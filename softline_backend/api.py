import logging
import os
from pathlib import Path
from secrets import compare_digest
from time import perf_counter
import re
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, StringConstraints
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .advisor_api import advisor_router
from .commerce_bridge import commerce_egress_configured
from .contracts import HandoffCase, HandoffView, MessageInput, MessageView, NewChat, QuoteCustomer, QuoteSnapshot, TurnAccepted, TurnView
from .quotes import render_quote
from .readiness import ProviderStatus, catalog_status, commerce_snapshot_at
from .store import ChatNotFound, ChatStore, MessageConflict, TurnNotFound, TurnRetryConflict
from .support_hours import SupportHours


bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
demo = Path(__file__).with_name("demo")


def chat_token(auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if auth is None:
        raise HTTPException(401, "Chat token required", headers={"WWW-Authenticate": "Bearer"})
    return auth.credentials


ChatToken = Annotated[str, Depends(chat_token)]


class SupportContact(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, min_length=3)]


def create_app(
    store: ChatStore,
    *,
    manager_token: str | None = None,
    catalog_index: Path | None = None,
    commerce_index: Path | None = None,
    provider_status: ProviderStatus = "deterministic",
    advisor_dist: Path | None = None,
    support_hours: SupportHours | None = None,
) -> FastAPI:
    app = FastAPI(title="Softline Chat API")
    hours = support_hours or SupportHours()
    app.include_router(advisor_router(store, manager_token, hours))
    app.mount("/demo", StaticFiles(directory=demo), name="demo")
    if advisor_dist is not None:
        app.mount("/assets", StaticFiles(directory=advisor_dist / "assets"), name="advisor-assets")

        @app.get("/advisor", include_in_schema=False)
        def store_advisor():
            return FileResponse(advisor_dist / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/", include_in_schema=False)
    def demo_chat():
        return FileResponse(demo / "chat.html")

    @app.get("/manager", include_in_schema=False)
    def demo_manager():
        return FileResponse(demo / "manager.html")

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready", responses={503: {"description": "Dependency unavailable"}})
    def ready(response: Response):
        database = "ready" if store.is_ready() else "unavailable"
        catalog = catalog_status(commerce_index or catalog_index, commerce=commerce_index is not None)
        queue = store.queue_health() if database == "ready" else "unavailable"
        healthy = database == "ready" and queue == "ready" and catalog in {"ready", "unconfigured"}
        response.headers["Cache-Control"] = "no-store"
        response.status_code = 200 if healthy else 503
        return {
            "status": "ready" if healthy else "unavailable",
            "database": database,
            "queue": queue,
            "catalog": catalog,
            "provider": provider_status,
            **({"catalogSnapshotAt": commerce_snapshot_at(commerce_index)} if commerce_index is not None and catalog == "ready" else {}),
        }

    def require_manager(token: ChatToken):
        if not manager_token or not compare_digest(token.encode(), manager_token.encode()):
            raise HTTPException(403, "Manager access required")

    @app.get("/manager/handoffs", response_model=list[HandoffView], dependencies=[Depends(require_manager)])
    def list_handoffs(limit: Annotated[int, Query(ge=1, le=100)] = 50):
        return store.list_handoffs(limit)

    @app.get(
        "/manager/handoffs/{handoff_id}",
        response_model=HandoffCase,
        dependencies=[Depends(require_manager)],
    )
    def get_handoff(handoff_id: UUID):
        case = store.get_handoff(handoff_id)
        if case is None:
            raise HTTPException(404, "Manager case not found")
        return case

    @app.post("/chats", response_model=NewChat, status_code=201)
    def create_chat(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return store.create_chat()

    @app.post("/chats/{chat_id}/messages", response_model=TurnAccepted, status_code=202)
    def submit_message(chat_id: UUID, body: MessageInput, token: ChatToken):
        started = perf_counter()
        try:
            turn_id = store.submit(chat_id, token, body.client_message_id, body.text)
        except ChatNotFound:
            raise HTTPException(404, "Chat not found") from None
        except MessageConflict:
            raise HTTPException(409, "Message ID was already used with different text") from None
        logger.info("turn_submission_accepted turn_id=%s duration_ms=%.1f", turn_id, (perf_counter() - started) * 1000)
        return TurnAccepted(turn_id=turn_id)

    @app.post("/chats/{chat_id}/manager-messages", response_model=TurnAccepted, status_code=202)
    def forward_message(chat_id: UUID, body: MessageInput, token: ChatToken):
        try:
            turn_id = store.submit(chat_id, token, body.client_message_id, body.text, to_manager=True)
        except ChatNotFound:
            raise HTTPException(404, "Chat not found") from None
        except MessageConflict:
            raise HTTPException(409, "Manager case is closed or message ID conflicts") from None
        return TurnAccepted(turn_id=turn_id)

    def support_view(chat_id: UUID, token: str, response: Response, email: str | None = None):
        response.headers["Cache-Control"] = "no-store"
        try:
            state = store.handoff_status(chat_id, token, email=email)
        except (ChatNotFound, TurnNotFound):
            raise HTTPException(404, "Manager case not found") from None
        support = hours.status()
        support.pop("email", None)
        if state["has_contact"] and hours.email:
            support["email"] = hours.email
        return {"status": state["status"], "hasContact": state["has_contact"], "support": support}

    @app.get("/chats/{chat_id}/support")
    def get_chat_support(chat_id: UUID, token: ChatToken, response: Response):
        return support_view(chat_id, token, response)

    @app.put("/chats/{chat_id}/support/contact")
    def save_chat_contact(chat_id: UUID, body: SupportContact, token: ChatToken, response: Response):
        if not re.fullmatch(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", body.email):
            raise HTTPException(422, "Invalid email address")
        return support_view(chat_id, token, response, email=body.email)

    @app.post("/chats/{chat_id}/turns/{turn_id}/retry", response_model=TurnAccepted, status_code=202)
    def retry_turn(chat_id: UUID, turn_id: UUID, token: ChatToken):
        started = perf_counter()
        try:
            store.retry(chat_id, token, turn_id)
        except ChatNotFound:
            raise HTTPException(404, "Chat not found") from None
        except TurnNotFound:
            raise HTTPException(404, "Turn not found") from None
        except TurnRetryConflict as exc:
            raise HTTPException(409, str(exc)) from None
        logger.info("turn_retry_accepted turn_id=%s duration_ms=%.1f", turn_id, (perf_counter() - started) * 1000)
        return TurnAccepted(turn_id=turn_id)

    @app.get("/chats/{chat_id}/turns/{turn_id}", response_model=TurnView)
    def get_turn(chat_id: UUID, turn_id: UUID, token: ChatToken):
        try:
            turn = store.get_turn(chat_id, token, turn_id)
        except ChatNotFound:
            raise HTTPException(404, "Chat not found") from None
        if turn is None:
            raise HTTPException(404, "Turn not found")
        if turn.outcome == "handoff":
            return turn.model_copy(update={"support": hours.status()})
        return turn

    @app.put("/chats/{chat_id}/turns/{turn_id}/quote/customer", response_model=QuoteSnapshot)
    def save_quote_customer(chat_id: UUID, turn_id: UUID, body: QuoteCustomer, token: ChatToken, response: Response):
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.save_quote_customer(chat_id, token, turn_id, body)
        except (ChatNotFound, TurnNotFound):
            raise HTTPException(404, "Quote not found") from None
        except MessageConflict:
            raise HTTPException(409, "This quote already has customer details") from None

    @app.get("/chats/{chat_id}/turns/{turn_id}/quote", response_class=HTMLResponse)
    def download_quote(chat_id: UUID, turn_id: UUID, token: ChatToken):
        try:
            turn = store.get_turn(chat_id, token, turn_id)
        except ChatNotFound:
            raise HTTPException(404, "Quote not found") from None
        if turn is None or turn.quote is None:
            raise HTTPException(404, "Quote not found")
        if turn.quote.customer is None:
            raise HTTPException(409, "Add customer details before downloading the quote")
        return HTMLResponse(render_quote(turn_id, turn.quote), headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="quote-{turn_id}.html"',
            "Content-Security-Policy": "default-src 'none'",
        })

    @app.post("/chats/{chat_id}/turns/{turn_id}/resolution", status_code=204)
    def confirm_resolution(chat_id: UUID, turn_id: UUID, token: ChatToken):
        try:
            store.confirm_customer_resolution(chat_id, token, turn_id)
        except (ChatNotFound, TurnNotFound):
            raise HTTPException(404, "Turn not found") from None
        except MessageConflict:
            raise HTTPException(409, "Only an answer or recommendation can be confirmed") from None
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/chats/{chat_id}/messages", response_model=list[MessageView], response_model_exclude_none=True)
    def list_messages(chat_id: UUID, token: ChatToken):
        try:
            return store.history(chat_id, token)
        except ChatNotFound:
            raise HTTPException(404, "Chat not found") from None

    return app


def app_from_env() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    index_path = os.getenv("CATALOG_INDEX_PATH")
    commerce_path = os.getenv("COMMERCE_CATALOG_INDEX_PATH", "").strip()
    provider_configured = bool(commerce_path) and commerce_egress_configured()
    advisor_path = os.getenv("STORE_ADVISOR_DIST_PATH", "").strip()
    return create_app(
        ChatStore(os.getenv("DATABASE_URL", "")),
        manager_token=os.getenv("MANAGER_TOKEN"),
        catalog_index=Path(index_path) if index_path else None,
        commerce_index=Path(commerce_path) if commerce_path else None,
        provider_status="configured" if provider_configured else "deterministic",
        advisor_dist=Path(advisor_path) if advisor_path else None,
        support_hours=SupportHours.from_env(),
    )
