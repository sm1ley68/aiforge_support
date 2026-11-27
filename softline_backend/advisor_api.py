import asyncio
import hashlib
import hmac
import logging
from time import monotonic, time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, HttpUrl, StringConstraints, field_validator

from aisupport_ml.commerce.retrieval import normalize
from aisupport_ml.privacy import mask_text
from starlette.concurrency import run_in_threadpool

from .knowledge import validated_url
from .store import ChatNotFound, ChatStore, MessageConflict, TurnNotFound
from .support_hours import SupportHours


logger = logging.getLogger(__name__)
OPERATOR_COOKIE = "softline_operator_session"
OPERATOR_TTL = 3600
TURN_WAIT = 12
REQUIREMENT_LABELS = {
    "Позиция": "Позиция", "quantity": "Количество", "Единица": "Единица", "ID предложения": "ID предложения",
    "Спорный факт": "Спорный факт",
    "Вопрос клиента": "Вопрос клиента",
    "Что проверить": "Что проверить",
    "product": "Продукт", "edition": "Редакция", "users": "Пользователи", "nodes": "Узлы",
    "term_months": "Срок, мес.", "goal": "Задача", "mail": "Почтовая система",
    "file_os": "ОС файлового сервера", "deployment": "Развёртывание", "budget_rub": "Бюджет, ₽",
    "budget_unlimited": "Без ограничения бюджета", "russian_only": "Российское происхождение",
    "backup_scope": "Объект резервного копирования", "perpetual_only": "Бессрочная лицензия",
}
ISSUES = {
    "customer_requested": "Попросили менеджера",
    "insufficient_evidence": "Недостаточно подтверждений",
    "commercial_terms": "Коммерческие условия",
    "delivery_confirmation": "Подтвердить поставку",
    "provider_unavailable": "Обработка требует проверки",
}
OUTCOMES = {
    "answer": "Ответ со сведениями",
    "clarify": "Нужно уточнение",
    "recommend": "Подбор завершён",
    "handoff": "Передано менеджеру",
}


class AdvisorMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ConsultationInput(BaseModel):
    conversation_id: str | None = Field(default=None, alias="conversationId", max_length=130)
    scenario: Literal["known", "discovery", "question"] | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    history: list[AdvisorMessage] = Field(default_factory=list, max_length=256)
    catalog_product_id: str | None = Field(default=None, alias="catalogProductId", max_length=240)
    client_message_id: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=112)
    ] = Field(default=None, alias="clientMessageId")

    @field_validator("message", "client_message_id")
    @classmethod
    def reject_null_bytes(cls, value: str | None) -> str | None:
        if value and "\x00" in value:
            raise ValueError("Null characters are not allowed")
        return value


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
ReplyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ManagerReplyInput(BaseModel):
    text: ReplyText
    confirmed_quote_turn_id: UUID | None = Field(default=None, alias="confirmedQuoteTurnId")
    client_message_id: UUID | None = Field(default=None, alias="clientMessageId")
    next_status: Literal["waiting", "resolved"] = Field(default="resolved", alias="nextStatus")
    seen_turn_id: UUID | None = Field(default=None, alias="seenTurnId")

    @field_validator("text")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Null characters are not allowed")
        return value


class ManagerStatusInput(BaseModel):
    status: Literal["review", "waiting", "resolved"]
    seen_turn_id: UUID = Field(alias="seenTurnId")


class ManagerArticleInput(BaseModel):
    question: ShortText
    aliases: list[ShortText] = Field(default_factory=list, max_length=8)
    answer: ReplyText
    sku: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9._/-]+$")] | None = None
    source_url: HttpUrl = Field(alias="sourceUrl")
    public_content_confirmed: Literal[True] = Field(alias="publicContentConfirmed")


def _matches(candidate: str, expected: str | None) -> bool:
    return bool(expected) and hmac.compare_digest(candidate.encode(), expected.encode())


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def _session_signature(secret: str, expires: str) -> str:
    return hmac.new(secret.encode(), f"store-advisor-operator:{expires}".encode(), hashlib.sha256).hexdigest()


def _has_operator_access(request: Request, secret: str | None) -> bool:
    if _matches(_bearer(request), secret):
        return True
    if not secret:
        return False
    expires, _, signature = request.cookies.get(OPERATOR_COOKIE, "").partition(".")
    if not (expires.isascii() and expires.isdigit() and len(expires) <= 12):
        return False
    return int(expires) >= int(time()) and _matches(signature, _session_signature(secret, expires))


def _chat_session(handle: str) -> tuple[UUID, str]:
    chat_id, _, token = handle.partition(".")
    try:
        identifier = UUID(chat_id)
    except ValueError:
        raise HTTPException(404, "Conversation not found") from None
    if not token:
        raise HTTPException(404, "Conversation not found")
    return identifier, token


def _format_value(value: str | bool) -> str:
    if isinstance(value, bool):
        return "да" if value else "нет"
    labels = {
        "local": "локально", "cloud": "облако",
        "files": "файлы", "disk_image": "образ диска", "unverified": "требует уточнения",
    }
    return labels.get(str(value), str(value))


def _requirements(result: dict) -> list[dict]:
    state = result.get("commerce_state") or {}
    context = state.get("catalog_context") or {}
    handoff = result.get("handoff") or {}
    values = {**context, **handoff.get("requirements", {})}
    return [
        {"label": label, "value": _format_value(values[key])}
        for key, label in REQUIREMENT_LABELS.items()
        if key in values and values[key] not in (None, "") and values[key] is not False
    ]


def _product(card: dict, recommended: bool) -> dict:
    details = []
    facts = {fact["field"]: fact["value"] for fact in card.get("verified_facts", [])}
    if card.get("price_amount") is not None and card.get("currency"):
        origin = "по карточке" if facts.get("price_origin") == "Карточка Softline" else "по снимку"
        details.append(f"Цена {origin} — {card['price_amount']} {card['currency']}.")
    if "vat" in facts:
        details.append(f"{facts['vat']}.")
    for key, label in (
        ("package_size", "Размер пакета"), ("license_quantity", "Число лицензий"), ("total_price", "Итого"),
        ("term", "Срок"), ("license_type", "Лицензия"), ("user_limit", "Лимит пользователей"),
    ):
        if key in facts:
            details.append(f"{label} — {facts[key]}.")
    product = {
        "id": card["offer_id"], "name": card["title"], "summary": card["match_summary"],
        "url": card["url"], "recommended": recommended, "snapshotAt": card["snapshot_at"],
    }
    if "edition" in facts:
        product["version"] = facts["edition"]
    if details:
        product["detail"] = " ".join(details)
    return product


def _present(row: dict, conversation_id: str) -> dict:
    result = row["result"] or {}
    outcome = result.get("outcome")
    products = [_product(card, outcome == "recommend") for card in result.get("products", [])]
    return {
        "conversationId": conversation_id,
        "messages": [
            {"role": message.role, "content": message.text, **({"author": message.author} if message.author else {})}
            for message in row["messages"]
        ],
        "reply": result.get("text", ""),
        "requirements": _requirements(result),
        "products": products,
        "sources": result.get("sources", []),
        "trace": [{"label": OUTCOMES[outcome], "detail": ""}] if outcome in OUTCOMES else [],
        "suggestedReplies": [],
        **({"quote": result["quote"]} if result.get("quote") else {}),
    }


def _operator_request(row: dict) -> dict:
    result = row["handoff_result"] or row["result"] or {}
    context = (result.get("commerce_state") or {}).get("catalog_context") or {}
    scenario = {"need": "discovery", "named": "known"}.get(context.get("mode"), "question")
    handoff = result.get("handoff")
    issue = None
    if handoff:
        issue = {"label": ISSUES.get(handoff["reason"], "Ручная проверка"), "detail": handoff["summary"]}
    elif row["status"] == "failed":
        issue = {"label": "Ошибка обработки", "detail": "Перепроверьте последнее сообщение."}
    if row["workflow_status"] is not None:
        status = row["workflow_status"]
    elif row["manager_replied_at"] is not None:
        status = "resolved"
    else:
        status = "review" if issue else "resolved" if result.get("quote") or row["customer_resolved_at"] else "waiting"
    identifier = str(row["chat_id"])
    view = {
        "id": identifier,
        "title": row["messages"][0].text[:160] if row["messages"] else "Обращение",
        "customer": "Клиент",
        "latestTurnId": str(row["turn_id"]),
        "updatedAt": max(filter(None, (row["updated_at"], row["workflow_updated_at"], row["manager_replied_at"]))).isoformat(),
        "scenario": scenario,
        "status": status,
        "response": _present({**row, "result": result}, identifier),
    }
    if handoff:
        view["handoffId"] = str(row["handoff_id"])
        view["needsReply"] = bool(row["workflow_status"] == "review" and row["needs_reply"])
        view["articlePublished"] = row["article_published_at"] is not None
        if row["contact_email"]:
            view["contactEmail"] = row["contact_email"]
        if row["manager_replied_at"] is not None:
            view["managerRepliedAt"] = row["manager_replied_at"].isoformat()
        shown_ids = {product["offer_id"] for product in result.get("products", [])}
        issue["checks"] = [
            f"Позиция {candidate_id}" for candidate_id in handoff["candidate_ids"] if candidate_id not in shown_ids
        ]
    if issue is not None:
        view["issue"] = issue
    return view


def advisor_router(store: ChatStore, manager_token: str | None, hours: SupportHours) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/support/availability")
    def availability(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return hours.status()

    def consultation_view(snapshot, handle):
        view = _present(snapshot, handle)
        if (snapshot["result"] or {}).get("outcome") == "handoff":
            view["support"] = hours.status()
        return view

    @router.post("/consultation")
    async def consult(body: ConsultationInput, response: Response):
        response.headers["Cache-Control"] = "no-store"
        handle = body.conversation_id
        if handle is None:
            chat = await run_in_threadpool(store.create_chat)
            chat_id, token = chat.chat_id, chat.chat_token
            handle = f"{chat_id}.{token}"
        else:
            chat_id, token = _chat_session(handle)

        # The UI's history is a retry hint only. The worker always reads the saved history.
        client_id = body.client_message_id
        if client_id is None:
            retry_key = f"{len(body.history)}\n{body.message}"
            client_id = hashlib.sha256(retry_key.encode()).hexdigest()
        try:
            turn_id = await run_in_threadpool(store.submit, chat_id, token, f"advisor:{client_id}", body.message)
        except ChatNotFound:
            raise HTTPException(404, "Conversation not found") from None
        except MessageConflict:
            raise HTTPException(409, "Message ID was already used") from None
        logger.info("advisor_turn_accepted turn_id=%s", turn_id)

        deadline = monotonic() + TURN_WAIT
        while monotonic() < deadline:
            turn = await run_in_threadpool(store.get_turn, chat_id, token, turn_id)
            if turn is not None and turn.status == "succeeded":
                snapshot = await run_in_threadpool(store.consultation_snapshot, chat_id, token, turn_id)
                return consultation_view(snapshot, handle)
            if turn is not None and turn.status == "failed":
                raise HTTPException(503, detail={
                    "message": "Turn failed", "conversationId": handle, "turnId": str(turn_id),
                }, headers={"Cache-Control": "no-store"})
            await asyncio.sleep(0.12)
        raise HTTPException(504, detail={
            "message": "Turn is still processing", "conversationId": handle, "turnId": str(turn_id),
        }, headers={"Cache-Control": "no-store"})

    @router.get("/consultation/{chat_id}/turns/{turn_id}")
    def consultation_result(chat_id: UUID, turn_id: UUID, request: Request, response: Response):
        headers = {"Cache-Control": "no-store"}
        token = _bearer(request)
        if not token:
            raise HTTPException(401, "Chat token required", headers=headers)
        try:
            snapshot = store.consultation_snapshot(chat_id, token, turn_id)
        except (ChatNotFound, TurnNotFound):
            raise HTTPException(404, "Turn not found", headers=headers) from None
        if snapshot["status"] != "succeeded":
            raise HTTPException(409, "Turn is not complete", headers=headers)
        response.headers.update(headers)
        view = consultation_view(snapshot, str(chat_id))
        if "quote" in view:
            quote_url = f"/chats/{chat_id}/turns/{turn_id}/quote"
            view["quote"]["downloadUrl"] = quote_url
            view["quote"]["customerUrl"] = f"{quote_url}/customer"
        return view

    @router.post("/operator/session")
    def sign_in(request: Request, response: Response):
        if not manager_token or not _matches(_bearer(request), manager_token):
            raise HTTPException(401, "Operator authentication required")
        expires = str(int(time()) + OPERATOR_TTL)
        response.set_cookie(
            OPERATOR_COOKIE, f"{expires}.{_session_signature(manager_token, expires)}", max_age=OPERATOR_TTL,
            path="/api/requests", httponly=True, samesite="strict", secure=request.url.scheme == "https",
        )
        response.headers["Cache-Control"] = "no-store"
        return {"authenticated": True}

    @router.delete("/operator/session")
    def sign_out(response: Response):
        response.delete_cookie(OPERATOR_COOKIE, path="/api/requests", httponly=True, samesite="strict")
        response.headers["Cache-Control"] = "no-store"
        return {"authenticated": False}

    def require_operator(request: Request, response: Response):
        if not _has_operator_access(request, manager_token):
            raise HTTPException(401, "Operator authentication required")
        response.headers["Cache-Control"] = "no-store"

    @router.post("/requests/{handoff_id}/reply")
    def send_manager_reply(handoff_id: UUID, body: ManagerReplyInput, request: Request, response: Response):
        require_operator(request, response)
        try:
            return store.reply_to_handoff(
                handoff_id, body.text, body.confirmed_quote_turn_id,
                str(body.client_message_id) if body.client_message_id else None, body.next_status, body.seen_turn_id,
            )
        except TurnNotFound:
            raise HTTPException(404, "Manager case not found") from None
        except MessageConflict:
            raise HTTPException(409, "Reply already saved or quote cannot be confirmed") from None

    @router.put("/requests/{handoff_id}/status", status_code=204)
    def set_manager_status(handoff_id: UUID, body: ManagerStatusInput, request: Request, response: Response):
        require_operator(request, response)
        try:
            store.change_handoff_status(handoff_id, body.status, body.seen_turn_id)
        except TurnNotFound:
            raise HTTPException(404, "Manager case not found") from None
        except MessageConflict:
            raise HTTPException(409, "The conversation has changed") from None

    @router.post("/requests/{handoff_id}/knowledge")
    def publish_manager_knowledge(handoff_id: UUID, body: ManagerArticleInput, request: Request, response: Response):
        require_operator(request, response)
        source_url = validated_url(str(body.source_url))
        if not source_url or body.source_url.scheme != "https" or body.source_url.query or body.source_url.fragment:
            raise HTTPException(422, "Use a public HTTPS source without query parameters or fragments")
        if source_url.host not in {"docs.softline.com", "store.softline.ru"} or source_url.port != 443:
            raise HTTPException(422, "Use an approved Softline source")
        text_fields = (body.question, body.answer, *body.aliases)
        search_keys = sorted({normalize(value) for value in [body.question, *body.aliases]} - {""})
        if not search_keys or any("\x00" in value for value in text_fields):
            raise HTTPException(422, "Invalid article content")
        try:
            has_sensitive = any(mask_text(value).categories for value in text_fields)
        except Exception:
            raise HTTPException(503, "Local publication check unavailable") from None
        if has_sensitive:
            raise HTTPException(422, "Article contains personal or restricted data")
        article = {"question": body.question, "aliases": body.aliases, "answer": body.answer,
                   "sku": body.sku, "sourceUrl": str(source_url)}
        try:
            return store.publish_manager_knowledge(handoff_id, article, search_keys)
        except TurnNotFound:
            raise HTTPException(404, "Save a manager reply first") from None
        except MessageConflict:
            raise HTTPException(409, "An article for this case is already published") from None

    @router.get("/requests/metrics")
    def metrics(request: Request, response: Response):
        require_operator(request, response)
        return store.operator_metrics()

    @router.get("/requests")
    def requests(request: Request, response: Response, limit: Annotated[int, Query(ge=1, le=50)] = 25):
        if not _has_operator_access(request, manager_token):
            raise HTTPException(401, "Operator authentication required")
        response.headers["Cache-Control"] = "no-store"
        return [_operator_request(row) for row in store.recent_consultations(limit)]

    return router
