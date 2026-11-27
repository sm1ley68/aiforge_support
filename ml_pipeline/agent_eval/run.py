"""Run the current HTTP API and worker against approved storefront scenarios."""

import argparse
import hashlib
import json
import logging
import math
import statistics
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import connect, sql
from psycopg.conninfo import make_conninfo

from evals import run_softline
from softline_backend.api import create_app
from softline_backend.commerce_bridge import commerce_from_env, commerce_egress_configured
from softline_backend.ollama_profile import DEFAULT_ENDPOINT, MODEL_4B, PROFILE
from softline_backend.store import ChatStore
from softline_backend.worker import process_one

HERE = Path(__file__).resolve().parent
EGRESS = re.compile(r"polza_egress turn_id=([0-9a-f-]+) decision=(\w+) category=(\w+)")
EXTRACTION = re.compile(
    r"(polza|ollama)_extraction turn_id=([0-9a-f-]+) (?:status=(\w+) )?duration_ms=(\d+)"
)
MODEL_SETTING_KEYS = {"POLZA_API_KEY", "LLM_API_KEY", "LLM_MODEL", "POLZA_TASK_MODEL", "LLM_BASE_URL"}


def settings(env_file, live, catalog, local=False):
    values = {}
    if env_file is not None and live:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in MODEL_SETTING_KEYS:
                values[key.strip()] = value.strip().strip("\"'")
    configured = {**values, "POLZA_EGRESS_MODE": "real" if live else "disabled",
                  "COMMERCE_CATALOG_INDEX_PATH": str(catalog),
                  "COMMERCE_MODEL_PROFILE": PROFILE if local else "polza" if live else "offline"}
    if not live:
        configured.update(POLZA_API_KEY="", LLM_API_KEY="")
    if local:
        configured.update(COMMERCE_OLLAMA_MODEL=MODEL_4B, COMMERCE_OLLAMA_ENDPOINT=DEFAULT_ENDPOINT)
    return configured


def invoke(manifest, catalog, mode, env_file):
    live = mode == "live"
    local = mode == "ollama"
    database_url = os.environ["TEST_DATABASE_URL"]
    schema_name = f"agent_eval_{uuid4().hex}"
    schema = sql.Identifier(schema_name)
    with (patch.dict(os.environ, settings(env_file, live, catalog, local)),
          connect(database_url, autocommit=True) as db):
        if (live or local) and not commerce_egress_configured():
            raise RuntimeError("The guarded model profile is not configured")
        commerce = commerce_from_env()
        db.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        try:
            store = ChatStore(make_conninfo(database_url, options=f"-c search_path={schema_name}"))
            store.initialize()
            return run_api(manifest, store, commerce, live, local=local)
        finally:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))


def run_api(manifest, store, commerce, live, *, local=False):
    manager_token = uuid4().hex
    with TemporaryDirectory() as folder, TestClient(create_app(store, manager_token=manager_token)) as client:
        log = Path(folder) / "worker.log"
        logger = logging.getLogger("softline_backend")
        handler = logging.FileHandler(log, encoding="utf-8")
        previous_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        def request(_base, path, *, method="GET", payload=None, token=None, expected=200):
            headers = {"Authorization": f"Bearer {token}"} if token else None
            response = client.request(method, path, json=payload, headers=headers)
            if response.status_code != expected:
                raise RuntimeError(f"HTTP {response.status_code}, expected {expected}")
            if method == "POST" and path.endswith("/messages"):
                process_one(store, commerce=commerce)
            return response.json()

        try:
            with patch.object(run_softline, "request", request):
                report = run_softline.run("local-test-client", manifest, manager_token, timeout=10)
        finally:
            logger.removeHandler(handler)
            handler.close()
            logger.setLevel(previous_level)

        events: dict[str, list[str]] = {}
        worker_log = log.read_text(encoding="utf-8")
        for turn_id, decision, category in EGRESS.findall(worker_log):
            events.setdefault(turn_id, []).append(f"{decision}:{category}")
        successful = {
            turn_id for turn_id, status, _, _ in run_softline.USAGE_RECORD.findall(worker_log) if status == "ok"
        }
        for case, details in zip(manifest["cases"], report["cases"], strict=True):
            for step, turn in zip(case["turns"], details["turns"], strict=True):
                decisions = events.get(turn.get("turn_id", ""), [])
                turn["egress"] = decisions
                expected = step.get("egress")
                if live and expected and not any(item.startswith(expected + ":") for item in decisions):
                    turn["failures"].append(f"Expected egress decision {expected}")
                if live and expected == "allowed" and turn.get("turn_id") not in successful:
                    turn["failures"].append("Polza reply did not pass validation")
                if live and expected == "blocked" and any(item.startswith("allowed:") for item in decisions):
                    turn["failures"].append("A local-only request made an external call")
        totals = [turn for case in report["cases"] for turn in case["turns"]]
        report["failed_turns"] = sum(bool(turn["failures"]) for turn in totals)
        report["passed_cases"] = sum(not any(turn["failures"] for turn in case["turns"]) for case in report["cases"])
        report["provider_usage"] = run_softline.usage_summary(log, report, None, None)
        provider = "ollama" if local else "polza"
        calls = [(turn_id, status or "ok", int(duration)) for model, turn_id, status, duration in EXTRACTION.findall(worker_log)
                 if model == provider]
        values = sorted(duration for _, status, duration in calls if status == "ok")
        report["extraction"] = {
            "calls": len(calls), "succeeded": len(values),
            "p50_ms": round(statistics.median(values)) if values else None,
            "p95_ms": values[math.ceil(0.95 * len(values)) - 1] if values else None,
        }
        reports_by_turn = {turn.get("turn_id"): turn for turn in totals}
        for turn_id, status, duration in calls:
            if turn_id in reports_by_turn:
                reports_by_turn[turn_id]["extraction"] = {"status": status, "ms": duration}
        report["mode"] = "ollama" if local else "live" if live else "offline"
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=("validation", "held_out"))
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--mode", choices=("offline", "live", "ollama"), required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ledger = (HERE / "PIPELINE.md").read_text(encoding="utf-8")
    gate = "C" if args.split == "held_out" else "B"
    if not re.search(rf"^- Gate {gate}: approved \d{{4}}-\d{{2}}-\d{{2}}$", ledger, re.M):
        parser.error(f"Gate {gate} has not been approved")
    if not args.catalog.is_file() or not os.environ.get("TEST_DATABASE_URL"):
        parser.error("Set a dedicated TEST_DATABASE_URL and a readable catalog")
    if args.split == "held_out" and args.mode != "live":
        parser.error("The final run uses the guarded live configuration")
    manifest_bytes = (HERE / f"{args.split}.json").read_bytes()
    fingerprint = hashlib.sha256(manifest_bytes).hexdigest()
    if fingerprint not in ledger:
        parser.error("The manifest differs from the approved corpus")
    if args.split == "held_out":
        local = HERE.parent / ".local" / "agent_eval"
        local.mkdir(parents=True, exist_ok=True)
        marker = local / f"held-out-{fingerprint}.started"
        marker.touch(exist_ok=False)
    report = invoke(json.loads(manifest_bytes), args.catalog, args.mode, args.env_file)
    report["manifest_sha256"] = fingerprint
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
