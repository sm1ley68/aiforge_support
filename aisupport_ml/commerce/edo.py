"""Public EDO help for chat sessions without organizational access."""

import re

from .contracts import Source
from .retrieval import normalize


STORE_EDO = Source(
    "softline-store-edo", "2026-11-27", "Softline Store — получение документов через ЭДО",
    "Для подключения ЭДО по заказам Softline Store отправьте заявку своему менеджеру или на edo@softline.com. "
    "Укажите в заявке оператора ЭДО и реквизиты компании.",
    "https://store.softline.ru/delivery_info/",
)
ECOMMERCE_EDO = Source(
    "softline-ecommerce-edo", "2026-11-27", "Softline Ecommerce — есть ли электронный документооборот?",
    "По заказам Allsoft напишите на edo@allsoft.ru. Поддержка отправит приглашение в Контур.Диадок.",
    "https://support.ecommerce.softline.ru/kb/legal-entities/whether-there-is-electronic-document-management",
)

_TOPIC = re.compile(r"\b(?:эдо|электронн\w+ документооборот\w*)\b")
_PURCHASE = re.compile(r"\b(?:купить|подобрать|цена|стоит|стоимость)\b")
_STATUS = re.compile(
    r"\b(?:статус\w*|проверь\w*|проверить|подключ[её]н\w*|подключил\w*|"
    r"приглашени\w*|мо[ейя] компани\w*|наш\w* организаци\w*|инн|ооо|пао|ао|работает)\b"
    r"|\bу (?!вас\b)\w+"
)
_ALLSOFT = re.compile(r"\b(?:allsoft|аллсофт|softline ecommerce)\b")


def edo_answer(text: str) -> tuple[str, tuple[Source, ...]] | None:
    query = normalize(text)
    if not _TOPIC.search(query) or _PURCHASE.search(query) and not _STATUS.search(query):
        return None
    if _ALLSOFT.search(query):
        sources = (ECOMMERCE_EDO,)
    else:
        sources = (STORE_EDO, ECOMMERCE_EDO)
    answer = "\n\n".join(source.text for source in sources)
    if _STATUS.search(query):
        answer = (
            "Чтобы проверить статус ЭДО или приглашения конкретной организации, войдите в кабинет оператора ЭДО "
            "с учётной записью, у которой есть права на эту организацию. "
            "Если доступа нет или статус не виден, обратитесь по контакту вашего магазина.\n\n" + answer
        )
    return answer, sources
