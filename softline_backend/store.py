from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from secrets import token_urlsafe
from uuid import UUID, uuid4

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import HandoffCase, HandoffView, MessageView, NewChat, TurnResult, TurnView


HANDOFF_ROWS = """
    SELECT turn_id AS handoff_id, turn_id, chat_id, result -> 'handoff' AS details
    FROM chat_turns
    WHERE status = 'succeeded' AND result ->> 'outcome' = 'handoff'
"""


class ChatNotFound(Exception):
    pass


class MessageConflict(Exception):
    pass


@dataclass(frozen=True)
class ClaimedTurn:
    turn_id: UUID
    chat_id: UUID
    sequence: int
    message_text: str
    attempts: int


class ChatStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _connect(self):
        return connect(self.database_url, row_factory=dict_row)

    def initialize(self):
        with self._connect() as db:
            db.execute(files(__package__).joinpath("schema.sql").read_text(encoding="utf-8"))

    def create_chat(self) -> NewChat:
        chat = NewChat(chat_id=uuid4(), chat_token=token_urlsafe(32))
        with self._connect() as db:
            db.execute(
                "INSERT INTO chats (chat_id, token_hash) VALUES (%s, %s)",
                (chat.chat_id, sha256(chat.chat_token.encode()).digest()),
            )
        return chat

    @staticmethod
    def _check_access(db, chat_id: UUID, token: str, *, lock: bool = False):
        query = "SELECT 1 FROM chats WHERE chat_id = %s AND token_hash = %s"
        if lock:
            query += " FOR UPDATE"
        if db.execute(query, (chat_id, sha256(token.encode()).digest())).fetchone() is None:
            raise ChatNotFound

    def submit(self, chat_id: UUID, token: str, client_message_id: str, text: str) -> UUID:
        with self._connect() as db:
            self._check_access(db, chat_id, token, lock=True)
            existing = db.execute(
                """SELECT turn_id, message_text FROM chat_turns
                   WHERE chat_id = %s AND client_message_id = %s""",
                (chat_id, client_message_id),
            ).fetchone()
            if existing:
                if existing["message_text"] != text:
                    raise MessageConflict
                return existing["turn_id"]

            turn_id = uuid4()
            db.execute(
                """INSERT INTO chat_turns (turn_id, chat_id, client_message_id, message_text)
                   VALUES (%s, %s, %s, %s)""",
                (turn_id, chat_id, client_message_id, text),
            )
            return turn_id

    def get_turn(self, chat_id: UUID, token: str, turn_id: UUID) -> TurnView | None:
        with self._connect() as db:
            self._check_access(db, chat_id, token)
            row = db.execute(
                """SELECT turn_id, status, result, error FROM chat_turns
                   WHERE chat_id = %s AND turn_id = %s""",
                (chat_id, turn_id),
            ).fetchone()
        if row is None:
            return None
        result = row.pop("result") or {}
        result.pop("handoff", None)
        return TurnView(**row, **result)

    def list_handoffs(self, limit: int) -> list[HandoffView]:
        with self._connect() as db:
            rows = db.execute(HANDOFF_ROWS + " ORDER BY sequence DESC LIMIT %s", (limit,))
            return [HandoffView(**row.pop("details"), **row) for row in rows]

    def get_handoff(self, handoff_id: UUID) -> HandoffCase | None:
        with self._connect() as db:
            row = db.execute(HANDOFF_ROWS + " AND turn_id = %s", (handoff_id,)).fetchone()
            if row is None:
                return None
            return HandoffCase(**row.pop("details"), **row, messages=self._history(db, row["chat_id"]))

    def history(self, chat_id: UUID, token: str) -> list[MessageView]:
        with self._connect() as db:
            self._check_access(db, chat_id, token)
            return self._history(db, chat_id)

    def previous_messages(self, turn: ClaimedTurn) -> list[MessageView]:
        with self._connect() as db:
            return self._history(db, turn.chat_id, before=turn.sequence)

    @staticmethod
    def _history(db, chat_id: UUID, before: int | None = None) -> list[MessageView]:
        query = "SELECT turn_id, message_text, result FROM chat_turns WHERE chat_id = %s"
        params = [chat_id]
        if before is not None:
            query += " AND sequence < %s"
            params.append(before)

        messages = []
        for row in db.execute(query + " ORDER BY sequence", params):
            turn_id = row["turn_id"]
            messages.append(MessageView(turn_id=turn_id, role="user", text=row["message_text"]))
            if row["result"]:
                messages.append(MessageView(turn_id=turn_id, role="assistant", text=row["result"]["text"]))
        return messages

    def claim(self, lease_seconds: int = 60) -> ClaimedTurn | None:
        with self._connect() as db:
            # The head turn remains a blocker even when another worker holds its row lock.
            candidate = db.execute(
                """SELECT candidate.turn_id, candidate.attempts
                   FROM chat_turns AS candidate
                   WHERE (candidate.status = 'queued'
                          OR (candidate.status = 'processing' AND candidate.lease_until <= clock_timestamp()))
                     AND NOT EXISTS (
                         SELECT 1 FROM chat_turns AS earlier
                         WHERE earlier.chat_id = candidate.chat_id
                           AND earlier.sequence < candidate.sequence
                           AND earlier.status IN ('queued', 'processing')
                     )
                   ORDER BY candidate.sequence
                   LIMIT 1 FOR UPDATE OF candidate SKIP LOCKED"""
            ).fetchone()
            if candidate is None:
                return None
            if candidate["attempts"] >= 3:
                db.execute(
                    """UPDATE chat_turns
                       SET status = 'failed', lease_until = NULL, error = 'worker_timeout'
                       WHERE turn_id = %s""",
                    (candidate["turn_id"],),
                )
                return None

            row = db.execute(
                """UPDATE chat_turns
                   SET status = 'processing', attempts = attempts + 1,
                       lease_until = clock_timestamp() + %s * interval '1 second'
                   WHERE turn_id = %s
                   RETURNING turn_id, chat_id, sequence, message_text, attempts""",
                (lease_seconds, candidate["turn_id"]),
            ).fetchone()
            return ClaimedTurn(**row)

    def finish(
        self, turn: ClaimedTurn, *, result: TurnResult | None = None, error: str | None = None
    ) -> bool:
        if (result is None) == (error is None):
            raise ValueError("Provide exactly one of result or error")
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE chat_turns
                   SET status = %s, result = %s, error = %s, lease_until = NULL
                   WHERE turn_id = %s AND status = 'processing' AND attempts = %s
                     AND lease_until > clock_timestamp()""",
                (
                    "succeeded" if result is not None else "failed",
                    Jsonb(result.model_dump(mode="json")) if result is not None else None,
                    error,
                    turn.turn_id,
                    turn.attempts,
                ),
            )
            return cursor.rowcount == 1
