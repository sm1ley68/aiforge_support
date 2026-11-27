"""Reviewed general support answers, grouped by the action the customer needs."""

import re

from .contracts import Source, SupportTopic
from .retrieval import normalize


KEYS = Source(
    "softline-lk-keys", "2026-11-27", "Ключи активации и дистрибутивы",
    "Войдите в личный кабинет «Софтлайн Цифровой Актив» и откройте «Дистрибутивы и ключи». "
    "Если ищете лицензию по заказу, откройте «Счета и платежи», разверните заказ и перейдите к продукту. "
    "Также проверьте, пришло ли уведомление о доставке лицензии.",
    "https://docs.softline.com/ru-ru/lk/fulfillment",
    aliases=("Где скачать ключ активации", "Где найти ключи и дистрибутивы"),
    reusable=True,
)
ACTIVATION = Source(
    "softline-lk-activation-instructions", "2026-11-27", "Инструкция по активации",
    "В личном кабинете откройте «Дистрибутивы и ключи», найдите купленный продукт и откройте его "
    "инструкцию по активации. Если активация завершилась ошибкой, сообщите её текст или код без ключа лицензии.",
    "https://docs.softline.com/ru-ru/lk/fulfillment",
    reusable=True,
)
RETURNS = Source(
    "softline-store-return-instructions", "2026-11-27", "Возврат в Softline Store",
    "Откройте условия возврата в разделе «Оплата и доставка». Для электронной лицензии проверьте правила "
    "её возврата и уточните, был ли получен ключ. Для оформления возврата по конкретному заказу "
    "подключу менеджера, который проверит обстоятельства покупки и подскажет дальнейшие шаги.",
    "https://store.softline.ru/delivery_info/",
    reusable=True,
)
SUPPORT_ANSWERS: dict[SupportTopic, Source] = {"keys": KEYS, "activation": ACTIVATION, "returns": RETURNS}

_RETURN = re.compile(r"\b(?:возврат\w*|вернуть (?:деньги|оплат\w*|лицензи\w*|товар\w*|заказ\w*|покупк\w*))\b")
_ACTIVATION = re.compile(r"\b(?:активаци\w*|активир\w*)\b")
_KEYS = re.compile(r"\b(?:ключ(?:и|а|ей|ом)?|дистрибутив\w*|код(?:а)? активации|лицензионн\w* код\w*)\b")
_FIND = re.compile(
    r"\b(?:где|куда|откуда|достать|получ\w*|найти|искать|скача\w*|выда\w*|присла\w*|приш\w*|поступ\w*|"
    r"письм\w*|не вижу|взять|не видн\w*|не наш[ел]\w*|отсутств\w*|что делать)\b"
)
_FAILURE = re.compile(
    r"\b(?:не (?:помог\w*|получ\w*|удал[оа]сь|заработ\w*|принима\w*|работа\w*|подход\w*|наш[ел]\w*|активир\w*|сработ\w*)|"
    r"(?:все еще|по прежнему) (?:нет|не \w+)|остал\w* ошибк\w*|"
    r"ошибк\w* (?:остал\w*|повтор\w*)|снова ошибк\w*|там пусто)\b"
)
_FOLLOW_UP = re.compile(
    r"^(?:(?:да|нет|все равно|к сожалению|в итоге|после этого|я|там|это|так|все еще|по прежнему) )*"
    r"(?:не \w+|пусто|ошибк\w*|остал\w*|снова |уже |проверил\w*|пробовал\w*)"
)
_EXPLICIT_ORDER_CHECK = re.compile(
    r"^(?:а |пожалуйста )?(?:проверьте|посмотрите|найдите) (?:пожалуйста )?"
    r"(?:мой |наш )?заказ(?: |$)|"
    r"^(?:какой |где |уточните )?(?:сейчас )?статус (?:моего |нашего )?заказа(?: |$)"
)
_ORDER_CHECK = re.compile(
    r"\bзаказ\w* (?:номер )?[a-zа-я]*\d[a-zа-я0-9]*\b|"
    r"\b(?:проверьте|проверить|посмотрите|найдите) (?:пожалуйста )?(?:по )?(?:мо[йеёю] |наш\w* )?заказ\w*\b|"
    r"\b(?:оформите|начните|сделайте) (?:пожалуйста )?возврат\b|"
    r"\b(?:верните|прошу вернуть) (?:мне )?(?:деньги|оплат\w*)\b"
)
_OFF_TOPIC = re.compile(
    r"\b(?:api|ssh|oauth|kms|wi fi|wifi|автоматизир\w*|автоматическ\w* выдач\w*|"
    r"двухфактор\w*|восстановлен\w* парол\w*|приватн\w* ключ\w*|ключ\w* доступа)\b"
)


def support_topic(query: str) -> SupportTopic | None:
    if _OFF_TOPIC.search(query):
        return None
    if _RETURN.search(query):
        return "returns"
    keys, finding = _KEYS.search(query), _FIND.search(query)
    if keys and (finding or _ORDER_CHECK.search(query) or re.search(r"\b(?:еще нет|прежнему нет|нет ключ\w*)\b", query)):
        return "keys"
    if _ACTIVATION.search(query) and (
        _FAILURE.search(query) or re.search(r"\b(?:как|чем|ввести|инструкци\w*|ошибк\w*|проблем\w*)\b", query)
    ):
        return "activation"
    if keys and (_FAILURE.search(query) or re.search(r"\bввести\b", query)):
        return "activation"
    return None


def support_request(text: str, previous: SupportTopic | None) -> tuple[SupportTopic | None, bool]:
    query = normalize(text)
    topic = support_topic(query)
    if topic is None and _OFF_TOPIC.search(query):
        return None, False
    if topic is None and previous and len(query.split()) <= 12:
        if _ORDER_CHECK.search(query) or (_FOLLOW_UP.search(query) and _FAILURE.search(query)):
            topic = previous
    failed = topic is not None and topic == previous and (
        _FAILURE.search(query)
        or re.search(r"\b(?:уже (?:проверил\w*|пробовал\w*)|там по прежнему|там пусто)\b", query)
    )
    return topic, bool(_EXPLICIT_ORDER_CHECK.search(query) or (topic and (_ORDER_CHECK.search(query) or failed)))
