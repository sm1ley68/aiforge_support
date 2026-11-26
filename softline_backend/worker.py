import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from time import sleep

from psycopg import OperationalError

from .catalog import catalog_reply
from .contracts import HandoffDetails, MessageView, TurnResult
from .product_questions import product_question_reply
from .store import ChatStore
from .task_search import task_reply

logger = logging.getLogger(__name__)
Reply = Callable[[str, list[MessageView]], TurnResult]
MANAGER_REQUEST = re.compile(
    r"(?:(?:пожалуйста,? )?(?:позовите|позови|подключите|соедините с|позвать|хочу поговорить с) "
    r"(?:менеджер(?:а|ом)|оператор(?:а|ом)|человек(?:а|ом))"
    r"|(?:мне )?нужен (?:менеджер|оператор|человек))"
    r"(?:,? пожалуйста)?[.!?]*"
)


def demo_reply(_text: str, _history: list[MessageView]) -> TurnResult:
    return TurnResult(
        outcome="clarify",
        text="Уточните, пожалуйста, название продукта или задачу, которую нужно решить.",
    )


def reply_from_env() -> Reply:
    index_path = os.getenv("CATALOG_INDEX_PATH")
    if not index_path:
        return demo_reply

    index = Path(index_path)

    def reply(text: str, history: list[MessageView]) -> TurnResult:
        return (
            product_question_reply(index, text, history)
            or task_reply(index, text, history)
            or catalog_reply(index, text)
            or demo_reply(text, history)
        )

    return reply


def process_one(store: ChatStore, reply: Reply = demo_reply) -> bool:
    turn = store.claim()
    if turn is None:
        return False

    history = store.previous_messages(turn)
    try:
        if MANAGER_REQUEST.fullmatch(" ".join(turn.message_text.casefold().split())):
            result = TurnResult(
                outcome="handoff",
                text="Передал ваше обращение менеджеру.",
                handoff=HandoffDetails(reason="customer_requested", summary=turn.message_text),
            )
        else:
            result = reply(turn.message_text, history)
    except Exception as exc:
        logger.warning("Turn %s failed (%s)", turn.turn_id, type(exc).__name__)
        saved = store.finish(turn, error="processing_failed")
    else:
        saved = store.finish(turn, result=result)

    if not saved:
        logger.info("Turn %s lease expired before completion", turn.turn_id)
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    store = ChatStore(os.environ["DATABASE_URL"])
    reply = reply_from_env()
    while True:
        try:
            if not process_one(store, reply):
                sleep(0.5)
        except OperationalError:
            logger.warning("PostgreSQL unavailable, retrying")
            sleep(1)


if __name__ == "__main__":
    main()
