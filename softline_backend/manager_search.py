"""Confidence-gated retrieval from reviewed manager articles."""

import re
from functools import lru_cache
from sqlite3 import DatabaseError

from aisupport_ml.commerce.catalog import SoftlineCatalog
from aisupport_ml.commerce.retrieval import normalize
from aisupport_ml.search import terms

from .contracts import CatalogReference, MessageView


_REFERENCE = re.compile(
    r"(?<![\w-])(?:(?=[a-z0-9-]*\d)[a-z][a-z0-9]*(?:-[a-z0-9]+)*|\d{5,12})(?![\w-])",
    re.I,
)
_LABELLED_REFERENCE = re.compile(
    r"\b(?:артикул\w*|sku|id предложения)\s*[:№#]?\s*([a-z0-9][a-z0-9._/-]{2,39})(?![\w-])", re.I,
)
_UPPERCASE_SKU = re.compile(r"(?<![\w-])[A-Z]{4,18}(?![\w-])")
_IMPLICIT_PRODUCT = re.compile(
    r"\b(?:у (?:него|нее|этой редакции)|в (?:нем|ней|этом продукте|этой версии|этой редакции)|"
    r"для (?:нее|него|этой версии|этой редакции)|(?:эта|эту) (?:редакцию|редакция|версию|версия)|"
    r"этот продукт|здесь)\b"
)
_FILLERS = set("а в вот где для и из как какой когда который ли мне мой можно на надо нужно он она они о от "
               "по пожалуйста подскажите при с то тут у что это этот эта этой его ее мы вы не".split())
_NEGATION = {"нельзя", "без", "не", "отключить", "отменить"}
_SYNONYMS = {
    "актуализировать": "обновить", "освежить": "обновить", "обновлять": "обновить",
    "перечень": "список", "компонент": "модуль",
    "дистрибутив": "установщик", "скачка": "скачать", "скачивать": "скачать",
    "инсталляция": "установка", "инсталлировать": "установить",
    "поддерживаться": "поддерживать", "совмещаться": "совместимый",
    "востребовать": "запросить", "запрашивать": "запросить",
}
_COMMON_TECH = {"api", "ocr", "pdf", "usb", "xml", "csv", "json", "docx", "windows", "linux", "macos"}


def product_scope(text: str, history: list[MessageView], catalog: SoftlineCatalog | None) -> CatalogReference | None:
    refs = {ref.casefold().rstrip(".") for ref in _LABELLED_REFERENCE.findall(text)}
    refs.update(_REFERENCE.findall(text.casefold()))
    refs.update(code.casefold() for code in _UPPERCASE_SKU.findall(text) if code.casefold() not in _COMMON_TECH)
    if refs:
        if catalog is None or len(refs) != 1:
            return None
        try:
            matches = catalog.by_reference(next(iter(refs)))
        except (DatabaseError, OSError):
            return None
        if len(matches) != 1:
            return None
        offer, = matches
        return CatalogReference(offer_id=offer.offer_id, sku=offer.vendor_code, title=offer.title)
    if not _IMPLICIT_PRODUCT.search(normalize(text)) or not history:
        return None
    last = history[-1]
    if last.role != "assistant" or len(last.catalog_references) != 1:
        return None
    selected, = last.catalog_references
    foreign = set(re.findall(r"\b[a-z][a-z0-9]+\b", text.casefold())) - set(terms(selected.title)) - _COMMON_TECH
    if foreign:
        return None
    return selected


@lru_cache(maxsize=1)
def _morphology():
    try:
        from pymorphy3 import MorphAnalyzer
        return MorphAnalyzer(lang="ru")
    except (ImportError, AttributeError, OSError):
        return None


@lru_cache(maxsize=4096)
def _lemma(word: str) -> str:
    morph = _morphology()
    if morph is not None and re.fullmatch(r"[а-я]{3,}", word):
        forms = morph.parse(word)
        if forms:
            word = forms[0].normal_form
    return _SYNONYMS.get(word, word)


def _tokens(text: str, scope: CatalogReference | None = None) -> frozenset[str]:
    if scope is not None:
        text = _IMPLICIT_PRODUCT.sub(" ", normalize(text))
    words = set(terms(text))
    if scope is not None:
        words -= set(terms(" ".join((scope.offer_id, scope.sku or "", scope.title)))) - _COMMON_TECH
    return frozenset(_lemma(word) for word in words - _FILLERS if len(word) > 2 or word.isdigit()) - _FILLERS


def _signature(text: str) -> set[str]:
    return set(terms(text)) & _NEGATION


def match_paraphrase(query: str, articles: list[dict], scope: CatalogReference | None) -> dict | None:
    """Use content-word coverage and an ambiguity margin, with ability to abstain."""
    if len(query) > 500 or len(articles) > 500:
        return None
    wanted = _tokens(query, scope)
    if len(wanted) < 2:
        return None
    signature = _signature(query)
    scored = []
    minimum_coverage = 1.0 if scope is not None else 0.8
    for article in articles:
        best = 0.0
        for wording in (article["question"], *article.get("aliases", [])):
            if _signature(wording) != signature:
                continue
            candidate = _tokens(wording, scope)
            overlap = len(wanted & candidate)
            if overlap >= 2 and overlap / len(wanted) >= minimum_coverage and overlap / len(candidate) >= 0.66:
                score = 2 * overlap / (len(wanted) + len(candidate))
                best = max(best, score)
        if best >= 0.8:
            scored.append((best, article))
    scored.sort(key=lambda item: -item[0])
    if not scored or (len(scored) > 1 and scored[0][0] - scored[1][0] < 0.14):
        return None
    return scored[0][1]
