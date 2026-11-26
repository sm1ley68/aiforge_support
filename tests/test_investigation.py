import json
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from aisupport_ml import investigate
from aisupport_ml.contracts import (
    Authorization, DeliveryEvent, Evidence, Order, TemporaryReadError, Ticket, Usage,
)
from aisupport_ml.search import PolicyIndex, PolicySection

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
TOOLS = frozenset({
    "get_customer_for_ticket", "find_orders", "get_order", "get_order_events",
    "get_related_cases", "search_policy", "authorize_delivery_inquiry",
})
TICKET = Ticket("demo", "T-1", "Заказ O-42 задерживается", "ru", TOOLS)


def evidence(source, record_id, version=None):
    return Evidence(source + ":" + record_id, source, record_id, record_id, NOW,
                    f"https://example.test/{source}/{record_id}", record_id, version)


class StubModel:
    def __init__(self, **changes):
        self.intent = dict(kind="delivery_delay", order_hint="O-42",
                           disputed_status=False, prior_contact=False)
        self.intent.update(changes)

    async def complete(self, system, ticket_text, schema):
        return self.intent, Usage(12, 8)


class StubTools:
    def __init__(self):
        self.candidates = ("O-42",)
        self.customer_id = "C-1"
        self.order_customer_id = "C-1"
        self.approved = True
        self.event_status = "delivered"
        self.order_failures = 0
        self.calls = []

    async def get_customer_for_ticket(self, ticket):
        self.calls.append("crm")
        return evidence("crm", self.customer_id)

    async def find_orders(self, ticket, customer_id, hint):
        return self.candidates

    async def get_order(self, ticket, customer_id, order_id):
        if self.order_failures:
            self.order_failures -= 1
            raise TemporaryReadError
        return Order(order_id, self.order_customer_id, "delayed", NOW - timedelta(days=1),
                     "msk", "parcel", evidence("orders", order_id, "17"))

    async def get_order_events(self, ticket, order_id):
        return DeliveryEvent(self.event_status, evidence("orders", "E-1", "2"))

    async def get_related_cases(self, ticket, order_id):
        return ()

    async def search_policy(self, ticket, order, query):
        return (evidence("kb", "D-03#2", "4"),)

    async def authorize_delivery_inquiry(self, ticket, order, evidence_items):
        if self.approved:
            return Authorization(True, (evidence("kb", "D-03#2", "4"),))
        return Authorization(False, reason="Уже есть открытый запрос.")


class InvestigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolved_has_only_current_evidence_and_serializes(self):
        result = await investigate(TICKET, StubTools(), StubModel(), now=NOW, version=2)
        proposal = result.proposal
        self.assertEqual(proposal.outcome, "resolved")
        self.assertEqual(proposal.action.target_id, "O-42")
        self.assertEqual(proposal.version, 2)
        self.assertEqual(result.usage, Usage(12, 8))
        evidence_ids = {item.id for item in proposal.evidence}
        self.assertEqual(set(proposal.action.evidence_ids), evidence_ids)
        self.assertTrue(all(set(claim.evidence_ids) <= evidence_ids for claim in proposal.claims))
        self.assertEqual(json.loads(json.dumps(asdict(proposal), default=str))["outcome"], "resolved")

    async def test_ambiguous_order_does_not_leak_candidates(self):
        tools = StubTools()
        tools.candidates = ("O-42", "O-999")
        result = await investigate(TICKET, tools, StubModel(), now=NOW)
        self.assertEqual(result.proposal.outcome, "needs_clarification")
        self.assertNotIn("O-999", repr(result))
        self.assertIsNone(result.proposal.action)

    async def test_mismatched_customer_keeps_crm_only(self):
        tools = StubTools()
        tools.order_customer_id = "C-other"
        result = await investigate(TICKET, tools, StubModel(), now=NOW)
        self.assertEqual(result.proposal.outcome, "escalate")
        self.assertEqual([item.source for item in result.proposal.evidence], ["crm"])

    async def test_conflict_does_not_reach_policy(self):
        result = await investigate(TICKET, StubTools(), StubModel(disputed_status=True), now=NOW)
        self.assertEqual(result.proposal.missing_data, ("consistent_delivery_status",))
        self.assertEqual(result.steps[-1].tool, "get_order_events")
        self.assertIsNone(result.proposal.action)

    async def test_retry_and_exhaustion(self):
        for failures, outcome in ((1, "resolved"), (2, "escalate")):
            with self.subTest(failures=failures):
                tools = StubTools()
                tools.order_failures = failures
                result = await investigate(TICKET, tools, StubModel(), now=NOW)
                self.assertEqual(result.proposal.outcome, outcome)
                self.assertEqual(sum(step.status == "retry" for step in result.steps), 1)

    async def test_denial_overrides_retrieval(self):
        tools = StubTools()
        tools.approved = False
        result = await investigate(TICKET, tools, StubModel(), now=NOW)
        self.assertEqual(result.proposal.summary, "Уже есть открытый запрос.")
        self.assertIsNone(result.proposal.action)

    async def test_invented_id_never_reaches_tools(self):
        tools = StubTools()
        result = await investigate(TICKET, tools, StubModel(order_hint="O-999"), now=NOW)
        self.assertEqual(result.proposal.missing_data, ("intent",))
        self.assertEqual(tools.calls, [])

    async def test_budget_and_permissions(self):
        result = await investigate(TICKET, StubTools(), StubModel(), now=NOW, max_calls=1)
        self.assertEqual(result.proposal.missing_data, ("find_orders",))
        tools = StubTools()
        result = await investigate(replace(TICKET, allowed_tools=frozenset()), tools, StubModel(), now=NOW)
        self.assertEqual(result.proposal.missing_data, ("get_customer_for_ticket",))
        self.assertEqual(tools.calls, [])


class PolicySearchTests(unittest.TestCase):
    def test_exact_match_expands_exceptions_and_filters_before_ranking(self):
        rule = PolicySection(
            "demo", "D-03", "2", "1", "Задержка доставки", "Порядок действий",
            "https://example.test/rule", NOW, region="msk", exceptions=(("D-03", "3", "1"),),
        )
        exception = replace(rule, section_id="3", title="Исключение", exceptions=())
        index = PolicyIndex((
            rule, exception, replace(rule, tenant_id="foreign"),
            replace(rule, section_id="4", valid_from=NOW + timedelta(days=1)),
            replace(rule, section_id="5", required_grant="restricted"),
            replace(rule, section_id="6", product="other"),
        ))
        order = Order("O-42", "C-1", "delayed", NOW, "msk", "parcel", evidence("orders", "O-42"))
        results = index.search(TICKET, order, "D-03", now=NOW, grants=frozenset())
        self.assertEqual([item.record_id for item in results], ["D-03#2", "D-03#3"])
        results = index.search(TICKET, order, "задержка", now=NOW, grants=frozenset())
        self.assertEqual([item.record_id for item in results], ["D-03#2", "D-03#3"])
