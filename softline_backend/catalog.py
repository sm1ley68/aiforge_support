import argparse
import gzip
import re
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import file_digest
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import iterparse
from defusedxml.common import DefusedXmlException
from pydantic import HttpUrl, TypeAdapter, ValidationError

from .contracts import ProductCard, Source, TurnResult, VerifiedFact


SCHEMA_VERSION = 2
COMPARISON_LIMIT = 5
SCHEMA = f"""
PRAGMA user_version = {SCHEMA_VERSION};
CREATE TABLE snapshot (
    sha256 TEXT NOT NULL,
    source_at TEXT NOT NULL
);
CREATE TABLE offers (
    offer_id TEXT PRIMARY KEY,
    sku TEXT,
    sku_key TEXT,
    group_id TEXT,
    title TEXT,
    title_key TEXT,
    family_key TEXT,
    edition TEXT,
    term TEXT,
    license_type TEXT,
    url TEXT,
    price TEXT,
    currency TEXT,
    available INTEGER
);
CREATE INDEX offers_sku ON offers (sku_key);
CREATE INDEX offers_title ON offers (title_key);
CREATE INDEX offers_family ON offers (family_key);
CREATE INDEX offers_group ON offers (group_id, offer_id);
"""

SKU_REQUEST = re.compile(
    r"(?:найди(?:те)?\s+|покажи(?:те)?\s+)?(?:sku|артикул)(?:\s+[:№#]?\s*|\s*[:№#]\s*)"
    r"([\w][\w./+:-]{0,127})[?]?",
    re.IGNORECASE,
)
PRODUCT_REQUEST = re.compile(
    r"(?P<command>нужен|нужна|нужно|найди(?:те)? продукт)\s+(?P<name>.{1,240}?)\??",
    re.IGNORECASE,
)
COMPARE_REQUEST = re.compile(r"сравни(?:те)?\s+редакции\s+(.{1,240}?)\??", re.IGNORECASE)
HTTP_URL = TypeAdapter(HttpUrl)

PARAMETER_NAMES = {
    "sku": "sku",
    "артикул": "sku",
    "vendorcode": "sku",
    "family": "family",
    "product family": "family",
    "семейство": "family",
    "линейка": "family",
    "edition": "edition",
    "редакция": "edition",
    "license term": "term",
    "срок лицензии": "term",
    "срок действия лицензии": "term",
    "license type": "license_type",
    "тип лицензии": "license_type",
}

FACT_LABELS = {"edition": "редакция", "term": "срок лицензии", "license_type": "тип лицензии"}
OFFER_FIELDS = "offer_id, sku, title, url, price, currency, available, source_at"


@dataclass(frozen=True)
class Snapshot:
    sha256: str
    source_at: datetime
    offer_count: int
    missing_id_count: int


@dataclass(frozen=True)
class Offer:
    offer_id: str
    sku: str | None
    title: str | None
    url: str | None
    price: str | None
    currency: str | None
    available: int | None
    source_at: str
    edition: str | None = None
    term: str | None = None
    license_type: str | None = None


def _name_key(value: str | None) -> str | None:
    return " ".join((value or "").casefold().split()) or None


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _snapshot_date(value: str | None) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value or "")
    except ValueError:
        raise ValueError("Feed date is missing or invalid. Pass --snapshot-at with an ISO timestamp.") from None
    if timestamp.tzinfo is None:
        raise ValueError("Feed date lacks a timezone. Pass --snapshot-at with an explicit offset.")
    return timestamp


def _validated_price(value: str | None, currency: str | None) -> tuple[str | None, str | None]:
    if not value or not currency or not re.fullmatch(r"[A-Za-z]{3}", currency):
        return None, None
    try:
        price = Decimal(value.replace(",", "."))
    except InvalidOperation:
        return None, None
    if not price.is_finite() or price < 0:
        return None, None
    return str(price), currency.upper()


def _offer_row(offer, offer_id: str) -> tuple:
    fields = {}
    params: dict[str, set[str]] = {}
    for child in offer:
        tag = _tag(child)
        value = (child.text or "").strip()
        if not value:
            continue
        if tag == "param":
            key = PARAMETER_NAMES.get(child.attrib.get("name", "").strip().casefold())
            if key:
                params.setdefault(key, set()).add(value)
        else:
            fields.setdefault(tag, value)

    known = {key: next(iter(values)) for key, values in params.items() if len(values) == 1}
    sku = fields.get("vendorCode") or known.get("sku")
    title = fields.get("name") or fields.get("model")
    raw_available = offer.attrib.get("available", "").strip().casefold()
    available = {"true": 1, "false": 0, "1": 1, "0": 0}.get(raw_available)
    price, currency = _validated_price(fields.get("price"), fields.get("currencyId"))
    return (
        offer_id,
        sku,
        sku.casefold() if sku else None,
        offer.attrib.get("group_id", "").strip() or None,
        title,
        _name_key(title),
        _name_key(known.get("family")),
        known.get("edition"),
        known.get("term"),
        known.get("license_type"),
        fields.get("url"),
        price,
        currency,
        available,
    )


def _load_feed(db: sqlite3.Connection, source: Path, source_at: str | None) -> Snapshot:
    with source.open("rb") as raw:
        digest = file_digest(raw, "sha256").hexdigest()
        raw.seek(0)
        compressed = raw.read(2) == b"\x1f\x8b"
        raw.seek(0)
        parsed = gzip.GzipFile(fileobj=raw) if compressed else raw
        with parsed:
            events = iterparse(parsed, events=("start", "end"), forbid_dtd=True)
            _, root = next(events)
            if _tag(root) != "yml_catalog":
                raise ValueError("Expected a YML catalog")
            timestamp = _snapshot_date(source_at or root.attrib.get("date"))
            db.execute("INSERT INTO snapshot VALUES (?, ?)", (digest, timestamp.isoformat()))
            stack = [root]
            inserted = skipped = 0
            for event, element in events:
                if event == "start":
                    stack.append(element)
                    continue
                stack.pop()
                if _tag(element) != "offer" or not stack or _tag(stack[-1]) != "offers":
                    continue
                offer_id = element.attrib.get("id", "").strip()
                if offer_id:
                    db.execute(
                        "INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        _offer_row(element, offer_id),
                    )
                    inserted += 1
                else:
                    skipped += 1
                stack[-1].remove(element)
    if not inserted:
        raise ValueError("The catalog contains no offers with IDs")
    return Snapshot(digest, timestamp, inserted, skipped)


def build_index(source: Path, destination: Path, *, source_at: str | None = None) -> Snapshot:
    """Build and validate the index before replacing the catalog visible to workers."""
    if source.resolve() == destination.resolve():
        raise ValueError("The source feed and SQLite destination must differ")
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript(SCHEMA)
            snapshot = _load_feed(db, source, source_at)
        temporary.replace(destination)
    except sqlite3.IntegrityError as exc:
        raise ValueError("The catalog contains duplicate offer IDs") from exc
    except (ParseError, DefusedXmlException, EOFError, gzip.BadGzipFile) as exc:
        raise ValueError("Invalid or unsafe YML catalog") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return snapshot


def _open_catalog(index: Path):
    uri = f"{index.resolve().as_uri()}?mode=ro"
    return closing(sqlite3.connect(uri, uri=True))


def lookup_sku(index: Path, sku: str) -> list[Offer]:
    with _open_catalog(index) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        fields = OFFER_FIELDS
        if version >= SCHEMA_VERSION:
            fields += ", edition, term, license_type"
        rows = db.execute(
            f"SELECT {fields} FROM offers CROSS JOIN snapshot WHERE sku_key = ? LIMIT 2",
            (sku.strip().casefold(),),
        )
        return [Offer(*row) for row in rows]


def _product_card(offer: Offer, match_summary: str) -> ProductCard | None:
    try:
        url = HTTP_URL.validate_python(offer.url)
    except ValidationError:
        return None

    title = offer.title or offer.sku or f"Предложение {offer.offer_id}"
    source = Source(title=title, url=url)
    facts = []
    for field in FACT_LABELS:
        value = getattr(offer, field)
        if value is not None:
            facts.append(VerifiedFact(field=field, value=value, source=source))
    return ProductCard(
        offer_id=offer.offer_id,
        sku=offer.sku,
        title=title,
        url=url,
        verified_facts=facts,
        match_summary=match_summary,
        price_amount=Decimal(offer.price) if offer.price is not None else None,
        currency=offer.currency,
        availability=bool(offer.available) if offer.available is not None else None,
        snapshot_at=datetime.fromisoformat(offer.source_at),
    )


def _answer(text: str, cards: list[ProductCard]) -> TurnResult:
    return TurnResult(
        outcome="answer",
        text=text,
        products=cards,
        sources=[Source(title=card.title, url=card.url) for card in cards],
    )


def _sku_reply(index: Path, sku: str) -> TurnResult:
    matches = lookup_sku(index, sku)
    if not matches:
        return TurnResult(outcome="clarify", text=f"Артикул {sku} не найден в текущем снимке. Проверьте его написание.")
    if len(matches) > 1:
        return TurnResult(outcome="clarify", text=f"Для артикула {sku} найдено несколько предложений. Уточните редакцию или срок лицензии.")

    card = _product_card(matches[0], "Точное совпадение артикула в каталоге")
    if card is None:
        return TurnResult(outcome="clarify", text=f"Для артикула {sku} в каталоге нет проверяемой ссылки. Могу передать вопрос менеджеру.")
    return _answer(f"Нашёл карточку по артикулу {card.sku}. Данные о цене и наличии относятся к снимку каталога.", [card])


def _compare_offers(db: sqlite3.Connection, key: str) -> TurnResult:
    identities = db.execute(
        """SELECT DISTINCT group_id, CASE WHEN group_id IS NULL THEN offer_id END
           FROM offers WHERE title_key = ? OR family_key = ? LIMIT 2""",
        (key, key),
    ).fetchall()
    if len(identities) != 1:
        return TurnResult(outcome="clarify", text="Не удалось однозначно определить семейство. Укажите точное название редакции.")

    group_id, offer_id = identities[0]
    condition, value = ("group_id", group_id) if group_id else ("offer_id", offer_id)
    rows = db.execute(
        f"""SELECT {OFFER_FIELDS}, edition, term, license_type FROM offers CROSS JOIN snapshot
            WHERE {condition} = ? ORDER BY offer_id LIMIT ?""",
        (value, COMPARISON_LIMIT + 1),
    ).fetchall()
    cards = [
        card
        for row in rows[:COMPARISON_LIMIT]
        if (card := _product_card(Offer(*row), "Предложение из найденного семейства")) is not None
    ]
    if not cards:
        return TurnResult(outcome="clarify", text="У найденных предложений нет проверяемых ссылок. Могу передать вопрос менеджеру.")

    summary = ["Параметры предложений по данным каталога:"]
    for card in cards:
        facts = ", ".join(f"{FACT_LABELS[fact.field]}: {fact.value}" for fact in card.verified_facts)
        summary.append(f"• {card.title} — {facts or 'редакция и условия лицензии не указаны'}")
    if len(rows) > len(cards):
        summary.append("Показана часть предложений. Уточните редакцию или срок лицензии, чтобы сузить список.")
    return _answer("\n".join(summary), cards)


def _known_family_prefix(db: sqlite3.Connection, key: str) -> bool:
    words = key.split()
    prefixes = [" ".join(words[:count]) for count in range(1, len(words) + 1)]
    placeholders = ", ".join("?" for _ in prefixes)
    return db.execute(
        f"SELECT 1 FROM offers WHERE family_key IN ({placeholders}) LIMIT 1",
        prefixes,
    ).fetchone() is not None


def _named_product_reply(
    index: Path, name: str, *, compare: bool = False, explicit: bool = True
) -> TurnResult | None:
    key = _name_key(name)
    if key is None:
        return None
    with _open_catalog(index) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            if explicit:
                return TurnResult(outcome="clarify", text="Для поиска по названию нужно обновить снимок каталога. Если знаете артикул, пришлите его.")
            return None

        if compare:
            return _compare_offers(db, key)
        rows = db.execute(
            f"""SELECT {OFFER_FIELDS}, edition, term, license_type FROM offers CROSS JOIN snapshot
                WHERE title_key = ? LIMIT 2""",
            (key,),
        ).fetchall()
        if not rows and not explicit and not _known_family_prefix(db, key):
            return None
    if len(rows) != 1:
        return TurnResult(outcome="clarify", text=f"Не удалось подтвердить одно предложение с названием «{name}». Укажите точную редакцию или артикул.")
    card = _product_card(Offer(*rows[0]), "Точное совпадение названия в каталоге")
    if card is None:
        return TurnResult(outcome="clarify", text=f"Для «{name}» в каталоге нет проверяемой ссылки. Могу передать вопрос менеджеру.")
    return _answer(f"Нашёл «{card.title}» по точному названию в каталоге.", [card])


def catalog_reply(index: Path, text: str) -> TurnResult | None:
    text = text.strip()
    if request := SKU_REQUEST.fullmatch(text):
        return _sku_reply(index, request[1])
    if request := COMPARE_REQUEST.fullmatch(text):
        return _named_product_reply(index, request[1], compare=True)
    if request := PRODUCT_REQUEST.fullmatch(text):
        return _named_product_reply(
            index, request["name"], explicit=request["command"].casefold().startswith("найди")
        )
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local Softline catalog index")
    parser.add_argument("feed", type=Path)
    parser.add_argument("index", type=Path)
    parser.add_argument("--snapshot-at", help="ISO timestamp with a timezone for the catalog snapshot")
    args = parser.parse_args()
    try:
        snapshot = build_index(args.feed, args.index, source_at=args.snapshot_at)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(
        f"Offers: {snapshot.offer_count}; missing ID: {snapshot.missing_id_count}; "
        f"snapshot: {snapshot.source_at.isoformat()}; SHA-256: {snapshot.sha256}"
    )


if __name__ == "__main__":
    main()
