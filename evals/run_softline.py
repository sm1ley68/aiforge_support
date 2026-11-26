"""Run Softline acceptance cases against the chat HTTP API."""

import argparse
import json
import math
import os
import re
import statistics
import time
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


USAGE_RECORD = re.compile(
    r"polza_extraction turn_id=([0-9a-f-]{36}) status=(\w+) duration_ms=\d+ "
    r"prompt_tokens=(\d+|None) completion_tokens=(\d+|None)"
)


def request(base_url, path, *, method="GET", payload=None, token=None, expected=200):
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(base_url + path, method=method, data=data, headers=headers), timeout=5) as response:
            if response.status != expected:
                raise RuntimeError(f"HTTP {response.status}, expected {expected}")
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}, expected {expected}") from None


def wait_for_turn(base_url, chat_path, turn_id, token, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        turn = request(base_url, f"{chat_path}/turns/{turn_id}", token=token)
        if turn["status"] in {"succeeded", "failed"}:
            return turn
        time.sleep(0.15)
    raise TimeoutError("Turn did not reach a terminal state")


def check_turn(turn, step):
    failures = []
    accepted = step.get("outcomes")
    if turn["status"] != "succeeded":
        failures.append(f"terminal state {turn['status']}")
    if accepted and turn["outcome"] not in accepted:
        failures.append(f"outcome {turn['outcome']} is outside the expected set")
    skus = {card["sku"] for card in turn["products"]}
    if "skus" in step and skus != set(step["skus"]):
        failures.append("returned SKUs differ from the case")
    offer_ids = {card["offer_id"] for card in turn["products"]}
    if not set(step.get("offer_ids_contain", ())).issubset(offer_ids):
        failures.append("an expected offer ID was not returned")
    if skus.intersection(step.get("excluded_skus", ())):
        failures.append("a prohibited SKU was returned")
    source_urls = {source["url"] for source in turn["sources"]}
    if step.get("sources") and not source_urls:
        failures.append("sources are missing")
    if not set(step.get("source_urls", ())).issubset(source_urls):
        failures.append("an expected source URL is missing")
    if any(value.casefold() not in (turn["text"] or "").casefold() for value in step.get("text_contains", ())):
        failures.append("an expected fact is missing from the response")
    return failures


def run_case(base_url, case, manager_token, timeout):
    chat = request(base_url, "/chats", method="POST", expected=201)
    chat_path = f"/chats/{chat['chat_id']}"
    token = chat["chat_token"]
    results = []
    for number, step in enumerate(case["turns"], 1):
        payload = {"client_message_id": str(uuid4()), "text": step["text"]}
        started = time.monotonic()
        try:
            accepted = request(
                base_url, f"{chat_path}/messages", method="POST", payload=payload, token=token, expected=202
            )
            turn_id = accepted["turn_id"]
            turn = wait_for_turn(base_url, chat_path, turn_id, token, timeout)
            elapsed_ms = round(1000 * (time.monotonic() - started))
            failures = check_turn(turn, step)
            if step.get("repeat"):
                repeated = request(
                    base_url, f"{chat_path}/messages", method="POST", payload=payload, token=token, expected=202
                )
                if repeated["turn_id"] != turn_id:
                    failures.append("repeated submission created a new turn")
            if step.get("manager"):
                if not manager_token:
                    failures.append("manager token was not configured for this case")
                else:
                    detail = request(base_url, f"/manager/handoffs/{turn_id}", token=manager_token)
                    queue = request(base_url, "/manager/handoffs?limit=100", token=manager_token)
                    if detail["chat_id"] != chat["chat_id"] or not detail["messages"]:
                        failures.append("manager case is missing chat history")
                    if sum(item["handoff_id"] == turn_id for item in queue) != 1:
                        failures.append("manager queue does not contain exactly one case for the turn")
            results.append({
                "step": number,
                "turn_id": turn_id,
                "outcome": turn["outcome"],
                "elapsed_ms": elapsed_ms,
                "failures": failures,
            })
        except (TimeoutError, RuntimeError, OSError) as exc:
            results.append({"step": number, "outcome": None, "failures": [type(exc).__name__], "error": str(exc)})
    return {"case": case["id"], "turns": results}


def run(base_url, manifest, manager_token, timeout):
    started = time.monotonic()
    cases = [run_case(base_url, case, manager_token, timeout) for case in manifest["cases"]]
    turns = [turn for case in cases for turn in case["turns"]]
    durations = sorted(turn["elapsed_ms"] for turn in turns if "elapsed_ms" in turn)
    return {
        "dataset": manifest["dataset"],
        "case_count": len(cases),
        "turn_count": len(turns),
        "failed_turns": sum(bool(turn["failures"]) for turn in turns),
        "p50_ms": round(statistics.median(durations)) if durations else None,
        "p95_ms": durations[math.ceil(0.95 * len(durations)) - 1] if durations else None,
        "report_elapsed_ms": round(1000 * (time.monotonic() - started)),
        "cases": cases,
    }


def usage_summary(log: Path, report: dict, input_rate: Decimal | None, output_rate: Decimal | None):
    turn_ids = {turn["turn_id"] for case in report["cases"] for turn in case["turns"] if "turn_id" in turn}
    calls = incomplete = succeeded = prompt = completion = 0
    with log.open(encoding="utf-8") as file:
        for line in file:
            match = USAGE_RECORD.search(line)
            if not match or match[1] not in turn_ids:
                continue
            calls += 1
            succeeded += match[2] == "ok"
            if "None" in (match[3], match[4]):
                incomplete += 1
                continue
            prompt += int(match[3])
            completion += int(match[4])

    estimate = None
    if calls and not incomplete and input_rate is not None and output_rate is not None:
        estimate = (prompt * input_rate + completion * output_rate) / 1_000_000
    return {
        "calls": calls,
        "successful_calls": succeeded,
        "calls_without_token_counts": incomplete,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "estimated_cost_rub": str(estimate) if estimate is not None else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--usage-log", type=Path)
    parser.add_argument("--input-rub-per-million", type=Decimal)
    parser.add_argument("--output-rub-per-million", type=Decimal)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = run(args.base_url.rstrip("/"), manifest, os.getenv("MANAGER_TOKEN"), args.timeout)
    if args.usage_log:
        report["provider_usage"] = usage_summary(
            args.usage_log, report, args.input_rub_per_million, args.output_rub_per_million
        )
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return int(bool(report["failed_turns"]))


if __name__ == "__main__":
    raise SystemExit(main())
