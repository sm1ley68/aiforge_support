"""Compare lexical, hybrid and reranked retrieval against section IDs."""

import argparse
import json
from pathlib import Path
from statistics import quantiles
from time import monotonic

from aisupport_ml.commerce.mock import load_fixture

from .run_commerce import FIXTURE, NOW, parse_date

DEFAULT_CASES = Path(__file__).with_name("commerce_retrieval.json")


def measure(search, cases):
    # Warm once per query to report steady-state search, including query encoding.
    for case in cases:
        search(case)
    results = []
    for case in cases:
        start = monotonic()
        found = [source.id for source in search(case)]
        results.append({
            "id": case["id"], "found": found,
            "hit": set(case["expected_ids"]) <= set(found),
            "ms": (monotonic() - start) * 1000,
        })
    durations = [row["ms"] for row in results]
    return {
        "hits_at_5": sum(row["hit"] for row in results), "total": len(results),
        "p95_ms": round(quantiles(durations, n=20, method="inclusive")[-1], 2) if len(results) > 1
        else round(durations[0], 2),
        "cases": results,
    }


def run(args):
    agent, _ = load_fixture(args.fixture, None)
    kb = agent.knowledge
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not cases:
        raise ValueError("Expected at least one retrieval case")
    lexical = measure(lambda case: kb.search(case["query"], args.as_of, case.get("sku")), cases)
    report = {"lexical": lexical, "recommended": "lexical"}
    if args.qwen:
        from aisupport_ml.commerce.qwen import qwen_search

        for variant in ("hybrid", "reranked"):
            retriever = qwen_search(rerank=variant == "reranked")
            result = measure(
                lambda case: retriever(case["query"], kb.eligible(args.as_of, case.get("sku"), None)),
                cases,
            )
            report[variant] = result
            recovered = [row["id"] for old, row in zip(lexical["cases"], result["cases"])
                         if not old["hit"] and row["hit"]]
            regressions = [row["id"] for old, row in zip(lexical["cases"], result["cases"])
                           if old["hit"] and not row["hit"]]
            result.update(recovered=recovered, regressions=regressions)
            best = report[report["recommended"]]
            if (recovered and not regressions and result["hits_at_5"] > best["hits_at_5"]
                    and result["p95_ms"] <= lexical["p95_ms"] + 500):
                report["recommended"] = variant
            del retriever
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=parse_date, default=NOW, help="ISO 8601 timestamp for source validity")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--qwen", action="store_true", help="Load Qwen embeddings and reranker")
    run(parser.parse_args())
