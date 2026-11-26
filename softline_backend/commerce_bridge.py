import asyncio
import logging
import os
import re
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from pydantic import TypeAdapter

from aisupport_ml.commerce import CommerceAgent
from aisupport_ml.commerce.catalog import CatalogOffer, SoftlineCatalog
from aisupport_ml.commerce.contracts import CatalogContext, Message, State
from aisupport_ml.commerce.retrieval import KnowledgeBase
from aisupport_ml.contracts import IntentModel, TemporaryReadError
from aisupport_ml.polza import DEFAULT_MODEL, PolzaIntentModel

from .contracts import HandoffDetails, MessageView, ProductCard, Source, TurnResult, VerifiedFact
from .knowledge import validated_url
from .store import ClaimedTurn


logger = logging.getLogger(__name__)
STATE = TypeAdapter(State)
FEED_TIMEZONE = timezone(timedelta(hours=3))
OFFER_ID = re.compile(r"id предложения\s*[:№#]?\s*([0-9]{2,40})[?!.]?", re.I)
COMMERCIAL_REQUEST = re.compile(r"скидк|постоплат|предоплат|рассроч|коммерческ\w+ предложен|\bкп\b", re.I)


class CatalogModel:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def complete(self, system, text, schema):
        if not self.api_key:
            raise TemporaryReadError("Catalog extraction provider is unconfigured")
        async with httpx.AsyncClient(timeout=5) as client:
            adapter = PolzaIntentModel(client, api_key=self.api_key, model=self.model, max_tokens=384)
            return await adapter.complete(system, text, schema)


def commerce_provider_key() -> str:
    return os.getenv("POLZA_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()


def _card(offer: CatalogOffer, *, node_price: bool) -> ProductCard | None:
    url = validated_url(offer.url)
    if url is None:
        return None
    try:
        snapshot = datetime.fromisoformat(offer.snapshot_at)
    except ValueError:
        return None
    if snapshot.tzinfo is None:
        snapshot = snapshot.replace(tzinfo=FEED_TIMEZONE)
    source = Source(title=offer.title, url=url)
    attributes = {
        "license_type": offer.license_type,
        "term": offer.term,
        "user_limit": offer.user_limit,
        "catalog_version": offer.edition,
        "platform": offer.platform,
        "operating_system": offer.operating_system,
    }
    facts = [VerifiedFact(field=field, value=str(value), source=source)
             for field, value in attributes.items() if value is not None]
    summary = "Данные из снимка каталога"
    if node_price and "по количеству узлов" in offer.title.casefold():
        summary = "Цена указана за узел"
    return ProductCard(
        offer_id=offer.offer_id, sku=offer.vendor_code, title=offer.title, url=url,
        verified_facts=facts, match_summary=summary, price_amount=offer.price,
        currency=offer.currency, availability=offer.available, snapshot_at=snapshot,
    )


def _requirements(context: CatalogContext | None) -> dict[str, str]:
    if context is None:
        return {}
    requirements = {}
    for field in fields(context):
        value = getattr(context, field.name)
        if field.name not in {"mode", "shown_offers"} and value is not None and value is not False:
            requirements[field.name] = "да" if value is True else str(value)
    return requirements


class CommerceBridge:
    def __init__(self, index_path: Path, model: IntentModel, *, provider_enabled: bool = False):
        self.agent = CommerceAgent(
            model, knowledge=KnowledgeBase([]), catalog_index=SoftlineCatalog(index_path), model_timeout=6
        )
        self.provider_enabled = provider_enabled

    def reply(
        self, turn: ClaimedTurn, history: list[MessageView], persisted_state: dict | None
    ) -> TurnResult:
        state = STATE.validate_python(persisted_state) if persisted_state is not None else State()
        messages = tuple(Message("customer" if entry.role == "user" else "agent", entry.text) for entry in history)
        text = turn.message_text
        direct_id = OFFER_ID.fullmatch(text.strip())
        query = direct_id[1] if direct_id else text
        result = asyncio.run(self.agent.reply(
            str(turn.chat_id), str(turn.turn_id), query, state=state, history=messages
        ))

        if result.trace is not None:
            logger.info(
                "commerce_turn turn_id=%s duration_ms=%d prompt_version=%s outcome=%s",
                turn.turn_id, result.trace.duration_ms, result.trace.prompt_version, result.outcome,
            )
            if self.provider_enabled:
                for call in result.trace.calls:
                    logger.info(
                        "polza_extraction turn_id=%s status=%s duration_ms=%d prompt_tokens=%s completion_tokens=%s",
                        turn.turn_id, call.error or "ok", call.duration_ms,
                        call.input_tokens if not call.error else None, call.output_tokens if not call.error else None,
                    )

        saved_state = STATE.dump_python(result.state, mode="json")
        sources = []
        for source in result.sources:
            if url := validated_url(source.url):
                sources.append(Source(url=url, title=source.title))
        if result.handoff is not None:
            context = result.handoff.catalog_context
            reason = "insufficient_evidence"
            if result.handoff.reason == "extraction_unavailable":
                reason = "provider_unavailable"
            elif result.handoff.reason == "manager_requested":
                reason = "commercial_terms" if COMMERCIAL_REQUEST.search(text) else "customer_requested"
            summary = " ".join(text.split())[:240]
            return TurnResult(
                outcome="handoff", text="Передал ваше обращение менеджеру.", sources=sources,
                commerce_state=saved_state,
                handoff=HandoffDetails(
                    reason=reason, summary=summary, requirements=_requirements(context),
                    candidate_ids=list(context.shown_offers) if context else [], evidence=sources,
                ),
            )

        products = [
            card for offer in result.products
            if (card := _card(offer, node_price=result.outcome == "recommend")) is not None
        ]
        if result.outcome not in {"answer", "clarify", "recommend"} or len(products) != len(result.products):
            return TurnResult(
                outcome="clarify", text="Уточните позицию по артикулу или попросите менеджера.",
                commerce_state=saved_state,
            )
        return TurnResult(
            outcome=result.outcome, text=result.text, products=products, sources=sources,
            commerce_state=saved_state,
        )


def commerce_from_env() -> CommerceBridge | None:
    path = os.getenv("COMMERCE_CATALOG_INDEX_PATH", "").strip()
    if not path:
        return None
    key = commerce_provider_key()
    model = os.getenv("POLZA_TASK_MODEL", "").strip() or os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL
    return CommerceBridge(Path(path), CatalogModel(key, model), provider_enabled=bool(key))
