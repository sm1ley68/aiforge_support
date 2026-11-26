"""Offline Softline feed import and indexed read-only lookup."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


_UNKNOWN = {"", "не определено", "другое или отсутствует"}
_FACETS = {
    "license_type": "Тип лицензии",
    "term": "Срок действия",
    "user_limit": "К-во пользователей до",
    "edition": "Версия",
    "platform": "Совместимая архитектура/платформа",
    "operating_system": "Операционная система",
}
_SCHEMA = """
CREATE TABLE catalog_meta (snapshot_at TEXT NOT NULL);
CREATE TABLE offers (
    offer_id TEXT PRIMARY KEY,
    vendor_code TEXT COLLATE NOCASE,
    group_id TEXT,
    category_id TEXT,
    title TEXT NOT NULL,
    vendor TEXT,
    url TEXT NOT NULL,
    price TEXT,
    currency TEXT,
    available INTEGER CHECK (available IN (0, 1)),
    license_type TEXT,
    term TEXT,
    user_limit INTEGER,
    edition TEXT,
    platform TEXT,
    operating_system TEXT,
    description TEXT NOT NULL
);
CREATE INDEX offers_vendor_code ON offers(vendor_code);
CREATE INDEX offers_group ON offers(group_id);
CREATE VIRTUAL TABLE offers_fts USING fts5(
    title, vendor, edition, description, content='offers', tokenize='unicode61'
);
"""


@dataclass(frozen=True)
class CatalogOffer:
    offer_id: str
    vendor_code: str | None
    group_id: str | None
    category_id: str | None
    title: str
    vendor: str | None
    url: str
    snapshot_at: str
    price: Decimal | None
    currency: str | None
    available: bool | None
    license_type: str | None
    term: str | None
    user_limit: int | None
    edition: str | None
    platform: str | None
    operating_system: str | None


@dataclass(frozen=True)
class CatalogImport:
    snapshot_at: str
    offers: int
    available: int


def _known(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned if cleaned.casefold() not in _UNKNOWN else None


def _positive_price(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return str(amount) if amount.is_finite() and amount > 0 else None


def _offer_values(element) -> tuple:
    offer_id = _known(element.get("id"))
    title = _known(element.findtext("name"))
    url = _known(element.findtext("url"))
    if not offer_id or not title or not url:
        raise ValueError("Feed offer is missing an ID, name, or source URL")

    parameters = {node.get("name"): _known(node.text) for node in element.iterchildren("param")}
    facets = {field: parameters.get(name) for field, name in _FACETS.items()}
    users = facets["user_limit"]
    user_limit = int(users) if users and re.fullmatch(r"[0-9]{1,9}", users) and int(users) > 0 else None
    currency = _known(element.findtext("currencyId"))
    available = {"true": 1, "false": 0}.get(element.get("available"))
    return (
        offer_id, _known(element.findtext("vendorCode")), _known(element.get("group_id")),
        _known(element.findtext("categoryId")), title, _known(element.findtext("vendor")), url,
        _positive_price(_known(element.findtext("price"))), "RUB" if currency == "RUR" else currency,
        available, facets["license_type"], facets["term"], user_limit, facets["edition"],
        facets["platform"], facets["operating_system"], (element.findtext("description") or "").strip(),
    )


def _index_feed(source: Path, destination: Path) -> CatalogImport:
    from lxml import etree

    snapshot_at = None
    offer_count = available_count = 0
    with closing(sqlite3.connect(destination)) as db, db:
        db.executescript(_SCHEMA)
        for event, element in etree.iterparse(
            str(source), events=("start", "end"), tag=("yml_catalog", "offer"),
            load_dtd=False, no_network=True, resolve_entities=False,
        ):
            if event == "start" and element.tag == "yml_catalog":
                snapshot_at = _known(element.get("date"))
            elif event == "end" and element.tag == "offer":
                values = _offer_values(element)
                db.execute("INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
                offer_count += 1
                available_count += element.get("available") == "true"
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]
        if not snapshot_at or not offer_count:
            raise ValueError("Feed must have a snapshot date and at least one offer")
        db.execute("INSERT INTO catalog_meta VALUES (?)", (snapshot_at,))
        db.execute("INSERT INTO offers_fts(offers_fts) VALUES ('rebuild')")
    return CatalogImport(snapshot_at, offer_count, available_count)


def build_catalog(source: Path, destination: Path) -> CatalogImport:
    """Write a new snapshot atomically, without replacing a previously built index."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".catalog-", dir=destination.parent, delete=False) as temporary:
        stage = Path(temporary.name)
    try:
        result = _index_feed(source, stage)
        os.link(stage, destination)
        return result
    finally:
        stage.unlink(missing_ok=True)


def _to_offer(row: sqlite3.Row) -> CatalogOffer:
    fields = dict(row)
    fields.pop("description")
    fields["price"] = Decimal(fields["price"]) if fields["price"] is not None else None
    fields["available"] = bool(fields["available"]) if fields["available"] is not None else None
    return CatalogOffer(**fields)


class SoftlineCatalog:
    def __init__(self, path: Path):
        self._uri = path.resolve().as_uri() + "?mode=ro"

    def _select(self, conditions: str, args: tuple) -> tuple[CatalogOffer, ...]:
        with closing(sqlite3.connect(self._uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT offers.*, catalog_meta.snapshot_at FROM offers CROSS JOIN catalog_meta " + conditions, args)
            return tuple(_to_offer(row) for row in rows)

    def by_reference(self, reference: str) -> tuple[CatalogOffer, ...]:
        """Prefer exact feed ID. An ambiguous vendor code can return multiple offers."""
        reference = reference.strip()
        exact = self._select("WHERE offer_id = ?", (reference,))
        return exact or self._select("WHERE vendor_code = ? ORDER BY offer_id", (reference,))

    def variants(self, group_id: str) -> tuple[CatalogOffer, ...]:
        return self._select("WHERE group_id = ? ORDER BY user_limit, offer_id", (group_id,))

    def has_title_phrase(self, phrase: str) -> bool:
        """Check a name hint against titles only, without resolving a SKU or edition."""
        terms = re.findall(r"[^\W_]+", phrase.casefold())
        if not 1 <= len(terms) <= 6:
            return False
        query = 'title : "' + " ".join(terms) + '"'
        with closing(sqlite3.connect(self._uri, uri=True)) as db:
            return db.execute("SELECT 1 FROM offers_fts WHERE offers_fts MATCH ? LIMIT 1", (query,)).fetchone() is not None

    def find_titles(self, title: str, *, users: int | None = None, limit: int = 12) -> tuple[CatalogOffer, ...]:
        """Search a literal product-name phrase, optionally for an exact seat count."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        terms = re.findall(r"[^\W_]+", title.casefold())
        if not 1 <= len(terms) <= 24:
            return ()
        query = 'title : "' + " ".join(terms) + '"'
        return self._select(
            "JOIN offers_fts ON offers_fts.rowid = offers.rowid WHERE offers_fts MATCH ? "
            "AND (? IS NULL OR user_limit = ?) "
            "ORDER BY (available IS NOT 1), bm25(offers_fts), offer_id LIMIT ?",
            (query, users, users, limit),
        )

    def search(self, query: str, *, available_only: bool = False, limit: int = 12) -> tuple[CatalogOffer, ...]:
        """Return lexical candidates. Search ranking doesn't establish compatibility."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        terms = tuple(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold())[:16]))
        if not terms:
            return ()
        expression = " AND ".join(f'"{term}"' for term in terms)
        return self._select(
            "JOIN offers_fts ON offers_fts.rowid = offers.rowid "
            "WHERE offers_fts MATCH ? AND (? = 0 OR available = 1) "
            "ORDER BY bm25(offers_fts, 8, 3, 3, 1), offer_id LIMIT ?",
            (expression, int(available_only), limit),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    result = build_catalog(args.feed, args.database)
    print(f"{result.snapshot_at}: {result.offers} offers, {result.available} available")


if __name__ == "__main__":
    main()
