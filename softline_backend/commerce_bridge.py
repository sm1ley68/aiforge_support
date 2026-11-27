import asyncio
import json
import logging
import os
import re
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

import httpx
from pydantic import TypeAdapter

from aisupport_ml.commerce import CommerceAgent
from aisupport_ml.commerce.catalog import CatalogOffer, SoftlineCatalog
from aisupport_ml.commerce.contracts import CatalogContext, Message, Recommendation, State
from aisupport_ml.commerce.indexed_chat import INDEXED_SCHEMA
from aisupport_ml.commerce.retrieval import KnowledgeBase
from aisupport_ml.commerce.softline_evidence import CATALOG_KNOWLEDGE, desktop_evidence
from aisupport_ml.contracts import IntentModel, TemporaryReadError
from aisupport_ml.polza import DEFAULT_BASE_URL, DEFAULT_MODEL, PolzaIntentModel

from .contracts import HandoffDetails, MessageView, ProductCard, Source, TurnResult, VerifiedFact
from .knowledge import validated_url
from .polza_egress import (
    ENDPOINT, RESPONSE_FIELDS, SYSTEM, LocalFilter, TurnScope, block, load_egress_filter, polza_scope, prepare, record,
)
from .store import ClaimedTurn


logger = logging.getLogger(__name__)
STATE = TypeAdapter(State)
FEED_TIMEZONE = timezone(timedelta(hours=3))
OFFER_ID = re.compile(r"id предложения\s*[:№#]?\s*([0-9]{2,40})[?!.]?", re.I)
COMMERCIAL_REQUEST = re.compile(r"скидк|постоплат|предоплат|рассроч|коммерческ\w+ предложен|\bкп\b", re.I)


class CatalogModel:
    def __init__(
        self, api_key: str, model: str, *, enabled: bool = False, checker: LocalFilter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.enabled = enabled
        self.checker = checker
        self.transport = transport

    async def complete(self, _system, text, schema):
        if not self.enabled or not self.api_key:
            block("disabled")
        if self.checker is None:
            block("filter_unavailable")
        if self.model != DEFAULT_MODEL:
            block("model_not_allowed")
        if schema != INDEXED_SCHEMA or INDEXED_SCHEMA["properties"].keys() != RESPONSE_FIELDS:
            block("schema_not_allowed")
        approved = await prepare(text, self.checker)
        expected = {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": approved.text}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ticket_intent", "strict": True, "schema": INDEXED_SCHEMA},
            },
            "stream": False, "temperature": 0, "max_tokens": 384,
        }

        sent = False

        async def validate_request(request: httpx.Request):
            nonlocal sent
            try:
                body = json.loads(request.content)
            except (TypeError, ValueError):
                block("request_mismatch")
            if (
                request.method != "POST" or str(request.url) != ENDPOINT or body != expected
                or any(key in request.headers for key in ("cookie", "forwarded", "x-forwarded-for", "x-real-ip"))
            ):
                block("request_mismatch")
            record("allowed", "technical_fields")
            sent = True

        async def record_response(response: httpx.Response):
            record("api_response", f"http_{response.status_code}")

        started = monotonic()
        status = "unavailable"
        usage = None
        try:
            async with httpx.AsyncClient(
                timeout=5, transport=self.transport, trust_env=False,
                event_hooks={"request": [validate_request], "response": [record_response]},
            ) as client:
                try:
                    adapter = PolzaIntentModel(client, api_key=self.api_key, model=self.model, max_tokens=384)
                except (ValueError, httpx.InvalidURL):
                    block("invalid_endpoint")
                result, usage = await adapter.complete(SYSTEM, approved.text, INDEXED_SCHEMA)
            validated = approved.validate_answer(result)
            status = "ok"
            return validated, usage
        except (TemporaryReadError, ValueError) as error:
            status = type(error).__name__
            raise
        finally:
            if sent:
                scope = polza_scope.get()
                logger.info(
                    "polza_extraction turn_id=%s status=%s duration_ms=%d prompt_tokens=%s completion_tokens=%s",
                    scope.turn_id if scope else "-", status, int((monotonic() - started) * 1000),
                    usage.input_tokens if usage else None, usage.output_tokens if usage else None,
                )


def commerce_provider_key() -> str:
    return os.getenv("POLZA_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()


def _card(offer: CatalogOffer, recommendation: Recommendation | None) -> ProductCard | None:
    url = validated_url(offer.url)
    if url is None:
        return None
    try:
        snapshot = datetime.fromisoformat(offer.snapshot_at)
    except ValueError:
        return None
    if snapshot.tzinfo is None:
        snapshot = snapshot.replace(tzinfo=FEED_TIMEZONE)
    source = Source(title=f"{offer.title} · фид от {offer.snapshot_at}", url=url)
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
    if desktop := desktop_evidence(offer):
        summary = "Цена указана за ПК"
        if offer.term is None and desktop.term_months is None and (desktop_url := validated_url(desktop.source.url)):
            facts.append(VerifiedFact(field="term", value="бессрочная", source=Source(title=desktop.source.title, url=desktop_url)))
    elif recommendation is not None:
        summary = "Цена указана за узел" if "по количеству узлов" in offer.title.casefold() else "Цена указана за ПК"
    if recommendation is not None:
        for field, value, evidence in (
            ("edition", recommendation.edition, recommendation.edition_source),
            ("package_size", recommendation.package_size, recommendation.package_source),
        ):
            if evidence_url := validated_url(evidence.url):
                facts.append(VerifiedFact(field=field, value=value, source=Source(title=evidence.title, url=evidence_url)))
        facts.extend((
            VerifiedFact(field="license_quantity", value=str(recommendation.quantity), source=source),
            VerifiedFact(field="total_price", value=f"{recommendation.total:.2f} {offer.currency}", source=source),
        ))
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
    def __init__(self, index_path: Path, model: IntentModel):
        self.agent = CommerceAgent(
            model, knowledge=KnowledgeBase(CATALOG_KNOWLEDGE), catalog_index=SoftlineCatalog(index_path), model_timeout=6
        )

    def restore_knowledge(self, publications: list[tuple[str, str, str]]) -> None:
        self.agent.knowledge.restore_publications(publications, datetime.now(timezone.utc))

    def reply(
        self, turn: ClaimedTurn, history: list[MessageView], persisted_state: dict | None
    ) -> TurnResult:
        state = STATE.validate_python(persisted_state) if persisted_state is not None else State()
        messages = tuple(Message("customer" if entry.role == "user" else "agent", entry.text) for entry in history)
        text = turn.message_text
        direct_id = OFFER_ID.fullmatch(text.strip())
        query = direct_id[1] if direct_id else text
        scope = TurnScope(str(turn.turn_id), text, tuple(message.text for message in history), persisted_state)
        token = polza_scope.set(scope)
        try:
            result = asyncio.run(self.agent.reply(
                str(turn.chat_id), str(turn.turn_id), query, state=state, history=messages
            ))
        finally:
            polza_scope.reset(token)

        if result.trace is not None:
            logger.info(
                "commerce_turn turn_id=%s duration_ms=%d prompt_version=%s outcome=%s",
                turn.turn_id, result.trace.duration_ms, result.trace.prompt_version, result.outcome,
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
            requirements = _requirements(context)
            if result.handoff.reason in {"conflicting_sources", "support_follow_up"}:
                label = "Спорный факт" if result.handoff.reason == "conflicting_sources" else "Что проверить"
                requirements[label] = result.handoff.question
            return TurnResult(
                outcome="handoff", text="Передал ваше обращение менеджеру.", sources=sources,
                commerce_state=saved_state,
                handoff=HandoffDetails(
                    reason=reason, summary=summary, requirements=requirements,
                    candidate_ids=list(context.shown_offers) if context else [], evidence=sources,
                ),
            )

        recommendations = {detail.offer_id: detail for detail in result.recommendations}
        products = [
            card for offer in result.products
            if (card := _card(offer, recommendations.get(offer.offer_id))) is not None
        ]
        if result.outcome not in {"answer", "clarify", "recommend"} or len(products) != len(result.products):
            return TurnResult(
                outcome="clarify", text="Уточните позицию по артикулу или попросите менеджера.",
                commerce_state=saved_state,
            )
        return TurnResult(
            outcome=result.outcome, text=result.text, products=products, sources=sources,
            commerce_state=saved_state, knowledge_update=result.knowledge_update,
        )


def commerce_from_env() -> CommerceBridge | None:
    path = os.getenv("COMMERCE_CATALOG_INDEX_PATH", "").strip()
    if not path:
        return None
    key = commerce_provider_key()
    model = os.getenv("POLZA_TASK_MODEL", "").strip() or os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL
    enabled, checker = load_egress_filter()
    return CommerceBridge(Path(path), CatalogModel(key, model, enabled=enabled, checker=checker))


def commerce_egress_configured() -> bool:
    enabled, checker = load_egress_filter()
    model = os.getenv("POLZA_TASK_MODEL", "").strip() or os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL
    endpoint = os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    return bool(enabled and checker and commerce_provider_key() and model == DEFAULT_MODEL and endpoint == ENDPOINT)
