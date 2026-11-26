from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin

from aisupport_ml.commerce.catalog import SoftlineCatalog
from aisupport_ml.commerce.routing import explicit_handoff_requested
from ml_pipeline.prep_data import normalize_route_text


_FACT = re.compile(
    r"\b(?:сколько|цен[ауеы]|стоимост\w*|наличи\w*|имеется ли|есть ли|"
    r"(?:возможно|можно|могу|можете) ли|возможность приобрести|можно у вас купить|"
    r"(?:лицензи|поддержива|совместим|входит|включен|работает)\w* ли|какой срок|"
    r"доходят ли|когда (?:получу|поставят|доставят)|как (?:работает|лицензируется))\b"
)
_CHOICE = re.compile(
    r"\b(?:како[йе]|какую|какие|какая)\b.{0,40}\b(?:лицензи|редакци|верси|вариант)\w*\b|"
    r"\b(?:что (?:купить|докупить|приобрести|посоветуете)|какой вариант|"
    r"сравни\w*|выбрать|подходящ\w* (?:программ|лицензи)\w*|какая позиция)\b"
)
_PURCHASE = re.compile(
    r"\b(?:приобретаем|приобретение|купить|купил|приобрести|заказать|закупить|докупить|"
    r"необходимо|нуж(?:ен|на|ны|но)|требуется|ищ[уе]\w*)\b"
)
_NEED = re.compile(
    r"\b(?:подб[ое]\w*|посовет\w*|альтернатив\w*|какую программу|что посоветуете|"
    r"чем (?:заменить|защитить|открыть)|нужно решение|решение для|"
    r"(?:хотим|нужно|надо)\s+(?:защитить|автоматизировать|настроить|заменить))\b"
)
_CONTACT = re.compile(
    r"\b(?:с кем (?:можно )?связаться|к кому обратиться|"
    r"(?:контакт\w*|e-mail|телефон\w*)\s+(?:сотрудник|консультант|представител|менеджер)\w*|"
    r"есть (?:у вас )?(?:живой )?(?:сотрудник|консультант|менеджер)\w*)\b"
)
_CONTEXT = re.compile(r"\b(?:эт(?:ой|у|ого|а|от|и)|так(?:ого|ой|ая)|данн(?:ого|ой|ую|ая)|саму|он[аи]?)\b")
_STOP = frozenset((
    "подскажите пожалуйста интересует приобретение приобрести купить есть срок нужен нужна нужно доступны "
    "версия лицензия цена стоимость купить пользователей устройств размещения года день добрый можно ли "
    "спасибо работает сайте обновление комплект состав лицензии организации редакция оформление купить "
    "лицензию входит какая такой будет будет день этот новая количество"
).split())


class RequestEvidence(TransformerMixin, BaseEstimator):
    """Business-action cues and literal title matches from the frozen storefront catalog."""

    def __init__(self, catalog_path: str):
        self.catalog_path = catalog_path

    def fit(self, _texts, _labels=None):
        return self

    def transform(self, texts):
        lookup = lru_cache(maxsize=4096)(SoftlineCatalog(Path(self.catalog_path)).has_title_phrase)
        result = []
        for message in texts:
            text = normalize_route_text(message).replace("крипто про", "криптопро").replace("астра линукс", "astra linux")
            words = re.findall(r"[^\W_]+", text)
            title_phrases = (
                " ".join((first, second)) for first, second in zip(words, words[1:])
                if len(first) >= 3 and len(second) >= 2 and first not in _STOP and second not in _STOP
                and not first.isdigit() and not second.isdigit()
            )
            resolved_name = any(map(lookup, title_phrases)) or any(
                lookup(word) for word in words if len(word) >= 4 and re.fullmatch(r"[a-z][a-z\d]+", word)
            )
            fact = bool(_FACT.search(text))
            choice = bool(_CHOICE.search(text))
            buy = bool(_PURCHASE.search(text))
            need = bool(_NEED.search(text))
            handoff = explicit_handoff_requested(text) or bool(_CONTACT.search(text))
            context = bool(_CONTEXT.search(text))
            result.append((resolved_name, fact, choice, buy, need, handoff, context,
                           fact and resolved_name, buy and resolved_name, choice and resolved_name,
                           (need or choice) and not resolved_name, context and not resolved_name,
                           fact and not resolved_name))
        return np.asarray(result, dtype=np.float64)
