import os
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .contracts import HandoffCase, HandoffView, MessageInput, MessageView, NewChat, TurnAccepted, TurnView
from .store import ChatNotFound, ChatStore, MessageConflict


bearer = HTTPBearer(auto_error=False)


def chat_token(auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if auth is None:
        raise HTTPException(401, "Chat token required", headers={"WWW-Authenticate": "Bearer"})
    return auth.credentials


ChatToken = Annotated[str, Depends(chat_token)]


def create_app(store: ChatStore, *, manager_token: str | None = None) -> FastAPI:
    app = FastAPI(title="Softline Chat API")

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
        try:
            turn_id = store.submit(chat_id, token, body.client_message_id, body.text)
        except ChatNotFound:
            raise HTTPException(404, "Chat not found") from None
        except MessageConflict:
            raise HTTPException(409, "Message ID was already used with different text") from None
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
    return create_app(ChatStore(os.environ["DATABASE_URL"]), manager_token=os.getenv("MANAGER_TOKEN"))
