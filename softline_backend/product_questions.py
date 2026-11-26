import re
from pathlib import Path

from .catalog import lookup_offer, lookup_sku, product_card
from .contracts import CatalogReference, MessageView, ProductCard, Source, TurnResult, VerifiedFact


SKU_SUFFIX = re.compile(r"\s+(?:у\s+|для\s+)?(?:sku|артикул(?:а)?)[\s:№#]+([\w][\w./+:-]{0,127})$", re.I)
QUESTIONS = {
    "price": r"сколько стоит(?: товар| лицензия| продукт)?|какая цена|какова цена|цена",
    "availability": r"(?:есть(?: ли)? |он |она )?в наличии|доступен ли|доступна ли|какое наличие",
    "edition": r"какая редакция|что за редакция|редакция",
    "term": r"какой срок(?: действия)? лицензии|на какой срок лицензия|срок(?: действия)? лицензии",
    "license_type": r"какой тип лицензии|какая лицензия|тип лицензии",
    "user_limit": r"на сколько пользователей|сколько пользователей(?: поддерживает)?|лимит пользователей",
    "deployment": r"какое развертывание|где разворачивается|можно ли развернуть локально|он локальный",
    "origin": r"какая страна происхождения|это российский продукт|это российское решение|страна происхождения",
    "compatibility": r"совместим(?:а|о)? (?:ли )?с (.+)|с (.+) (?:совместим(?:а|о)?|работает)",
}
LABELS = {
    "price": "цена",
    "availability": "наличие",
    "edition": "редакция",
    "term": "срок лицензии",
    "license_type": "тип лицензии",
    "user_limit": "лимит пользователей",
    "deployment": "развёртывание",
    "origin": "страна происхождения",
    "compatibility": "совместимость",
}


def _matching_fact(card: ProductCard, field: str, question: re.Match[str]) -> VerifiedFact | None:
    if field != "compatibility":
        return next((item for item in card.verified_facts if item.field == field), None)
    target = (question[1] or question[2]).strip()
    return next(
        (
            item
            for item in card.verified_facts
            if item.field == field and item.value.casefold().replace("ё", "е") == target
        ),
        None,
    )


def _fact_text(card: ProductCard, field: str, fact: VerifiedFact | None) -> str | None:
    snapshot = card.snapshot_at.strftime("%d.%m.%Y")
    if field == "price":
        if card.price_amount is not None and card.currency:
            return f"Цена «{card.title}» по снимку от {snapshot} составляет {card.price_amount} {card.currency}."
        return None
    if field == "availability":
        if card.availability is not None:
            status = "есть в наличии" if card.availability else "нет в наличии"
            return f"По снимку от {snapshot} товар «{card.title}» {status}."
        return None

    if fact:
        return f"По данным каталога у «{card.title}» {LABELS[field]} — {fact.value}."
    return None


def product_question_reply(index: Path, text: str, history: list[MessageView]) -> TurnResult | None:
    question = " ".join(text.split()).rstrip("?!")
    sku_match = SKU_SUFFIX.search(question)
    if sku_match:
        question = question[:sku_match.start()]
    normalized = question.casefold().replace("ё", "е").removeprefix("а ")
    for field, pattern in QUESTIONS.items():
        question_match = re.fullmatch(pattern, normalized)
        if question_match is not None:
            break
    else:
        return None

    if sku_match:
        matches = lookup_sku(index, sku_match[1])
        offer = matches[0] if len(matches) == 1 else None
    else:
        references = history[-1].catalog_references if history and history[-1].role == "assistant" else []
        if len(references) != 1:
            return TurnResult(outcome="clarify", text="Укажите артикул товара, о котором спрашиваете.")
        reference = references[0]
        offer = lookup_offer(index, reference.offer_id)
        if offer is not None:
            same_product = (
                offer.sku == reference.sku
                if reference.sku is not None
                else (offer.title or f"Предложение {offer.offer_id}") == reference.title
            )
            if not same_product:
                offer = None

    if offer is None:
        return TurnResult(outcome="clarify", text="Не удалось однозначно найти этот товар в актуальном снимке. Проверьте артикул.")
    card = product_card(offer, "Карточка из актуального снимка каталога")
    if card is None:
        return TurnResult(outcome="clarify", text="В актуальном снимке у товара нет проверяемой ссылки. Могу передать вопрос менеджеру.")

    fact = _matching_fact(card, field, question_match)
    source = fact.source if fact is not None else Source(title=card.title, url=card.url)
    selection = CatalogReference(offer_id=card.offer_id, sku=card.sku, title=card.title)
    answer = _fact_text(card, field, fact)
    if answer is None:
        return TurnResult(
            outcome="clarify",
            text=f"Для «{card.title}» в текущем снимке не подтверждается {LABELS[field]}. Могу передать вопрос менеджеру.",
            sources=[source],
            catalog_selection=selection,
        )
    return TurnResult(
        outcome="answer",
        text=answer,
        sources=[source],
        catalog_selection=selection,
    )
