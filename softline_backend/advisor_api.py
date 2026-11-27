import asyncio
import hashlib
import hmac
import logging
from time import monotonic, time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, StringConstraints, field_validator
from starlette.concurrency import run_in_threadpool

from .store import ChatNotFound, ChatStore, MessageConflict


logger = logging.getLogger(__name__)
OPERATOR_COOKIE = "softline_operator_session"
OPERATOR_TTL = 3600
TURN_WAIT = 12
REQUIREMENT_LABELS = {
    "Спорный факт": "Спорный факт",
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
    if card.get("price_amount") is not None and card.get("currency"):
        details.append(f"Цена по снимку — {card['price_amount']} {card['currency']}.")
    facts = {fact["field"]: fact["value"] for fact in card.get("verified_facts", [])}
    for key, label in (
        ("package_size", "Размер пакета"), ("license_quantity", "Число лицензий"), ("total_price", "Итого"),
        ("term", "Срок"), ("license_type", "Лицензия"), ("user_limit", "Лимит пользователей"),
    ):
        if key in facts:
            details.append(f"{label} — {facts[key]}.")
    product = {
        "id": card["offer_id"], "name": card["title"], "summary": card["match_summary"],
        "url": card["url"], "recommended": recommended,
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
        "messages": [{"role": message.role, "content": message.text} for message in row["messages"]],
        "reply": result.get("text", ""),
        "requirements": _requirements(result),
        "products": products,
        "sources": result.get("sources", []),
        "trace": [{"label": OUTCOMES[outcome], "detail": ""}] if outcome in OUTCOMES else [],
        "suggestedReplies": [],
    }


def _operator_request(row: dict) -> dict:
    result = row["result"] or {}
    context = (result.get("commerce_state") or {}).get("catalog_context") or {}
    scenario = {"need": "discovery", "named": "known"}.get(context.get("mode"), "question")
    handoff = result.get("handoff")
    issue = None
    if handoff:
        issue = {"label": ISSUES.get(handoff["reason"], "Ручная проверка"), "detail": handoff["summary"]}
    elif row["status"] == "failed":
        issue = {"label": "Ошибка обработки", "detail": "Перепроверьте последнее сообщение."}
    status = "review" if issue else (
        "resolved" if result.get("outcome") in {"answer", "recommend"} else "waiting"
    )
    identifier = str(row["chat_id"])
    view = {
        "id": identifier,
        "title": row["messages"][0].text[:160] if row["messages"] else "Обращение",
        "customer": "Клиент",
        "updatedAt": row["updated_at"].isoformat(),
        "scenario": scenario,
        "status": status,
        "response": _present(row, identifier),
    }
    if issue is not None:
        view["issue"] = issue
    return view


def advisor_router(store: ChatStore, manager_token: str | None) -> APIRouter:
    router = APIRouter(prefix="/api")

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
                return _present(snapshot, handle)
            if turn is not None and turn.status == "failed":
                raise HTTPException(503, detail={
                    "message": "Turn failed", "conversationId": handle, "turnId": str(turn_id),
                }, headers={"Cache-Control": "no-store"})
            await asyncio.sleep(0.12)
        raise HTTPException(504, detail={
            "message": "Turn is still processing", "conversationId": handle, "turnId": str(turn_id),
        }, headers={"Cache-Control": "no-store"})

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

    @router.get("/requests")
    def requests(request: Request, response: Response, limit: Annotated[int, Query(ge=1, le=50)] = 25):
        if not _has_operator_access(request, manager_token):
            raise HTTPException(401, "Operator authentication required")
        response.headers["Cache-Control"] = "no-store"
        return [_operator_request(row) for row in store.recent_consultations(limit)]

    return router
