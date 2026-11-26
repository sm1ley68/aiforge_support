import logging
import os
from pathlib import Path
from secrets import compare_digest
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .contracts import HandoffCase, HandoffView, MessageInput, MessageView, NewChat, TurnAccepted, TurnView
from .readiness import ProviderStatus, catalog_status
from .store import ChatNotFound, ChatStore, MessageConflict, TurnNotFound, TurnRetryConflict


bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
demo = Path(__file__).with_name("demo")


def chat_token(auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if auth is None:
        raise HTTPException(401, "Chat token required", headers={"WWW-Authenticate": "Bearer"})
    return auth.credentials


ChatToken = Annotated[str, Depends(chat_token)]


def create_app(
    store: ChatStore,
    *,
    manager_token: str | None = None,
    catalog_index: Path | None = None,
    provider_status: ProviderStatus = "deterministic",
) -> FastAPI:
    app = FastAPI(title="Softline Chat API")
    app.mount("/demo", StaticFiles(directory=demo), name="demo")

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
        catalog = catalog_status(catalog_index)
        healthy = database == "ready" and catalog in {"ready", "unconfigured"}
        response.headers["Cache-Control"] = "no-store"
        response.status_code = 200 if healthy else 503
        return {
            "status": "ready" if healthy else "unavailable",
            "database": database,
            "catalog": catalog,
            "provider": provider_status,
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
        return turn

    @app.get("/chats/{chat_id}/messages", response_model=list[MessageView])
    def list_messages(chat_id: UUID, token: ChatToken):
        try:
            return store.history(chat_id, token)
        except ChatNotFound:
            raise HTTPException(404, "Chat not found") from None

    return app


def app_from_env() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    index_path = os.getenv("CATALOG_INDEX_PATH")
    return create_app(
        ChatStore(os.getenv("DATABASE_URL", "")),
        manager_token=os.getenv("MANAGER_TOKEN"),
        catalog_index=Path(index_path) if index_path else None,
        provider_status="configured" if os.getenv("POLZA_API_KEY", "").strip() else "deterministic",
    )
