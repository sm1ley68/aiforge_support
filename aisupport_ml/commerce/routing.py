"""Conservative routing of the first customer message, before answering it."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable


_HUMAN = r"(?:менеджер|оператор|сотрудник|человек|специалист)\w*"
_HUMAN_ACTION = r"(?:соедините|переключите|переведите|позовите|позови|подключите|свяжите|вызовите)"
_HANDOFF = re.compile(
    rf"\b{_HUMAN_ACTION}\b(?:\s+[\w-]+){{0,3}}\s+{_HUMAN}\b|"
    rf"\b(?:нужен|нужна|поговорить с|связаться с|контакт)\s+{_HUMAN}\b"
)
_NO_HANDOFF = re.compile(
    rf"\bне\s+(?:{_HUMAN_ACTION}|переключайте|переводите|соединяйте|зовите)\b|"
    rf"\b(?:не\s+нужен\s+{_HUMAN}|{_HUMAN}\s+не\s+нужен)\b"
)
_SPECIAL = re.compile(
    r"\b(?:индивидуальн\w*|персональн\w*)\s+(?:скидк\w*|услови\w*)\b|"
    r"\b(?:согласова\w*|обсуди\w*|возможна)\b.{0,32}\bпостоплат\w*\b"
)
_FACT = re.compile(
    r"\b(?:цен\w*|стоимост\w*|наличи\w*)\b|\bсколько\s+(?:будет\s+)?сто\w*\b|"
    r"\b(?:можно|возможно)\s+(?:ли\s+)?(?:приобрести|купить|заказать)\b|"
    r"\bесть ли\s+(?:возможность|такая лицензия|в наличии)\b"
)
_CHOICE = re.compile(
    r"\b(?:какой|какая|какую|какие|какое)\b.{0,32}\b(?:верси\w*|редакци\w*|лицензи\w*|дистрибутив\w*)\b|"
    r"\b(?:какая|какую)\s+подойд\w*\b|\b(?:как|что)\b.{0,16}\b(?:докупить|обновить|продлить)\b"
)
_PURCHASE = re.compile(
    r"\b(?:мне нужен|мне нужна|мне нужно|нужен|нужна|нужны|хочу купить|нужно приобрести)\b"
)
_NEED = re.compile(
    r"\b(?:посовет\w*|подбер\w*|подобрат\w*|какое решение|что (?:купить|выбрать))\b|"
    r"\bчтобы\s+(?:работал\w*|защит\w*|хран\w*|восстанавлива\w*|управля\w*)\b|"
    r"\b(?:хотим|хочу|нужно|надо)\s+(?:защитить|автоматизировать|настроить|резервировать)\b|"
    r"\b(?:нужно|ищем|ищу)\s+решение для\b"
)
_REFERENCE = re.compile(
    r"\b(?:верси[юяи]|редакци[юяи]|дистрибутив)\s+|"
    r"\bлицензи\w*\s+на\s+|\b(?:нужен|нужна|нужны|хочу купить|ищу)\s+(?!лицензи\w*\b)"
)
_REFERENCE_STOP = re.compile(
    r"\b(?:для|можно|нужно|необходимо|подходит|подойдет|какая|какую|как|на|со|чтобы|но)\b|[?!,;]",
)
_GENERIC = frozenset((
    "а и вот этот эта такое это его ее такой цена стоимость сколько стоит будет какая какой какие у вас ваша "
    "подскажите пожалуйста скажите можно ли возможность приобрести купить заказать как есть наличии наличия в "
    "на по для от лицензия лицензии лицензию пользователей пользователя одного двух можно ли может"
).split())
_ALIASES = {"астра линукс": "astra linux", "крипто про": "криптопро"}


def _normalize(message: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", message).casefold().replace("ё", "е").split())


def _has_named_reference(text: str, matches_catalog: Callable[[str], bool]) -> bool:
    for marker in _REFERENCE.finditer(text):
        fragment = _REFERENCE_STOP.split(text[marker.end():], maxsplit=1)[0]
        words = re.findall(r"[^\W_]+", fragment)[:5]
        if not words or words[0] in _GENERIC:
            continue
        for length in range(len(words), 0, -1):
            phrase = " ".join(words[:length])
            if length == 1 and (len(phrase) < 4 or phrase.isdigit()):
                continue
            if matches_catalog(_ALIASES.get(phrase, phrase)):
                return True
    return False


def explicit_handoff_requested(message: str) -> bool:
    text = _normalize(message)
    return not _NO_HANDOFF.search(text) and bool(_HANDOFF.search(text) or _SPECIAL.search(text))


def choose_first_route(
    message: str,
    *,
    matches_catalog: Callable[[str], bool],
    suggested_route: str | None = None,
    score: float = 0.0,
) -> str:
    """Return a routing hint, not a product match or a decision about stock/licensing."""
    text = _normalize(message)
    if explicit_handoff_requested(message):
        return "handoff"

    asking_to_choose = _CHOICE.search(text)
    named = bool((asking_to_choose or _PURCHASE.search(text)) and _has_named_reference(text, matches_catalog))
    if asking_to_choose and named:
        return "find_named_product"
    if _FACT.search(text):
        # A stock/price question with a named subject remains a fact question even
        # when it begins with "I need ...". Bare questions need clarification.
        significant = set(re.findall(r"[a-zа-я]+", text)) - _GENERIC
        if significant:
            return "answer_product_question"
    if named:
        return "find_named_product"
    if _NEED.search(text):
        return "recommend_by_need"
    if re.fullmatch(r"[\w.-]+(?:\s+[\w.-]+){0,3}", text) and re.search(r"[a-z]{3,}", text) and matches_catalog(text):
        return "find_named_product"
    # Only a reversible routing suggestion can be accepted from the learned model.
    if suggested_route == "recommend_by_need" and score >= 0.55:
        return suggested_route
    return "clarify"
