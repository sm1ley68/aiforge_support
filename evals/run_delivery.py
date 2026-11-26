"""Run synthetic ticket-to-Proposal checks. Run from the project root."""
import argparse
import asyncio
import json
import os
from contextlib import AsyncExitStack
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from time import monotonic

from aisupport_ml import investigate
from aisupport_ml.contracts import (
    Authorization, DeliveryEvent, Evidence, Order, ReadTools, TemporaryReadError, Ticket, Usage,
)
from aisupport_ml.intent import PROMPT_VERSION

CASE_FILE = Path(__file__).with_name("delivery_cases.json")
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
TOOLS = frozenset(name for name in vars(ReadTools) if not name.startswith("_"))


def evidence(source, record_id, version=None):
    return Evidence(
        f"{source}:{record_id}", source, record_id, record_id, NOW,
        f"https://example.test/{source}/{record_id}", record_id, version,
    )


class FixtureTools:
    def __init__(self, source):
        self.source = source
        self.order_failures = source.get("order_failures", 0)
        self.search_misses = source.get("search_misses", 0)
        self.policy = evidence("kb", "D-03#2", "4")

    async def get_customer_for_ticket(self, ticket):
        return evidence("crm", "C-1") if self.source.get("customer", True) else None

    async def find_orders(self, ticket, customer_id, hint):
        orders = self.source.get("orders", ["O-42"])
        return tuple(order_id for order_id in orders if hint is None or hint == order_id)

    async def get_order(self, ticket, customer_id, order_id):
        if self.order_failures:
            self.order_failures -= 1
            raise TemporaryReadError
        if self.source.get("order_missing"):
            return None
        deadline_offset = 1 if self.source.get("future_deadline") else -1
        return Order(
            order_id, customer_id, self.source.get("order_status", "delayed"),
            NOW + timedelta(days=deadline_offset), "msk", "parcel",
            evidence("orders", order_id, "17"),
        )

    async def get_order_events(self, ticket, order_id):
        status = self.source.get("event_status", "delayed")
        return DeliveryEvent(status, evidence("orders", f"{order_id}-event", "2")) if status else None

    async def get_related_cases(self, ticket, order_id):
        return (evidence("crm", f"{order_id}-previous-contact"),)

    async def search_policy(self, ticket, order, query):
        if self.search_misses:
            self.search_misses -= 1
            return ()
        return (self.policy,)

    async def authorize_delivery_inquiry(self, ticket, order, evidence_items):
        denial = self.source.get("denial")
        if denial:
            return Authorization(False, reason="Регламент запрещает действие.", missing_data=(denial,))
        return Authorization(True, (self.policy,))


class RecordedModel:
    def __init__(self, live_model, fixture_intent):
        self.live_model = live_model
        self.fixture_intent = fixture_intent
        self.output = None
        self.duration_ms = None
        self.error = None
        self.usage = None

    async def complete(self, system, ticket_text, schema):
        started = monotonic()
        try:
            if self.live_model is None:
                self.output, self.usage = dict(self.fixture_intent), Usage(0, 0)
            else:
                self.output, self.usage = await self.live_model.complete(system, ticket_text, schema)
            return self.output, self.usage
        except (TemporaryReadError, ValueError) as error:
            self.error = str(error) or type(error).__name__
            raise
        finally:
            self.duration_ms = round((monotonic() - started) * 1000)


async def evaluate(case, live_model, slots):
    expected = case["expected"]
    model = RecordedModel(live_model, case["intent"])
    async with slots:
        run = await investigate(
            Ticket("synthetic", case["id"], case["text"], "ru", TOOLS),
            FixtureTools(case["sources"]), model, now=NOW, timeout=20,
        )
    proposal = run.proposal
    target = proposal.action.target_id if proposal.action else None
    passed_checks = {step.tool for step in run.steps if step.status == "ok"}
    attempted_checks = {step.tool for step in run.steps}
    missed = sorted(set(expected["required_checks"]) - passed_checks)
    extra = sorted(set(expected["forbidden_checks"]) & attempted_checks)
    actual_intent = model.output if isinstance(model.output, dict) else {}
    intent_errors = [key for key, value in case["intent"].items() if actual_intent.get(key) != value]
    checks = {
        "outcome": expected["outcome"] == proposal.outcome,
        "action_target": expected["action_target"] == target,
        "missing_data": expected["missing_data"] == list(proposal.missing_data),
        "required_checks": not missed,
        "forbidden_checks": not extra,
        "intent": run.usage is not None and not intent_errors,
    }
    return {
        "case": case["id"],
        "passed": all(checks.values()),
        "checks": checks,
        "expected_outcome": expected["outcome"],
        "outcome": proposal.outcome,
        "expected_action_target": expected["action_target"],
        "action_target": target,
        "unexpected_action": target is not None and not checks["action_target"],
        "expected_missing_data": expected["missing_data"],
        "missing_data": proposal.missing_data,
        "missed_checks": missed,
        "extra_checks": extra,
        "intent_errors": intent_errors,
        "model_error": model.error,
        "steps": [asdict(step) for step in run.steps],
        "model_ms": model.duration_ms,
        "run_ms": run.duration_ms,
        "usage": asdict(model.usage) if model.usage else None,
    }


async def run(args):
    cases = json.loads(CASE_FILE.read_text())
    async with AsyncExitStack() as stack:
        model = None
        if args.mode == "polza":
            import httpx

            from aisupport_ml.polza import PolzaIntentModel

            if args.model:
                os.environ["LLM_MODEL"] = args.model
            client = await stack.enter_async_context(httpx.AsyncClient(timeout=18, trust_env=False))
            model = PolzaIntentModel(client)
        slots = asyncio.Semaphore(args.concurrency)
        results = await asyncio.gather(*(evaluate(case, model, slots) for case in cases))
    report = {
        "mode": args.mode,
        "model": model.model if model else "stub",
        "prompt_version": PROMPT_VERSION,
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "outcome_matches": sum(item["checks"]["outcome"] for item in results),
        "intent_matches": sum(item["checks"]["intent"] for item in results),
        "unexpected_actions": sum(item["unexpected_action"] for item in results),
        "median_model_ms": median(item["model_ms"] for item in results),
        "results": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stub", "polza"), default="stub")
    parser.add_argument("--model", help="Override LLM_MODEL for this Polza run")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be positive")
    if args.model and args.mode != "polza":
        parser.error("--model requires --mode polza")
    raise SystemExit(asyncio.run(run(args)))
