"""Synthetic commerce fixture loading and in-memory integration for demos and evals."""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .contracts import Customer, Message, OrderRecord, Product, Seller, Source, State, TurnResult
from .engine import CommerceAgent
from .retrieval import KnowledgeBase


def _source(data):
    values = dict(data)
    for key in ("valid_from", "valid_until"):
        if values.get(key):
            values[key] = datetime.fromisoformat(values[key])
            if values[key].utcoffset() is None:
                raise ValueError(f"{key} must have a timezone")
    for key in ("aliases", "exceptions"):
        if key in values:
            values[key] = tuple(values[key])
    return Source(**values)


def load_fixture(path: Path, model, **options):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    products = tuple(Product(
        item["sku"], item["name"], tuple(item.get("aliases", ())), Decimal(item["price"]),
        item["currency"], _source(item["source"]), item.get("availability"),
    ) for item in fixture["catalog"])
    knowledge = KnowledgeBase([_source(item) for item in fixture["knowledge"]])
    orders = tuple(
        OrderRecord(item["id"], item["customer_id"], _source(item["source"]))
        for item in fixture.get("orders", ())
    )
    conditions = tuple(_source(item) for item in fixture.get("conditions", ()))
    customers = {item["id"]: Customer(**item) for item in fixture.get("customers", ())}
    seller = Seller(**fixture["seller"]) if fixture.get("seller") else None
    return CommerceAgent(
        model, products=products, knowledge=knowledge, orders=orders, conditions=conditions, seller=seller, **options,
    ), customers


@dataclass
class _Conversation:
    owner: str | None
    state: State = State()
    history: tuple[Message, ...] = ()
    turns: dict[str, tuple[str, TurnResult]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MockSupport:
    def __init__(self, agent: CommerceAgent):
        self.agent = agent
        self.conversations: dict[str, _Conversation] = {}
        self.manager_queue = {}
        self.documents = {}

    async def reply(self, conversation_id, message_id, text, *, customer=None, now=None):
        """Supply customer identity from authentication and serialize writes per conversation."""
        customer_id = customer.id if customer else None
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = _Conversation(customer_id)
        conversation = self.conversations[conversation_id]
        if conversation.owner != customer_id:
            raise PermissionError("Conversation does not belong to customer")
        async with conversation.lock:
            previous = conversation.turns.get(message_id)
            if previous:
                if previous[0] != text:
                    raise ValueError("Message ID already has a different payload")
                return previous[1]
            result = await self.agent.reply(
                conversation_id, message_id, text, state=conversation.state,
                history=conversation.history, customer=customer, now=now,
            )
            conversation.state = result.state
            conversation.history += (Message("customer", text), Message("agent", result.text))
            if result.handoff:
                self.manager_queue[result.handoff.id] = result.handoff
            if result.document:
                self.documents[result.document.id] = (conversation_id, result.document)
            conversation.turns[message_id] = (text, result)
            return result

    def get_document(self, conversation_id, document_id, *, customer=None):
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.owner != (customer.id if customer else None):
            raise PermissionError("Conversation does not belong to customer")
        stored_conversation, document = self.documents[document_id]
        if stored_conversation != conversation_id:
            raise PermissionError("Document does not belong to conversation")
        return document
