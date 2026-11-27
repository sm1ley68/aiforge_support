import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep

from psycopg import OperationalError

from aisupport_ml.commerce.edo import edo_answer
from aisupport_ml.commerce.retrieval import normalize
from aisupport_ml.commerce.routing import explicit_handoff_requested

from .catalog import catalog_reply
from .commerce_bridge import CommerceBridge, commerce_from_env
from .contracts import HandoffDetails, MessageView, Source, TurnResult
from .manager_search import match_paraphrase, product_scope
from .product_questions import product_question_reply
from .quotes import QUOTE_REQUEST
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


def process_one(
    store: ChatStore, reply: Reply = demo_reply, *, commerce: CommerceBridge | None = None
) -> bool:
    turn = store.claim()
    if turn is None:
        return False

    started = monotonic()
    outcome = "failed"
    logger.info("turn_claimed turn_id=%s attempt=%d", turn.turn_id, turn.attempts)
    history = store.previous_messages(turn)
    try:
        if commerce is not None:
            result = commerce.reply(turn, history, store.previous_commerce_state(turn))
        elif MANAGER_REQUEST.fullmatch(" ".join(turn.message_text.casefold().split())):
            result = TurnResult(
                outcome="handoff",
                text="Передал ваше обращение менеджеру.",
                handoff=HandoffDetails(reason="customer_requested", summary=turn.message_text),
            )
        elif answer := edo_answer(turn.message_text):
            text, sources = answer
            result = TurnResult(outcome="answer", text=text, sources=[
                Source(title=source.title, url=source.url) for source in sources
            ])
        else:
            result = reply(turn.message_text, history)
        if (result.outcome in {"clarify", "handoff"}
                and not explicit_handoff_requested(turn.message_text) and not QUOTE_REQUEST.fullmatch(turn.message_text.strip())):
            if result.handoff is None or (
                result.handoff.reason in {"insufficient_evidence", "provider_unavailable"}
                and not {"Вопрос клиента", "Спорный факт", "Что проверить"} & result.handoff.requirements.keys()
            ):
                catalog = commerce.agent.catalog_index if commerce is not None else None
                reference = product_scope(turn.message_text, history, catalog)
                sku = (reference.sku or reference.offer_id) if reference is not None else None
                article = store.match_manager_knowledge(normalize(turn.message_text), sku)
                if article is None:
                    candidates = store.manager_knowledge_candidates(sku)
                    article = match_paraphrase(turn.message_text, candidates, reference)
                if article is not None:
                    result = TurnResult(
                        outcome="answer", text=article["answer"], commerce_state=result.commerce_state,
                        catalog_selection=reference if article.get("sku") else None,
                        sources=[Source(title=article["question"], url=article["sourceUrl"])],
                    )
    except Exception as exc:
        logger.warning("turn_error turn_id=%s error=%s", turn.turn_id, type(exc).__name__)
        saved = store.finish(turn, error="processing_failed")
    else:
        outcome = result.outcome
        saved = store.finish(turn, result=result)

    logger.info(
        "turn_finished turn_id=%s attempt=%d outcome=%s saved=%s duration_ms=%d",
        turn.turn_id, turn.attempts, outcome, saved, int((monotonic() - started) * 1000),
    )
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    store = ChatStore(os.environ["DATABASE_URL"])
    reply = reply_from_env()
    commerce = commerce_from_env()
    knowledge_loaded = False
    while True:
        try:
            if commerce is not None and not knowledge_loaded:
                commerce.restore_knowledge(store.published_knowledge())
                knowledge_loaded = True
            if not process_one(store, reply, commerce=commerce):
                sleep(0.5)
        except OperationalError:
            logger.warning("PostgreSQL unavailable, retrying")
            sleep(1)


if __name__ == "__main__":
    main()
