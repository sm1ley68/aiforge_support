"""Local masking and an allowlisted payload for external storefront inference."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from ipaddress import ip_address
import re
import unicodedata


_MAX_TEXT = 8_000
_MAX_TOTAL = 24_000
_MAX_HISTORY = 8

# The value group excludes the label when it helps preserve the meaning of a message.
_IDENTIFIERS = tuple((kind, re.compile(pattern, re.I)) for kind, pattern in (
    ("email", r"(?<![\w@])[^\s@,;:()<>]{1,64}@[\w.-]+\.[a-zа-яё]{2,}(?![\w@])"),
    ("phone", r"(?<!\w)(?:\+7|7|8)[ .-]*\(?\d{3}\)?[ .-]*\d{3}[ .-]*\d{2}[ .-]*\d{2}(?!\d)"),
    ("phone", r"\b(?:тел(?:ефон)?\.?|мобильный|whatsapp|ватсап)\s*[:№]?\s*(?P<value>\+?\d(?:[(). -]*\d){6,14})(?!\d)"),
    ("phone", r"(?<![\w+])\+(?!7)\d(?:[(). -]*\d){7,14}(?!\d)"),
    ("snils", r"(?<!\d)\d{3}-\d{3}-\d{3}[ -]\d{2}(?!\d)"),
    ("snils", r"\bснилс\s*[:№]?\s*(?P<value>\d(?:[ -]*\d){10})(?!\d)"),
    ("tax_id", r"\bинн\s*[:№]?\s*(?P<value>\d{12}|\d{10})(?!\d)"),
    ("passport", r"(?<!\d)\d{2}[ ]+\d{2}[ ]+\d{6}(?!\d)"),
    ("passport", r"\b(?:паспорт(?:а)?|серия\s+паспорта)\s*(?:рф\s*)?(?:серия\s*)?[:№]?\s*"
     r"(?P<value>\d{2}[ -]?\d{2}[ ,–-]*(?:(?:номер|№)\s*[:№]?\s*)?\d{6})(?!\d)"),
    ("passport", r"\b(?:номер паспорта|паспорт\s+номер)\s*[:№]?\s*(?P<value>\d{6})(?!\d)"),
    ("passport", r"\bсерия паспорта\s*[:№]?\s*(?P<value>\d{2}[ -]?\d{2})(?!\d)"),
    ("document", r"\b(?:полис\s+(?:омс|дмс)|омс|дмс|миграционн\w+\s+карт\w+|водительск\w+\s+удостоверен\w+)\s*"
     r"(?:номер\s*)?[:№]?\s*(?P<value>[a-zа-яё]*\s*\d(?:[ -]*\d){5,19})(?!\d)"),
    ("document", r"\b(?:паспорт\s+выдан|кем выдан|дата выдачи|код подразделения)\s*[:№]?\s*"
     r"(?P<value>\d{1,2}[./]\d{1,2}[./]\d{2,4}|[^;.!?\n]+)"),
    ("birth", r"\b(?:(?:дата|год|месяц|место) рождения|родил(?:ся|ась))\s*(?:в\s+)?[:=]?\s*"
     r"(?P<value>\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}(?:\s+году)?|[^;,.!?\n]+)"),
    ("birth", r"\b(?P<value>\d{1,2}[./]\d{1,2}[./]\d{2,4})\s*(?:г\.\s*р\.|года рождения)"),
    ("address", r"\b(?:адрес(?:\s+(?:проживания|регистрации|доставки))?|проживаю|зарегистрирован[а]?)\s*"
     r"[:=]\s*(?P<value>[^;!?\n]+?)(?=\s+[А-ЯЁA-Z][^;!?\n]{0,40}:|[;!?\n]|$)"),
    ("address", r"\b(?:ул\.|улица|проспект|пр-т|переулок|пер\.|шоссе)\s+"
     r"[а-яё\d-]+(?:\s+[а-яё-]+){0,4}\s*,?\s*(?:д(?:ом)?\.?\s*)?\d+[а-яё]?"
     r"(?:\s*[,/]\s*(?:корпус|корп\.|кв\.|квартира|подъезд)\s*\d+[а-яё]?)*"),
    ("account", r"(?<![\w@])@[a-zа-яё0-9_][\w.-]{1,63}"),
    ("account", r"\b(?:логин|никнейм|telegram|телеграм|user[_ -]?id)\s*[:=№]\s*(?P<value>[@\w.-]+)"),
    ("account", r"(?:https?://|www\.)[^\s<>()]+"),
    ("device", r"\b(?:cookie|session[_ -]?id|imei|device[_ -]?id|идентификатор устройства|mac[- ]адрес|"
     r"токен сессии)\s*[:=№]\s*(?P<value>[^\s;,]+)"),
    ("device", r"(?<![\w:])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![\w:])"),
    ("device", r"(?<!\w)[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?!\w)"),
    ("location", r"\b(?:геолокация|координаты)\s*[:=]\s*(?P<value>[-+]?\d{1,3}[.,]\d+\s*[,; ]\s*[-+]?\d{1,3}[.,]\d+)"),
    ("order", r"\b(?:номер заказа|заказ(?:а)?\s*(?=[№#:]|\d)|трек[- ]номер|номер отправления)\s*"
     r"[:№#]?\s*(?P<value>[a-zа-яё0-9-]*\d[a-zа-яё0-9-]*)(?!\w)"),
    ("payment", r"\b(?:номер карты|банковск\w+\s+карт\w+|расч[её]тный сч[её]т|банковский сч[её]т|cvv|cvc|"
     r"пин[- ]код)\s*[:№]?\s*(?P<value>\d(?:[ -]*\d){2,19})(?!\d)"),
))

_NAME = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
_LABELLED_NAME = re.compile(rf"(?i:\b(?:фио|фамилия и имя|меня зовут|мо[её] имя)\b)\s*[:=]?\s*(?P<value>{_NAME}(?:\s+{_NAME}){{0,2}})")
_LOWERCASE_NAME = re.compile(r"\b(?:фио|меня зовут|мо[её] имя)\s*[:=]?\s*(?P<value>[а-яё-]+(?:\s+[а-яё-]+){1,2})"
                             r"(?=\s*[,.;!\n])", re.I)
_IP = re.compile(r"(?<![\w.:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:]|\.\d)|"
                 r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])", re.I)
_CARD = re.compile(r"(?<!\d)\d(?:[ -]*\d){12,18}(?!\d)")

# Context-dependent categories require local handling even if part of the text can be masked.
_RESTRICTED = {
    "health": re.compile(r"\b(?:диагноз\w*|диабет\w*|онколог\w*|инвалидност\w*|вич|снилс\s+пациент\w*|"
                         r"болею|лечусь|история болезни|медицинск\w+\s+(?:заключен\w*|карт\w*|данн\w*))\b", re.I),
    "sensitive_context": re.compile(
        r"\b(?:интимн\w+\s+жизн\w*|сексуальн\w+\s+ориентаци\w*|судим(?:ость|ости|ост[ьи]ю|ого|ая|ый)?|"
        r"расов\w+\s+принадлежност\w*|национальност\w*|этническ\w+\s+происхожден\w*|"
        r"политическ\w+\s+(?:взгляд\w*|убеждени\w*)|религиоз\w+\s+убеждени\w*|вероисповедани\w*|"
        r"философск\w+\s+убеждени\w*)\b", re.I),
    "personal_context": re.compile(
        r"\b(?:семейн\w+\s+положени\w*|состав семь\w*|мо[яию]\s+дет\w*|мой реб[её]нок|"
        r"место работы|я работаю|моя должность|окончил[а]?\s+(?:школ\w*|вуз\w*)|"
        r"моя зарплата|мой доход|моя задолженность|мо[йя]\s+кредит\w*)\b", re.I),
    "attachment": re.compile(
        r"\b(?:прикрепил[а]?|прикрепляю|во вложении|мо[яе]\s+фото|голосов\w+\s+сообщени\w*|"
        r"скан\w*\s+паспорта|резюме|паспортн\w+\s+данн\w*)\b", re.I),
}

_LABELS = {
    "email": "ПОЧТА", "phone": "ТЕЛЕФОН", "name": "ФИО", "snils": "СНИЛС", "tax_id": "ИНН",
    "passport": "ПАСПОРТ", "document": "ДОКУМЕНТ", "birth": "ДАННЫЕ_О_РОЖДЕНИИ", "address": "АДРЕС",
    "location": "МЕСТОПОЛОЖЕНИЕ", "account": "АККАУНТ", "device": "УСТРОЙСТВО",
    "ip": "IP", "order": "ЗАКАЗ", "payment": "ПЛАТЁЖНЫЕ_ДАННЫЕ",
}


@dataclass(frozen=True)
class PersonalSpan:
    start: int
    stop: int
    category: str


EntityDetector = Callable[[str], Iterable[PersonalSpan]]


@lru_cache(maxsize=1)
def _natasha_models():
    from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter

    return Doc, Segmenter(), NewsNERTagger(NewsEmbedding())


def _detect_entities(text: str) -> Iterable[PersonalSpan]:
    document_type, segmenter, tagger = _natasha_models()
    document = document_type(text)
    document.segment(segmenter)
    document.tag_ner(tagger)
    categories = {"PER": "name", "LOC": "location"}
    for span in document.spans:
        if span.type in categories:
            yield PersonalSpan(span.start, span.stop, categories[span.type])


@dataclass(frozen=True)
class MaskedText:
    text: str = field(repr=False)
    categories: tuple[str, ...]
    block_external: bool = False


def _luhn(text: str) -> bool:
    digits = [int(char) for char in text if char.isdecimal()][::-1]
    values = [value * 2 if offset % 2 else value for offset, value in enumerate(digits)]
    return any(digits) and sum(value - 9 if value > 9 else value for value in values) % 10 == 0


def _merge_spans(text: str, spans: Iterable[PersonalSpan]) -> str:
    parts = []
    cursor = 0
    spans = sorted(spans, key=lambda span: (span.start, -(span.stop - span.start)))
    if not spans:
        return text
    current = spans[0]
    for span in spans[1:]:
        if span.start < current.stop:
            current = PersonalSpan(current.start, max(current.stop, span.stop), current.category)
            continue
        parts.extend((text[cursor:current.start], f"[{_LABELS[current.category]}]"))
        cursor, current = current.stop, span
    parts.extend((text[cursor:current.start], f"[{_LABELS[current.category]}]", text[current.stop:]))
    return "".join(parts)


def mask_text(text: str, *, entity_detector: EntityDetector = _detect_entities) -> MaskedText:
    """Mask recognized spans locally. The result still counts as untrusted text."""
    if not isinstance(text, str) or len(text) > _MAX_TEXT:
        return MaskedText("[СООБЩЕНИЕ_НЕ_ПРОВЕРЕНО]", ("unverified_input",), True)
    text = "".join(char for char in unicodedata.normalize("NFKC", text)
                   if unicodedata.category(char) != "Cf")
    if len(text) > _MAX_TEXT:
        return MaskedText("[СООБЩЕНИЕ_НЕ_ПРОВЕРЕНО]", ("unverified_input",), True)
    restricted = tuple(kind for kind, pattern in _RESTRICTED.items() if pattern.search(text))
    if restricted:
        return MaskedText("[ЧУВСТВИТЕЛЬНЫЕ_ДАННЫЕ]", restricted, True)

    spans = []
    for category, pattern in (*_IDENTIFIERS, ("name", _LABELLED_NAME), ("name", _LOWERCASE_NAME)):
        for match in pattern.finditer(text):
            start, stop = match.span("value" if "value" in pattern.groupindex else 0)
            spans.append(PersonalSpan(start, stop, category))
    for match in _IP.finditer(text):
        try:
            ip_address(match[0])
        except ValueError:
            continue
        spans.append(PersonalSpan(*match.span(), "ip"))
    spans.extend(PersonalSpan(*match.span(), "payment") for match in _CARD.finditer(text) if _luhn(match[0]))
    try:
        entities = list(entity_detector(text))
        for item in entities:
            if item.category not in {"name", "location"} or not 0 <= item.start < item.stop <= len(text):
                raise ValueError("Invalid entity offsets or category")
        spans.extend(entities)
    except Exception:
        categories = tuple(sorted({span.category for span in spans} | {"entity_detector_unavailable"}))
        return MaskedText(_merge_spans(text, spans), categories, True)
    return MaskedText(_merge_spans(text, spans), tuple(sorted({span.category for span in spans})))


_PLATFORMS = {
    "windows 10": "windows_10", "windows 11": "windows_11", "windows server 2016": "windows_server_2016",
    "windows server 2019": "windows_server_2019", "windows server 2022": "windows_server_2022",
    "linux": "linux", "macos": "macos",
}
_PLATFORM = re.compile(r"\b(?:" + "|".join(_PLATFORMS) + r")\b", re.I)
_BACKUP = re.compile(r"\b(?:резервн\w*\s+коп(?:ирован\w*|и[июйя])|б[эе]кап\w*)\b", re.I)
_MAIL_SECURITY = re.compile(r"\b(?:защищ\w*|защити\w*|защит[ау])\s+(?:почт\w+\s+и\s+файл\w+|файл\w+\s+и\s+почт\w+)\b", re.I)
_TASK_PATTERNS = (("backup", _BACKUP), ("email_file_security", _MAIL_SECURITY))
_DEVICES = re.compile(r"(?<![\d.-])([1-9]\d{0,4})\s*(?:пк|ноутбук\w*|компьютер\w*|устройств\w*|узл\w*)\b", re.I)
_SEATS = re.compile(r"(?<![\d.-])([1-9]\d{0,4})\s*(?:пользовател\w*|мест\w*|лицензи\w*)\b", re.I)
_REFERENCE = re.compile(r"\b(?:sku|артикул|id\s+предложения)\s*[:№#]?\s*([a-z0-9][a-z0-9_.-]{1,39})(?![\w.-])", re.I)
_BARE_FACT = {
    "сколько стоит": "price", "а сколько стоит": "price", "какая цена": "price",
    "есть в наличии": "availability", "есть ли в наличии": "availability", "какой срок лицензии": "term",
}
_LOCAL = re.compile(r"\b(?:локально|без облака|на сво[её]м сервере|на внешн\w*\s+диск\w*)\b", re.I)
_CLOUD = re.compile(r"\b(?:в облаке|в облако|облачн\w+\s+разв[её]ртыван\w*)\b", re.I)


@dataclass(frozen=True)
class TechnicalRequest:
    task: str | None = None
    platform: str | None = None
    device_count: int | None = None
    license_count: int | None = None
    deployment: str | None = None
    fact: str | None = None
    catalog_reference: str | None = None


@dataclass(frozen=True)
class PrivacyResult:
    masked_message: str = field(repr=False)
    categories: tuple[str, ...]
    outbound_fields: TechnicalRequest | None = None

    @property
    def model_payload(self) -> dict[str, str | int] | None:
        """Return only generated technical fields. Never return free text or history."""
        if self.outbound_fields is None:
            return None
        fields = self.outbound_fields
        values = {
            "task": fields.task, "platform": fields.platform, "device_count": fields.device_count,
            "license_count": fields.license_count, "deployment": fields.deployment, "fact": fields.fact,
            "catalog_reference": fields.catalog_reference,
        }
        return {name: value for name, value in values.items() if value is not None}


def _bounded_count(value: object) -> int | None:
    return value if type(value) is int and 1 <= value <= 99_999 else None


def _canonical(value: object) -> str:
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def _selection_text(selection: Mapping[str, object]) -> list[str]:
    values = []
    for value in selection.values():
        items = value if isinstance(value, (list, tuple)) else (value,)
        if len(items) > 50:
            raise ValueError("Selection exceeds the supported shape")
        for item in items:
            if isinstance(item, str):
                values.append(item)
            elif item is not None and type(item) not in {int, bool}:
                raise ValueError("Selection contains an unsupported value")
    return values


def _project(
    text: str,
    selection: Mapping[str, object],
    is_public_reference: Callable[[str], bool] | None,
) -> TechnicalRequest | None:
    text = " ".join(text.split())
    tasks = {name for name, pattern in _TASK_PATTERNS if pattern.search(text)}
    platforms = {_PLATFORMS[_canonical(match[0])] for match in _PLATFORM.finditer(text)}
    devices = {int(match[1]) for match in _DEVICES.finditer(text)}
    seats = {int(match[1]) for match in _SEATS.finditer(text)}
    deployments = {name for name, pattern in (("local", _LOCAL), ("cloud", _CLOUD)) if pattern.search(text)}
    references = {match[1] for match in _REFERENCE.finditer(text)}
    if any(len(values) > 1 for values in (tasks, platforms, devices, seats, deployments, references)):
        raise ValueError("Conflicting technical requirements")
    reference = next(iter(references), None)
    if reference and (is_public_reference is None or is_public_reference(reference) is not True):
        raise ValueError("Unconfirmed catalog reference")
    fact = _BARE_FACT.get(_canonical(text).strip(" ?!."))
    if not any((tasks, platforms, devices, seats, deployments, fact, reference)):
        return None

    old_goal = _canonical(selection.get("goal"))
    old_task = next((name for name, pattern in _TASK_PATTERNS if pattern.fullmatch(old_goal)), None)
    if reference or (tasks and old_task not in tasks):
        old_task, selection = None, {}
    old_platform = _PLATFORMS.get(_canonical(selection.get("file_os")))
    old_deployment = next((name for name in ("local", "cloud") if selection.get("deployment") == name), None)
    return TechnicalRequest(
        task=next(iter(tasks), old_task), platform=next(iter(platforms), old_platform),
        device_count=next(iter(devices), _bounded_count(selection.get("nodes"))),
        license_count=next(iter(seats), _bounded_count(selection.get("users"))),
        deployment=next(iter(deployments), old_deployment), fact=fact, catalog_reference=reference,
    )


def prepare_llm_input(
    message: str,
    *,
    history: Sequence[str] = (),
    selection: Mapping[str, object] | None = None,
    has_attachments: bool = False,
    is_public_reference: Callable[[str], bool] | None = None,
    entity_detector: EntityDetector = _detect_entities,
) -> PrivacyResult:
    """Check the local inputs and return an allowlisted outbound projection or a local-only result."""
    selection = selection if selection is not None else {}
    try:
        if isinstance(history, str) or len(history) > _MAX_HISTORY or len(selection) > 50:
            raise ValueError("Too much context")
        texts = [message, *history, *_selection_text(selection)]
        if any(not isinstance(text, str) or len(text) > _MAX_TEXT for text in texts):
            raise ValueError("Invalid text")
        if sum(map(len, texts)) > _MAX_TOTAL:
            raise ValueError("Too much text")
    except (TypeError, AttributeError, ValueError):
        return PrivacyResult("[СООБЩЕНИЕ_НЕ_ПРОВЕРЕНО]", ("unverified_input",))

    checked = {text: mask_text(text, entity_detector=entity_detector) for text in dict.fromkeys(texts)}
    current = checked[message]
    categories = {kind for item in checked.values() for kind in item.categories}
    if has_attachments:
        categories.add("attachment")
    if has_attachments or any(item.block_external for item in checked.values()):
        return PrivacyResult(current.text, tuple(sorted(categories)))
    # Free-text state values with findings cannot seed even the technical projection.
    safe_selection = {key: value for key, value in selection.items()
                      if not isinstance(value, str) or not checked[value].categories}
    try:
        projection = _project(current.text, safe_selection, is_public_reference)
    except Exception:
        categories.add("unverified_technical_fields")
        projection = None
    if projection is None and not categories:
        categories.add("no_technical_fields")
    return PrivacyResult(current.text, tuple(sorted(categories)), projection)
