from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, JsonValue, StringConstraints, field_validator, model_validator

from aisupport_ml.commerce.contracts import KnowledgeUpdate


class NewChat(BaseModel):
    chat_id: UUID
    chat_token: str


class MessageInput(BaseModel):
    client_message_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    text: str = Field(min_length=1, max_length=8000)

    @field_validator("client_message_id", "text")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Null characters are not allowed")
        return value

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message text is empty")
        return value


class TurnAccepted(BaseModel):
    turn_id: UUID


class Source(BaseModel):
    title: str
    url: HttpUrl


class VerifiedFact(BaseModel):
    field: str
    value: str
    source: Source


class ProductCard(BaseModel):
    offer_id: str
    sku: str | None = None
    title: str
    url: HttpUrl
    verified_facts: list[VerifiedFact] = Field(default_factory=list)
    match_summary: str
    price_amount: Decimal | None = None
    currency: str | None = None
    availability: bool | None = None
    snapshot_at: datetime


class CatalogReference(BaseModel):
    offer_id: str
    sku: str | None = None
    title: str


class HandoffDetails(BaseModel):
    reason: Literal["customer_requested", "insufficient_evidence", "commercial_terms", "provider_unavailable"]
    summary: str
    requirements: dict[str, str] = Field(default_factory=dict)
    candidate_ids: list[str] = Field(default_factory=list)
    evidence: list[Source] = Field(default_factory=list)


class QuoteSnapshot(BaseModel):
    offer_id: str
    sku: str | None = None
    title: str
    quantity: int = Field(ge=1, le=10000)
    unit_label: Literal["уп.", "лиц.", "ПК", "узел"]
    unit_price: Decimal
    total: Decimal
    currency: str
    catalog_snapshot_at: datetime
    issued_at: datetime
    source: Source


class TurnResult(BaseModel):
    outcome: Literal["answer", "clarify", "recommend", "handoff"]
    text: str
    products: list[ProductCard] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    handoff: HandoffDetails | None = None
    catalog_selection: CatalogReference | None = None
    commerce_state: dict[str, JsonValue] | None = None
    quote: QuoteSnapshot | None = None
    knowledge_update: KnowledgeUpdate | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def check_handoff(self):
        if (self.outcome == "handoff") != (self.handoff is not None):
            raise ValueError("Only a handoff outcome includes manager details")
        return self


class TurnView(BaseModel):
    turn_id: UUID
    status: Literal["queued", "processing", "succeeded", "failed"]
    outcome: Literal["answer", "clarify", "recommend", "handoff"] | None = None
    text: str | None = None
    products: list[ProductCard] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    quote: QuoteSnapshot | None = None
    error: str | None = None


class MessageView(BaseModel):
    turn_id: UUID
    role: Literal["user", "assistant"]
    text: str
    author: Literal["manager"] | None = None
    catalog_references: list[CatalogReference] = Field(default_factory=list, exclude=True)


class HandoffView(HandoffDetails):
    handoff_id: UUID
    turn_id: UUID
    chat_id: UUID


class HandoffCase(HandoffView):
    messages: list[MessageView]
