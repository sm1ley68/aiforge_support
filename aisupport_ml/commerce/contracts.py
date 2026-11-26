from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from .catalog import CatalogOffer


@dataclass(frozen=True)
class Source:
    id: str
    version: str
    title: str
    text: str
    url: str
    sku: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    exceptions: tuple[str, ...] = ()
    reusable: bool = False
    aliases: tuple[str, ...] = ()
    customer_id: str | None = None

    def active(self, now: datetime, customer_id: str | None = None) -> bool:
        return (
            (self.customer_id is None or self.customer_id == customer_id)
            and (self.valid_from is None or self.valid_from <= now)
            and (self.valid_until is None or now < self.valid_until)
        )


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    aliases: tuple[str, ...]
    price: Decimal
    currency: str
    source: Source
    availability: str | None = None


@dataclass(frozen=True)
class Customer:
    id: str
    company: str
    tax_id: str


@dataclass(frozen=True)
class Seller:
    company: str
    tax_id: str
    bank: str
    bank_code: str
    settlement_account: str


@dataclass(frozen=True)
class OrderRecord:
    id: str
    customer_id: str
    source: Source


@dataclass(frozen=True)
class CartLine:
    sku: str
    quantity: int | None


@dataclass(frozen=True)
class PricedLine:
    sku: str
    name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    currency: str
    source: Source


@dataclass(frozen=True)
class Document:
    id: str
    kind: Literal["quote", "invoice"]
    customer: Customer | None
    lines: tuple[PricedLine, ...]
    currency: str
    total: Decimal
    conditions: tuple[Source, ...] = ()
    seller: Seller | None = None


@dataclass(frozen=True)
class PendingProduct:
    skus: tuple[str, ...]
    quantity: int | None


@dataclass(frozen=True)
class PendingConsultation:
    question: str
    kind: str
    fact: str | None
    special_terms: str | None
    skus: tuple[str, ...]


@dataclass(frozen=True)
class CatalogContext:
    mode: Literal["named", "need"]
    product: str | None = None
    edition: str | None = None
    users: int | None = None
    nodes: int | None = None
    term_months: int | None = None
    goal: str | None = None
    mail: str | None = None
    file_os: str | None = None
    deployment: Literal["local", "cloud"] | None = None
    budget_rub: int | None = None
    budget_unlimited: bool = False
    russian_only: bool = False
    shown_offers: tuple[str, ...] = ()


@dataclass(frozen=True)
class State:
    cart: tuple[CartLine, ...] = ()
    consultation: PendingConsultation | None = None
    pending: PendingProduct | None = None
    intent: Literal["quote", "invoice"] | None = None
    requested_terms: str | None = None
    last_quote: Document | None = None
    awaiting_price_confirmation: bool = False
    catalog_context: CatalogContext | None = None


@dataclass(frozen=True)
class Message:
    role: Literal["customer", "agent"]
    text: str


@dataclass(frozen=True)
class Handoff:
    id: str
    reason: str
    summary: str
    question: str
    cart: tuple[CartLine, ...]
    history: tuple[Message, ...]
    sources: tuple[Source, ...]
    catalog_context: CatalogContext | None = None


@dataclass(frozen=True)
class KnowledgeUpdate:
    status: Literal["published", "existing", "draft"]
    id: str


@dataclass(frozen=True)
class ModelCall:
    step: str
    duration_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


@dataclass(frozen=True)
class Trace:
    model: str
    prompt_version: str
    duration_ms: int
    calls: tuple[ModelCall, ...]


@dataclass(frozen=True)
class TurnResult:
    outcome: Literal["answer", "clarify", "recommend", "quote_ready", "invoice_ready", "handoff"]
    text: str
    state: State
    sources: tuple[Source, ...] = ()
    document: Document | None = None
    handoff: Handoff | None = None
    knowledge_update: KnowledgeUpdate | None = None
    trace: Trace | None = None
    products: tuple[CatalogOffer, ...] = ()
