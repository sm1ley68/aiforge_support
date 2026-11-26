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

from .contracts import ProductCard, Source, TurnResult


SCHEMA = """
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
    url TEXT,
    price TEXT,
    currency TEXT,
    available INTEGER
);
CREATE INDEX offers_sku ON offers (sku_key);
"""

SKU_REQUEST = re.compile(
    r"(?:найди(?:те)?\s+|покажи(?:те)?\s+)?(?:sku|артикул)(?:\s+[:№#]?\s*|\s*[:№#]\s*)"
    r"([\w][\w./+:-]{0,127})[?]?",
    re.IGNORECASE,
)
HTTP_URL = TypeAdapter(HttpUrl)


@dataclass(frozen=True)
class Snapshot:
    sha256: str
    source_at: datetime
    offer_count: int
    missing_id_count: int


@dataclass(frozen=True)
class Offer:
    offer_id: str
    sku: str
    title: str | None
    url: str | None
    price: str | None
    currency: str | None
    available: int | None
    source_at: str


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
    named_sku = None
    for child in offer:
        tag = _tag(child)
        value = (child.text or "").strip()
        if not value:
            continue
        if tag == "param" and child.attrib.get("name", "").strip().casefold() in {"sku", "артикул", "vendorcode"}:
            named_sku = named_sku or value
        elif tag != "param":
            fields.setdefault(tag, value)

    sku = fields.get("vendorCode") or named_sku
    raw_available = offer.attrib.get("available", "").strip().casefold()
    available = {"true": 1, "false": 0, "1": 1, "0": 0}.get(raw_available)
    price, currency = _validated_price(fields.get("price"), fields.get("currencyId"))
    return (
        offer_id,
        sku,
        sku.casefold() if sku else None,
        offer.attrib.get("group_id"),
        fields.get("name") or fields.get("model"),
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
                    db.execute("INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", _offer_row(element, offer_id))
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


def lookup_sku(index: Path, sku: str) -> list[Offer]:
    uri = f"{index.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute(
            """SELECT offer_id, sku, title, url, price, currency, available, source_at
               FROM offers CROSS JOIN snapshot
               WHERE sku_key = ? LIMIT 2""",
            (sku.strip().casefold(),),
        )
        return [Offer(*row) for row in rows]


def catalog_reply(index: Path, text: str) -> TurnResult | None:
    request = SKU_REQUEST.fullmatch(text.strip())
    if request is None:
        return None

    sku = request[1]
    matches = lookup_sku(index, sku)
    if not matches:
        return TurnResult(outcome="clarify", text=f"Артикул {sku} не найден в текущем снимке. Проверьте его написание.")
    if len(matches) > 1:
        return TurnResult(outcome="clarify", text=f"Для артикула {sku} найдено несколько предложений. Уточните редакцию или срок лицензии.")

    offer = matches[0]
    try:
        url = HTTP_URL.validate_python(offer.url)
    except ValidationError:
        return TurnResult(outcome="clarify", text=f"Для артикула {sku} в каталоге нет проверяемой ссылки. Могу передать вопрос менеджеру.")

    card = ProductCard(
        offer_id=offer.offer_id,
        sku=offer.sku,
        title=offer.title or offer.sku,
        url=url,
        match_summary="Точное совпадение артикула в каталоге",
        price_amount=Decimal(offer.price) if offer.price is not None else None,
        currency=offer.currency,
        availability=bool(offer.available) if offer.available is not None else None,
        snapshot_at=datetime.fromisoformat(offer.source_at),
    )
    return TurnResult(
        outcome="answer",
        text=f"Нашёл карточку по артикулу {offer.sku}. Данные о цене и наличии относятся к снимку каталога.",
        products=[card],
        sources=[Source(title=card.title, url=card.url)],
    )


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
