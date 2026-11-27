"""Compare the two storefront profiles once on an independently frozen manifest."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import httpx

from aisupport_ml.polza import DEFAULT_MODEL
from softline_backend.ollama_profile import DEFAULT_ENDPOINT, MODEL_4B

from .run import invoke


EXPECTED_OLLAMA_DIGEST = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"


def preload():
    with httpx.Client(base_url=DEFAULT_ENDPOINT.removesuffix("/api/chat"), timeout=60, trust_env=False, follow_redirects=False) as client:
        tags = client.get("/api/tags")
        tags.raise_for_status()
        models = tags.json()["models"]
        match = next((row for row in models if row["name"] == MODEL_4B), None)
        if (not match or match["digest"] != EXPECTED_OLLAMA_DIGEST
                or match["details"]["quantization_level"] != "Q4_K_M"):
            raise RuntimeError("Install the pinned Qwen Q4_K_M weights before the comparison")
        warm = client.post("/api/generate", json={
            "model": MODEL_4B, "stream": False, "keep_alive": "10m", "options": {"num_ctx": 2048},
        })
        warm.raise_for_status()
        loaded = client.get("/api/ps")
        loaded.raise_for_status()
        usage = next(row for row in loaded.json()["models"] if row["name"] == MODEL_4B)
        return {"digest": match["digest"], "weights_bytes": match["size"],
                "loaded_bytes": usage["size"], "vram_bytes": usage["size_vram"]}


def summarize(report):
    totals, passed = Counter(), Counter()
    for case in report["cases"]:
        for turn in case["turns"]:
            for name, ok in turn["checks"].items():
                totals[name] += 1
                passed[name] += int(ok)
    return {name: {"passed": passed[name], "total": total} for name, total in sorted(totals.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = args.manifest.read_bytes()
    fingerprint = hashlib.sha256(data).hexdigest()
    if fingerprint != args.sha256:
        parser.error("The closed manifest does not match its frozen fingerprint")
    manifest = json.loads(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    marker = args.manifest.with_name(f"comparison-{fingerprint}.started")
    if marker.exists() or args.output.exists():
        parser.error("The closed round was already started or the report exists")
    hardware = preload()
    marker.touch(exist_ok=False)

    profiles = {}
    for profile, mode, name in (("qwen", "ollama", MODEL_4B), ("haiku", "live", DEFAULT_MODEL)):
        report = invoke(manifest, args.catalog, mode, args.env_file)
        report["model"] = name
        report["dimensions"] = summarize(report)
        profiles[profile] = report
        payload = {"dataset": manifest["dataset"], "manifest_sha256": fingerprint,
                   "ollama_model": hardware, "profiles": profiles}
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(profile, json.dumps({key: report[key] for key in
                                  ("passed_cases", "turn_count", "p50_ms", "p95_ms", "dimensions", "extraction")}),
              flush=True)
    return 0 if all(report["extraction"]["succeeded"] for report in profiles.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
