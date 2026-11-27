import logging
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from secrets import token_urlsafe
from uuid import UUID, uuid4

from psycopg import Error, IsolationLevel, OperationalError, connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import (
    CatalogReference,
    HandoffCase,
    HandoffView,
    MessageView,
    NewChat,
    TurnResult,
    TurnView,
)


logger = logging.getLogger(__name__)

CLAIMABLE_TURNS = """
    (candidate.status = 'queued'
     OR (candidate.status = 'processing' AND candidate.lease_until <= clock_timestamp()))
    AND NOT EXISTS (
        SELECT 1 FROM chat_turns AS earlier
        WHERE earlier.chat_id = candidate.chat_id
          AND earlier.sequence < candidate.sequence
          AND earlier.status IN ('queued', 'processing')
    )
"""


HANDOFF_ROWS = """
    SELECT turn_id AS handoff_id, turn_id, chat_id, result -> 'handoff' AS details
    FROM chat_turns
    WHERE status = 'succeeded' AND result ->> 'outcome' = 'handoff'
"""


class ChatNotFound(Exception):
    pass


class MessageConflict(Exception):
    pass


class TurnNotFound(Exception):
    pass


class TurnRetryConflict(Exception):
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

    def _connect(self, **kwargs):
        if not self.database_url:
            raise OperationalError("DATABASE_URL is missing")
        return connect(self.database_url, row_factory=dict_row, **kwargs)

    def is_ready(self) -> bool:
        try:
            with self._connect(connect_timeout=2) as db:
                db.execute("SET LOCAL statement_timeout = '2s'")
                db.execute(
                    "SELECT chats.token_hash, chat_turns.retry_attempt_base, chat_turns.updated_at "
                    "FROM chats JOIN chat_turns USING (chat_id) LIMIT 0"
                )
                db.execute("SELECT article_id, source_id, source_version, status FROM commerce_knowledge LIMIT 0")
        except Error:
            return False
        return True

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
            db.isolation_level = IsolationLevel.READ_COMMITTED
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

    def retry(self, chat_id: UUID, token: str, turn_id: UUID) -> None:
        with self._connect() as db:
            db.isolation_level = IsolationLevel.READ_COMMITTED
            self._check_access(db, chat_id, token, lock=True)
            row = db.execute(
                "SELECT status, sequence FROM chat_turns WHERE chat_id = %s AND turn_id = %s",
                (chat_id, turn_id),
            ).fetchone()
            if row is None:
                raise TurnNotFound
            if row["status"] != "failed":
                raise TurnRetryConflict("Only failed turns can be retried")

            later = db.execute(
                """SELECT 1 FROM chat_turns
                   WHERE chat_id = %s AND sequence > %s AND attempts > 0
                   LIMIT 1""",
                (chat_id, row["sequence"]),
            ).fetchone()
            if later is not None:
                raise TurnRetryConflict("A later turn has already started")

            db.execute(
                """UPDATE chat_turns
                   SET status = 'queued', error = NULL, retry_attempt_base = attempts,
                       updated_at = clock_timestamp()
                   WHERE turn_id = %s""",
                (turn_id,),
            )

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
        result.pop("catalog_selection", None)
        result.pop("commerce_state", None)
        return TurnView(**row, **result)

    def consultation_snapshot(self, chat_id: UUID, token: str, turn_id: UUID) -> dict:
        with self._connect() as db:
            self._check_access(db, chat_id, token)
            row = db.execute(
                '''SELECT chat_id, sequence, status, result FROM chat_turns
                   WHERE chat_id = %s AND turn_id = %s''',
                (chat_id, turn_id),
            ).fetchone()
            if row is None:
                raise TurnNotFound
            row["messages"] = self._history(db, chat_id, before=row["sequence"] + 1)
            return row

    def recent_consultations(self, limit: int) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                '''SELECT * FROM (
                       SELECT DISTINCT ON (chat_id) chat_id, sequence, status, result, updated_at
                       FROM chat_turns ORDER BY chat_id, sequence DESC
                   ) AS latest ORDER BY sequence DESC LIMIT %s''',
                (limit,),
            ).fetchall()
            for row in rows:
                row["messages"] = self._history(db, row["chat_id"], before=row["sequence"] + 1)
            return rows

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

    def previous_commerce_state(self, turn: ClaimedTurn) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT result -> 'commerce_state' AS state FROM chat_turns
                   WHERE chat_id = %s AND sequence < %s AND status = 'succeeded'
                     AND result ->> 'commerce_state' IS NOT NULL
                   ORDER BY sequence DESC LIMIT 1""",
                (turn.chat_id, turn.sequence),
            ).fetchone()
        return row["state"] if row is not None else None

    def published_knowledge(self) -> list[tuple[str, str, str]]:
        with self._connect() as db:
            return [(row["article_id"], row["source_id"], row["source_version"]) for row in db.execute(
                "SELECT article_id, source_id, source_version FROM commerce_knowledge WHERE status = 'published'"
            )]

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
            if result := row["result"]:
                references = []
                if before is not None:
                    selection = result.get("catalog_selection")
                    candidates = [selection] if selection else result.get("products", [])
                    references = [CatalogReference.model_validate(candidate) for candidate in candidates]
                messages.append(MessageView(
                    turn_id=turn_id, role="assistant", text=result["text"], catalog_references=references
                ))
        return messages

    def claim(self, lease_seconds: int = 60) -> ClaimedTurn | None:
        with self._connect() as db:
            db.isolation_level = IsolationLevel.READ_COMMITTED
            # Retry and claim both lock the chat before changing queue state.
            candidate = db.execute(
                f"""SELECT candidate.turn_id
                    FROM chat_turns AS candidate JOIN chats AS chat USING (chat_id)
                    WHERE {CLAIMABLE_TURNS}
                    ORDER BY candidate.sequence
                    LIMIT 1 FOR UPDATE OF chat, candidate SKIP LOCKED"""
            ).fetchone()
            if candidate is None:
                return None

            # A retry can commit after the candidate statement took its snapshot
            # but before it locked the chat. Check again with a fresh snapshot.
            candidate = db.execute(
                f"""SELECT candidate.turn_id, candidate.attempts, candidate.retry_attempt_base
                    FROM chat_turns AS candidate
                    WHERE candidate.turn_id = %s AND {CLAIMABLE_TURNS}""",
                (candidate["turn_id"],),
            ).fetchone()
            if candidate is None:
                return None

            if candidate["attempts"] - candidate["retry_attempt_base"] < 3:
                row = db.execute(
                    """UPDATE chat_turns
                       SET status = 'processing', attempts = attempts + 1, updated_at = clock_timestamp(),
                           lease_until = clock_timestamp() + %s * interval '1 second'
                       WHERE turn_id = %s
                       RETURNING turn_id, chat_id, sequence, message_text, attempts""",
                    (lease_seconds, candidate["turn_id"]),
                ).fetchone()
                return ClaimedTurn(**row)

            db.execute(
                """UPDATE chat_turns
                   SET status = 'failed', lease_until = NULL, error = 'worker_timeout',
                       updated_at = clock_timestamp()
                   WHERE turn_id = %s""",
                (candidate["turn_id"],),
            )
        logger.warning(
            "turn_attempts_exhausted turn_id=%s attempt=%s",
            candidate["turn_id"], candidate["attempts"],
        )
        return None

    def finish(
        self, turn: ClaimedTurn, *, result: TurnResult | None = None, error: str | None = None
    ) -> bool:
        if (result is None) == (error is None):
            raise ValueError("Provide exactly one of result or error")
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE chat_turns
                   SET status = %s, result = %s, error = %s, lease_until = NULL, updated_at = clock_timestamp()
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
            if cursor.rowcount != 1:
                return False
            if result is not None and (update := result.knowledge_update) is not None:
                db.execute(
                    """INSERT INTO commerce_knowledge (article_id, source_id, source_version, status)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (article_id) DO UPDATE SET status = 'published'
                       WHERE commerce_knowledge.status = 'draft' AND excluded.status = 'published'
                         AND commerce_knowledge.source_id = excluded.source_id
                         AND commerce_knowledge.source_version = excluded.source_version""",
                    (update.id, update.source_id, update.source_version,
                     "draft" if update.status == "draft" else "published"),
                )
            return True
