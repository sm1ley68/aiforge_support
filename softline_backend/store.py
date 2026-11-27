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


HANDOFF_PREDICATE = "status = 'succeeded' AND result ->> 'outcome' = 'handoff'"


HANDOFF_ROWS = f"""
    SELECT turn_id AS handoff_id, turn_id, chat_id, result -> 'handoff' AS details
    FROM chat_turns
    WHERE {HANDOFF_PREDICATE}
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
                db.execute("SELECT submitted_at FROM chat_turns LIMIT 0")
                db.execute("SELECT confirmed_quote_id FROM manager_replies LIMIT 0")
                db.execute("SELECT turn_id FROM customer_resolutions LIMIT 0")
                db.execute("SELECT handoff_id FROM manager_knowledge LIMIT 0")
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
                """INSERT INTO chat_turns (turn_id, chat_id, client_message_id, message_text, submitted_at)
                   VALUES (%s, %s, %s, %s, clock_timestamp())""",
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
                f"""WITH recent AS (
                       SELECT * FROM (
                           SELECT DISTINCT ON (chat_id) chat_id, turn_id, sequence, status, result, updated_at
                           FROM chat_turns ORDER BY chat_id, sequence DESC
                       ) AS latest ORDER BY sequence DESC LIMIT %s
                   )
                   SELECT recent.*, saved.turn_id AS handoff_id, saved.result AS handoff_result,
                          saved.sequence AS handoff_sequence, reply.created_at AS manager_replied_at,
                          resolution.created_at AS customer_resolved_at
                   FROM recent
                   LEFT JOIN LATERAL (
                       SELECT turn_id, sequence, result FROM chat_turns
                       WHERE chat_id = recent.chat_id AND sequence <= recent.sequence AND {HANDOFF_PREDICATE}
                       ORDER BY sequence DESC LIMIT 1
                   ) AS saved ON true
                   LEFT JOIN manager_replies AS reply ON reply.handoff_id = saved.turn_id
                   LEFT JOIN customer_resolutions AS resolution ON resolution.turn_id = recent.turn_id
                   ORDER BY recent.sequence DESC""",
                (limit,),
            ).fetchall()
            for row in rows:
                row["messages"] = self._history(db, row["chat_id"], before=row["sequence"] + 1)
                if handoff := row["handoff_result"]:
                    candidate_ids = handoff["handoff"]["candidate_ids"]
                    if candidate_ids:
                        cards = db.execute(
                            """SELECT DISTINCT ON (card ->> 'offer_id') card
                               FROM chat_turns
                               CROSS JOIN LATERAL jsonb_array_elements(result -> 'products') AS card
                               WHERE chat_id = %s AND sequence <= %s AND card ->> 'offer_id' = ANY(%s)
                               ORDER BY card ->> 'offer_id', sequence DESC""",
                            (row["chat_id"], row["handoff_sequence"], candidate_ids),
                        ).fetchall()
                        cards_by_id = {item["card"]["offer_id"]: item["card"] for item in cards}
                        handoff["products"] = [cards_by_id[key] for key in candidate_ids if key in cards_by_id]
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

    def reply_to_handoff(self, handoff_id: UUID, text: str, quote_id: UUID | None) -> dict:
        with self._connect() as db:
            case = db.execute(HANDOFF_ROWS + " AND turn_id = %s", (handoff_id,)).fetchone()
            if case is None:
                raise TurnNotFound
            db.execute("SELECT chat_id FROM chats WHERE chat_id = %s FOR UPDATE", (case["chat_id"],))
            existing = db.execute(
                """SELECT handoff_id, text, created_at, confirmed_quote_id
                   FROM manager_replies WHERE handoff_id = %s""",
                (handoff_id,),
            ).fetchone()
            if existing is not None:
                if existing["text"] != text or existing["confirmed_quote_id"] != quote_id:
                    raise MessageConflict
                return existing
            if quote_id is not None:
                quote = db.execute(
                    """SELECT result -> 'quote' ->> 'offer_id' AS offer_id FROM chat_turns AS quote
                       WHERE quote.chat_id = %s AND quote.turn_id = %s
                         AND quote.sequence < (SELECT sequence FROM chat_turns WHERE turn_id = %s)
                         AND NOT EXISTS (SELECT 1 FROM manager_replies WHERE confirmed_quote_id = quote.turn_id)""",
                    (case["chat_id"], quote_id, handoff_id),
                ).fetchone()
                candidates = case["details"].get("candidate_ids", [])
                if not quote or not quote["offer_id"] or (candidates and quote["offer_id"] not in candidates):
                    raise MessageConflict
            return db.execute(
                """INSERT INTO manager_replies (handoff_id, after_sequence, text, confirmed_quote_id)
                   SELECT %s, max(sequence), %s, %s FROM chat_turns WHERE chat_id = %s
                   RETURNING handoff_id, text, created_at, confirmed_quote_id""",
                (handoff_id, text, quote_id, case["chat_id"]),
            ).fetchone()

    def publish_manager_knowledge(self, handoff_id: UUID, article: dict, search_keys: list[str]) -> dict:
        with self._connect() as db:
            if db.execute(
                "SELECT handoff_id FROM manager_replies WHERE handoff_id = %s", (handoff_id,),
            ).fetchone() is None:
                raise TurnNotFound
            row = db.execute(
                """INSERT INTO manager_knowledge (handoff_id, article, search_keys) VALUES (%s, %s, %s)
                   ON CONFLICT (handoff_id) DO NOTHING RETURNING article, created_at""",
                (handoff_id, Jsonb(article), search_keys),
            ).fetchone()
            if row is None:
                row = db.execute(
                    "SELECT article, created_at FROM manager_knowledge WHERE handoff_id = %s", (handoff_id,),
                ).fetchone()
                if row["article"] != article:
                    raise MessageConflict
            return {"article_id": handoff_id, **row}

    def match_manager_knowledge(self, key: str, sku: str | None) -> dict | None:
        if not key:
            return None
        with self._connect() as db:
            rows = db.execute(
                """SELECT article FROM manager_knowledge WHERE search_keys @> ARRAY[%s]::text[]
                   AND (article ->> 'sku' IS NULL OR lower(article ->> 'sku') = lower(%s))
                   ORDER BY (article ->> 'sku' IS NOT NULL) DESC LIMIT 2""",
                (key, sku),
            ).fetchall()
            if rows and (len(rows) == 1 or bool(rows[0]["article"].get("sku")) != bool(rows[1]["article"].get("sku"))):
                return rows[0]["article"]
            return None

    def confirm_customer_resolution(self, chat_id: UUID, token: str, turn_id: UUID) -> None:
        with self._connect() as db:
            self._check_access(db, chat_id, token)
            turn = db.execute(
                """SELECT result ->> 'outcome' AS outcome FROM chat_turns
                   WHERE chat_id = %s AND turn_id = %s AND status = 'succeeded'""",
                (chat_id, turn_id),
            ).fetchone()
            if turn is None:
                raise TurnNotFound
            if turn["outcome"] not in {"answer", "recommend"}:
                raise MessageConflict
            db.execute("INSERT INTO customer_resolutions (turn_id) VALUES (%s) ON CONFLICT DO NOTHING", (turn_id,))

    def operator_metrics(self) -> dict:
        with self._connect() as db:
            return db.execute(
                """WITH turns AS (
                       SELECT turn_id, chat_id, updated_at, result ->> 'outcome' AS outcome,
                              result ->> 'quote' IS NOT NULL AS has_quote
                       FROM chat_turns WHERE status = 'succeeded'
                   ), first_requests AS (
                       SELECT DISTINCT ON (chat_id) chat_id, submitted_at FROM chat_turns
                       ORDER BY chat_id, sequence
                   ), manager_events AS (
                       SELECT turn.chat_id, reply.created_at, reply.confirmed_quote_id
                       FROM manager_replies AS reply JOIN chat_turns AS turn ON turn.turn_id = reply.handoff_id
                   ), first_events AS (
                       SELECT chat_id, min(replied_at) AS replied_at FROM (
                           SELECT chat_id, updated_at AS replied_at FROM turns WHERE outcome <> 'handoff'
                           UNION ALL
                           SELECT chat_id, created_at FROM manager_events
                       ) AS replies GROUP BY chat_id
                   ), confirmations AS (
                       SELECT turn.chat_id, resolution.created_at, turn.has_quote
                       FROM customer_resolutions AS resolution JOIN turns AS turn USING (turn_id)
                   ), first_resolutions AS (
                       SELECT chat_id, min(resolved_at) AS resolved_at FROM (
                           SELECT chat_id, updated_at AS resolved_at FROM turns WHERE has_quote
                           UNION ALL
                           SELECT chat_id, created_at FROM confirmations
                           UNION ALL
                           SELECT chat_id, created_at FROM manager_events
                       ) AS events GROUP BY chat_id
                   )
                   SELECT
                       (SELECT count(*) FROM turns WHERE outcome = 'handoff') AS "handoffs",
                       (SELECT count(*) FROM manager_events) AS "managerAnswered",
                       (SELECT count(*) FROM manager_events WHERE confirmed_quote_id IS NOT NULL) AS "managerConfirmedQuotes",
                       (SELECT count(*) FROM turns
                        WHERE has_quote AND NOT EXISTS (
                            SELECT 1 FROM manager_events WHERE confirmed_quote_id = turns.turn_id
                        )) AS "automaticQuotes",
                       (SELECT count(DISTINCT confirmation.chat_id) FROM confirmations AS confirmation
                        WHERE NOT has_quote AND NOT EXISTS (
                            SELECT 1 FROM manager_events WHERE chat_id = confirmation.chat_id
                        )) AS "customerConfirmedAnswers",
                       percentile_cont(0.5) WITHIN GROUP (
                           ORDER BY extract(epoch FROM (event.replied_at - first.submitted_at)) * 1000
                       ) AS "medianFirstReplyMs",
                       percentile_cont(0.5) WITHIN GROUP (
                           ORDER BY extract(epoch FROM (resolution.resolved_at - first.submitted_at)) * 1000
                       ) AS "medianResolutionMs"
                   FROM first_requests AS first
                   LEFT JOIN first_events AS event USING (chat_id)
                   LEFT JOIN first_resolutions AS resolution USING (chat_id)"""
            ).fetchone()

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
        query = """SELECT turn.turn_id, turn.message_text, turn.result,
                          coalesce((SELECT jsonb_agg(jsonb_build_object('id', reply.handoff_id, 'text', reply.text)
                                                   ORDER BY reply.created_at, reply.handoff_id)
                                    FROM manager_replies AS reply WHERE reply.after_sequence = turn.sequence),
                                   '[]'::jsonb) AS replies
                   FROM chat_turns AS turn WHERE chat_id = %s"""
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
            for reply in row["replies"]:
                messages.append(MessageView(turn_id=reply["id"], role="assistant", text=reply["text"], author="manager"))
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
