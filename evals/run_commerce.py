"""Replay storefront conversations and report end-state checks, timing and token cost."""

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median, quantiles

from aisupport_ml.commerce.extraction import PROMPT_VERSION
from aisupport_ml.commerce.mock import MockSupport, load_fixture
from aisupport_ml.contracts import Usage

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name("commerce_cases.json")
FIXTURE = ROOT / "fixtures" / "commerce_mock.json"
NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


class ReplayModel:
    model = "fixture"

    def __init__(self, turns):
        self.outputs = {turn["text"]: turn["model"] for turn in turns}
        self.current = None

    async def complete(self, system, text, schema):
        if "ids" in schema["properties"]:
            return {"ids": self.current.get("ids", [])}, Usage(0, 0)
        self.current = self.outputs[json.loads(text)["message"]]
        return self.current["extraction"], Usage(0, 0)


def validate(result, expected):
    document = result.document
    obtained = {
        "outcome": result.outcome,
        "total": str(document.total) if document else None,
        "lines": [[line.sku, line.quantity] for line in document.lines] if document else None,
        "reason": result.handoff.reason if result.handoff else None,
        "source_ids": [source.id for source in result.sources],
        "condition_ids": [source.id for source in document.conditions] if document else None,
        "knowledge": result.knowledge_update.status if result.knowledge_update else None,
        "uses_generated": any(source.id.startswith("faq-") for source in result.sources),
    }
    checks = dict(expected)
    contains = checks.pop("contains", None)
    mismatches = {key: {"expected": value, "actual": obtained[key]}
                  for key, value in checks.items() if obtained[key] != value}
    if contains and contains not in result.text:
        mismatches["contains"] = {"expected": contains, "actual": result.text}
    return mismatches


async def evaluate(case, args, live_model, repetition):
    agent, customers = load_fixture(args.fixture, live_model or ReplayModel(case["turns"]))
    storefront = MockSupport(agent)
    now = getattr(args, "as_of", NOW)
    results = []
    seen_messages = set()
    for index, turn in enumerate(case["turns"]):
        if "price_change" in turn:
            sku, price = turn["price_change"]
            product = agent.products[sku]
            agent.products[sku] = replace(
                product, price=Decimal(price), source=replace(product.source, version="2"),
            )
        conversation_id = turn.get("conversation", "chat")
        message_id = turn.get("message", str(index))
        result = await storefront.reply(
            conversation_id, message_id, turn["text"], customer=customers.get(case.get("buyer", "BUY-1")), now=now,
        )
        cached = (conversation_id, message_id) in seen_messages
        seen_messages.add((conversation_id, message_id))
        mismatches = validate(result, turn["expected"])
        results.append({
            "turn": index + 1, "outcome": result.outcome, "mismatches": mismatches,
            "trace": asdict(result.trace) if not cached else None,
        })
    counters = {
        "documents": len(storefront.documents),
        "handoffs": len(storefront.manager_queue),
        "articles": len(agent.knowledge.generated),
    }
    expectations = case.get("final", {})
    mismatches = {key: {"expected": value, "actual": counters[key]}
                  for key, value in expectations.items() if value != counters[key]}
    return {
        "case": case["id"], "group": case.get("group", "synthetic"), "repetition": repetition,
        "passed": not mismatches and all(not turn["mismatches"] for turn in results),
        "final": counters, "mismatches": mismatches, "turns": results,
    }


def model_cost(calls, input_rate, output_rate):
    if input_rate is None or output_rate is None:
        return None
    input_tokens = sum(call["input_tokens"] for call in calls)
    output_tokens = sum(call["output_tokens"] for call in calls)
    return (input_tokens * input_rate + output_tokens * output_rate) / Decimal(1_000_000)


def summary(results, args):
    groups = defaultdict(list)
    for row in results:
        groups[row["group"]].append(row)
    report = {}
    for label, entries in groups.items():
        totals = Counter()
        per_outcome = defaultdict(lambda: {"dialogues": 0, "estimated_cost_rub": Decimal(0)})
        latencies = []
        for entry in entries:
            turns = entry["turns"]
            traces = [turn["trace"] for turn in turns if turn["trace"] is not None]
            calls = [call for trace in traces for call in trace["calls"]]
            totals.update(calls=len(calls), input_tokens=sum(call["input_tokens"] for call in calls),
                          output_tokens=sum(call["output_tokens"] for call in calls))
            latencies.extend(trace["duration_ms"] for trace in traces)
            stats = per_outcome[turns[-1]["outcome"]]
            stats["dialogues"] += 1
            cost = model_cost(calls, args.input_rate, args.output_rate)
            if cost is None:
                stats["estimated_cost_rub"] = None
            else:
                stats["estimated_cost_rub"] += cost
        for stats in per_outcome.values():
            cost = stats["estimated_cost_rub"]
            stats["avg_estimated_cost_rub"] = (cost / stats["dialogues"] if cost is not None else None)
        report[label] = {
            "passed": sum(row["passed"] for row in entries), "total": len(entries),
            "p50_turn_ms": median(latencies),
            "p95_turn_ms": round(quantiles(latencies, n=20, method="inclusive")[-1]) if len(latencies) > 1 else latencies[0],
            **totals, "by_final_outcome": dict(per_outcome),
        }
    return report


async def run(args):
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.only:
        cases = [case for case in cases if case["id"] in args.only]
    if not cases:
        raise ValueError("No matching cases")

    async def evaluate_all(model):
        slots = asyncio.Semaphore(args.concurrency)

        async def limited(case, index):
            async with slots:
                return await evaluate(case, args, model, index)

        return await asyncio.gather(*(limited(case, repeat + 1) for case in cases
                                      for repeat in range(args.repeat if case.get("critical") else 1)))

    if args.mode == "polza":
        import httpx
        from aisupport_ml.polza import PolzaIntentModel

        async with httpx.AsyncClient(timeout=19, trust_env=False) as client:
            # Longer structured responses for carts, without changing the delivery adapter default.
            model = PolzaIntentModel(client, max_tokens=1024, reasoning_effort="low")
            results = await evaluate_all(model)
    else:
        results = await evaluate_all(None)
    report = {"mode": args.mode, "prompt_version": PROMPT_VERSION,
              "summary": summary(results, args), "cases": results}
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if all(result["passed"] for result in results) else 1


def parse_date(value: str):
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected ISO 8601 timestamp") from None
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp needs a timezone")
    return parsed


def rate(value: str):
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("expected a positive decimal rate") from None
    if not parsed.is_finite() or parsed < 0:
        raise argparse.ArgumentTypeError("expected a non-negative decimal rate")
    return parsed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stub", "polza"), default="stub")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--as-of", type=parse_date, default=NOW, help="ISO 8601 timestamp for source validity")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat scenarios marked critical")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--input-rate", type=rate, help="RUB per million input tokens")
    parser.add_argument("--output-rate", type=rate, help="RUB per million output tokens")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeat < 1 or args.concurrency < 1:
        parser.error("repeat and concurrency must be positive")
    if (args.input_rate is None) != (args.output_rate is None):
        parser.error("provide both rates or neither")
    raise SystemExit(asyncio.run(run(args)))
