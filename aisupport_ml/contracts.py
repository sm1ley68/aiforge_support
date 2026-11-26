from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


@dataclass(frozen=True)
class Ticket:
    tenant_id: str
    ticket_id: str
    text: str
    language: str
    allowed_tools: frozenset[str]


@dataclass(frozen=True)
class Evidence:
    id: str
    source: Literal["crm", "orders", "kb"]
    record_id: str
    label: str
    observed_at: datetime
    url: str
    excerpt: str
    version: str | None = None


@dataclass(frozen=True)
class Claim:
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Intent:
    kind: Literal["delivery_delay", "other"]
    order_hint: str | None = None
    disputed_status: bool = False
    prior_contact: bool = False


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


class IntentModel(Protocol):
    async def complete(
        self, system: str, ticket_text: str, schema: dict
    ) -> tuple[dict, Usage]: ...


@dataclass(frozen=True)
class Order:
    id: str
    customer_id: str
    status: str
    promised_at: datetime
    region: str
    product: str
    evidence: Evidence


@dataclass(frozen=True)
class DeliveryEvent:
    status: str
    evidence: Evidence


@dataclass(frozen=True)
class Authorization:
    # Backend decision from the full applicable approved policy set.
    allowed: bool
    evidence: tuple[Evidence, ...] = ()
    reason: str | None = None
    missing_data: tuple[str, ...] = ()


class TemporaryReadError(Exception):
    """Adapter reports a retryable read failure."""


class ReadTools(Protocol):
    async def get_customer_for_ticket(self, ticket: Ticket) -> Evidence | None: ...
    async def find_orders(self, ticket: Ticket, customer_id: str, hint: str | None) -> tuple[str, ...]: ...
    async def get_order(self, ticket: Ticket, customer_id: str, order_id: str) -> Order | None: ...
    async def get_order_events(self, ticket: Ticket, order_id: str) -> DeliveryEvent | None: ...
    async def get_related_cases(self, ticket: Ticket, order_id: str) -> tuple[Evidence, ...]: ...
    async def search_policy(self, ticket: Ticket, order: Order, query: str) -> tuple[Evidence, ...]: ...
    async def authorize_delivery_inquiry(self, ticket: Ticket, order: Order, evidence: tuple[Evidence, ...]) -> Authorization: ...


@dataclass(frozen=True)
class Action:
    id: str
    kind: Literal["create_delivery_inquiry"]
    target_id: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Proposal:
    version: int
    outcome: Literal["resolved", "needs_clarification", "escalate"]
    summary: str
    claims: tuple[Claim, ...]
    evidence: tuple[Evidence, ...]
    action: Action | None
    reply_draft: str | None
    missing_data: tuple[str, ...]
    escalation_team: str | None = None


@dataclass(frozen=True)
class Step:
    tool: str
    reason: str
    status: Literal["ok", "retry", "unavailable"]
    duration_ms: int
    evidence_ids: tuple[str, ...] = ()
