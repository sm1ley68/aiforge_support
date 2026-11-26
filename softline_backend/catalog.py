import argparse
import gzip
import json
import re
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import file_digest
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import DefusedXMLParser, iterparse
from defusedxml.common import DefusedXmlException
from .contracts import ProductCard, Source, TurnResult, VerifiedFact
from .knowledge import (
    KNOWLEDGE_FIELDS,
    OFFER_FACT_FIELDS,
    SUPPLEMENTAL_FIELDS,
    import_knowledge,
    insert_evidence,
    normalized_value,
    validated_url,
)


NAMED_SCHEMA_VERSION = 2
TASK_SCHEMA_VERSION = 3
EVIDENCE_SCHEMA_VERSION = 4
COMPARISON_LIMIT = 5
SCHEMA = f"""
PRAGMA user_version = {EVIDENCE_SCHEMA_VERSION};
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
    available INTEGER,
    description TEXT,
    deployment TEXT,
    user_limit INTEGER,
    origin TEXT,
    price_kopecks INTEGER
);
CREATE VIRTUAL TABLE task_terms USING fts5(
    name_terms, description_terms, content='', tokenize='unicode61'
);
CREATE INDEX offers_sku ON offers (sku_key);
CREATE INDEX offers_title ON offers (title_key);
CREATE INDEX offers_family ON offers (family_key);
CREATE INDEX offers_group ON offers (group_id, offer_id);
CREATE TABLE offer_evidence (
    offer_id TEXT NOT NULL REFERENCES offers (offer_id),
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_title TEXT NOT NULL,
    PRIMARY KEY (offer_id, field, value, source_url)
) WITHOUT ROWID;
CREATE INDEX offer_evidence_field ON offer_evidence (field, value, offer_id);
CREATE TEMP TABLE feed_field_conflicts (
    offer_id TEXT NOT NULL,
    field TEXT NOT NULL,
    PRIMARY KEY (offer_id, field)
) WITHOUT ROWID;
"""

SKU_REQUEST = re.compile(
    r"(?:найди(?:те)?\s+|покажи(?:те)?\s+)?(?:sku|артикул)(?:\s+[:№#]?\s*|\s*[:№#]\s*)"
    r"([\w][\w./+:-]{0,127})[?]?",
    re.IGNORECASE,
)
OFFER_ID_REQUEST = re.compile(r"id\s+предложения[\s:№#]+([\w][\w./+:-]{0,127})[?]?", re.IGNORECASE)
PRODUCT_REQUEST = re.compile(
    r"(?P<command>нужен|нужна|нужно|найди(?:те)? продукт)\s+(?P<name>.{1,240}?)\??",
    re.IGNORECASE,
)
COMPARE_REQUEST = re.compile(r"сравни(?:те)?\s+редакции\s+(.{1,240}?)\??", re.IGNORECASE)
COMPARE_ID_REQUEST = re.compile(
    r"сравни(?:те)?\s+(?:предложения|редакции)\s+по\s+id(?: предложения)?\s*[:№#]?\s*([\w./+:-]{1,128})\??",
    re.IGNORECASE,
)
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
    "срок действия": "term",
    "license type": "license_type",
    "тип лицензии": "license_type",
    "deployment": "deployment",
    "развертывание": "deployment",
    "тип развертывания": "deployment",
    "user limit": "user_limit",
    "количество пользователей": "user_limit",
    "максимум пользователей": "user_limit",
    "к-во пользователей до": "user_limit",
    "country of origin": "origin",
    "страна происхождения": "origin",
    "capability": "capability",
    "возможность": "capability",
    "license quantity": "license_quantity",
    "количество пользователей в лицензии": "license_quantity",
    "price basis": "price_basis",
    "единица цены": "price_basis",
}

FACT_LABELS = {"edition": "редакция", "term": "срок лицензии", "license_type": "тип лицензии"}
OFFER_FIELDS = "offer_id, sku, title, url, price, currency, available, source_at"


@dataclass(frozen=True)
class Snapshot:
    sha256: str
    source_at: datetime
    offer_count: int
    missing_id_count: int
    coverage: dict | None = None


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
    deployment: str | None = None
    user_limit: int | None = None
    origin: str | None = None
    evidence: tuple[VerifiedFact, ...] = ()


class MindboxXMLParser(DefusedXMLParser):
    def defused_start_doctype_decl(self, name, sysid, pubid, has_internal_subset):
        # Permit the standard Mindbox header; the parser still forbids entities and external references.
        if (name, sysid, pubid, has_internal_subset) != ("yml_catalog", "shops.dtd", None, False):
            super().defused_start_doctype_decl(name, sysid, pubid, has_internal_subset)


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
    code = currency.upper()
    return str(price), "RUB" if code == "RUR" else code


def _price_kopecks(price: str | None, currency: str | None) -> int | None:
    if price is None or currency != "RUB":
        return None
    rubles = Decimal(price)
    if rubles > Decimal("92233720368547758.07"):
        return None
    rounded = rubles.quantize(Decimal("0.01"))
    return int(rounded * 100) if rounded == rubles else None


def _offer_row(
    offer, offer_id: str, unmapped: Counter[str] | None
) -> tuple[tuple, list[str], dict[str, set[str]]]:
    fields = {}
    params: dict[str, set[str]] = {}
    for child in offer:
        tag = _tag(child)
        value = (" ".join(child.itertext()) if tag == "description" else child.text or "").strip()
        if not value:
            continue
        if tag == "param":
            name = " ".join(child.attrib.get("name", "").casefold().replace("ё", "е").split())
            key = PARAMETER_NAMES.get(name)
            if key:
                params.setdefault(key, set()).add(value)
            elif unmapped is not None and 0 < len(name) <= 120:
                unmapped[name] += 1
        else:
            fields.setdefault(tag, value)

    known = {}
    conflicts = []
    supplemental = {}
    for field, values in params.items():
        if field in KNOWLEDGE_FIELDS:
            values = {normalized_value(field, value) for value in values}
            if field == "capability":
                supplemental[field] = values - {None}
                continue
            if len(values) != 1 or None in values:
                conflicts.append(field)
                continue
        if len(values) == 1:
            value = next(iter(values))
            if field in SUPPLEMENTAL_FIELDS:
                supplemental[field] = {value}
            else:
                known[field] = value
    sku = fields.get("vendorCode") or known.get("sku")
    title = fields.get("name") or fields.get("model")
    group_ids = {offer.attrib.get("group_id", "").strip(), fields.get("group_id", "")} - {""}
    raw_available = offer.attrib.get("available", "").strip().casefold()
    available = {"true": 1, "false": 0, "1": 1, "0": 0}.get(raw_available)
    price, currency = _validated_price(fields.get("price"), fields.get("currencyId"))
    description = re.sub(r"<[^>]+>", " ", fields.get("description", ""))
    return (
        offer_id,
        sku,
        sku.casefold() if sku else None,
        next(iter(group_ids)) if len(group_ids) == 1 else None,
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
        description,
        known.get("deployment"),
        int(known["user_limit"]) if "user_limit" in known else None,
        known.get("origin"),
        _price_kopecks(price, currency),
    ), conflicts, supplemental


def _load_feed(
    db: sqlite3.Connection, source: Path, source_at: str | None, unmapped: Counter[str] | None
) -> Snapshot:
    with source.open("rb") as raw:
        digest = file_digest(raw, "sha256").hexdigest()
        raw.seek(0)
        compressed = raw.read(2) == b"\x1f\x8b"
        raw.seek(0)
        parsed = gzip.GzipFile(fileobj=raw) if compressed else raw
        with parsed:
            parser = MindboxXMLParser(forbid_dtd=True, forbid_entities=True, forbid_external=True)
            events = iterparse(parsed, events=("start", "end"), parser=parser)
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
                    row, conflicts, supplemental = _offer_row(element, offer_id, unmapped)
                    db.execute(
                        "INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )
                    if conflicts:
                        db.executemany(
                            "INSERT INTO feed_field_conflicts VALUES (?, ?)",
                            [(offer_id, field) for field in conflicts],
                        )
                    if supplemental:
                        title, url = row[4], validated_url(row[10])
                        if url is not None:
                            for field, values in supplemental.items():
                                for value in values:
                                    insert_evidence(db, offer_id, field, value, str(url), title or offer_id)
                    inserted += 1
                else:
                    skipped += 1
                stack[-1].remove(element)
    if not inserted:
        raise ValueError("The catalog contains no offers with IDs")
    db.execute(
        """INSERT INTO task_terms (rowid, name_terms, description_terms)
           SELECT rowid, replace(replace(title, 'ё', 'е'), 'Ё', 'Е'),
                  replace(replace(description, 'ё', 'е'), 'Ё', 'Е')
           FROM offers"""
    )
    return Snapshot(digest, timestamp, inserted, skipped)


def _coverage_counts(db: sqlite3.Connection) -> dict:
    columns = (
        "sku", "title", "family_key", "group_id", "price", "available", *OFFER_FACT_FIELDS,
    )
    conditions = (
        *(f"{name} IS NOT NULL" for name in columns),
        "price_kopecks IS NOT NULL",
        "available = 1",
        "description <> ''",
    )
    counts = db.execute(f"SELECT {', '.join(f'COUNT(NULLIF({condition}, 0))' for condition in conditions)} FROM offers")
    fields = (*columns, "rub_price", "in_stock", "description")
    result = dict(zip(fields, counts.fetchone()))
    result.update(dict.fromkeys((*SUPPLEMENTAL_FIELDS, "compatibility"), 0))
    result.update(db.execute(
        """SELECT field, COUNT(DISTINCT offer_id) FROM offer_evidence
           WHERE field IN ('capability', 'license_quantity', 'price_basis', 'compatibility')
           GROUP BY field"""
    ))
    result["verifiable_url"] = sum(
        validated_url(url) is not None for (url,) in db.execute("SELECT url FROM offers WHERE url IS NOT NULL")
    )
    result["ambiguous_sku_keys"] = db.execute(
        "SELECT COUNT(*) FROM (SELECT sku_key FROM offers WHERE sku_key IS NOT NULL GROUP BY sku_key HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    return result


def build_index(
    source: Path,
    destination: Path,
    *,
    source_at: str | None = None,
    knowledge: Path | None = None,
    coverage: bool = False,
) -> Snapshot:
    """Build and validate the index before replacing the catalog visible to workers."""
    if source.resolve() == destination.resolve():
        raise ValueError("The source feed and SQLite destination must differ")
    if knowledge is not None and knowledge.resolve() == destination.resolve():
        raise ValueError("The knowledge manifest and SQLite destination must differ")
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript(SCHEMA)
            unmapped = Counter() if coverage else None
            snapshot = _load_feed(db, source, source_at, unmapped)
            feed_counts = _coverage_counts(db) if coverage else None
            if knowledge is not None:
                import_knowledge(db, knowledge)
            if coverage:
                problem_counts = dict(db.execute("SELECT field, COUNT(*) FROM feed_field_conflicts GROUP BY field"))
                snapshot = replace(snapshot, coverage={
                    "offer_count": snapshot.offer_count,
                    "missing_id_count": snapshot.missing_id_count,
                    "source_at": snapshot.source_at.isoformat(),
                    "sha256": snapshot.sha256,
                    "feed": feed_counts,
                    "effective": _coverage_counts(db) if knowledge is not None else feed_counts,
                    "unusable_feed_fields": problem_counts,
                    "unmapped_parameter_names": dict(unmapped.most_common(50)),
                })
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


def _schema_version(db: sqlite3.Connection) -> int:
    return db.execute("PRAGMA user_version").fetchone()[0]


def _offer_columns(version: int) -> str:
    fields = OFFER_FIELDS
    if version >= NAMED_SCHEMA_VERSION:
        fields += ", edition, term, license_type"
    if version >= TASK_SCHEMA_VERSION:
        fields += ", deployment, user_limit, origin"
    return fields


def _offer_with_evidence(db: sqlite3.Connection, version: int, row) -> Offer:
    offer = Offer(*row)
    if version < EVIDENCE_SCHEMA_VERSION:
        return offer
    rows = db.execute(
        """SELECT field, value, source_url, source_title FROM offer_evidence
           WHERE offer_id = ? ORDER BY field, value, source_url""",
        (offer.offer_id,),
    )
    return replace(offer, evidence=tuple(
        VerifiedFact(field=field, value=value, source=Source(title=title, url=url))
        for field, value, url, title in rows
    ))


def lookup_sku(index: Path, sku: str) -> list[Offer]:
    with _open_catalog(index) as db:
        version = _schema_version(db)
        fields = _offer_columns(version)
        rows = db.execute(
            f"SELECT {fields} FROM offers CROSS JOIN snapshot WHERE sku_key = ? LIMIT 2",
            (sku.strip().casefold(),),
        )
        return [_offer_with_evidence(db, version, row) for row in rows]


def lookup_offer(index: Path, offer_id: str) -> Offer | None:
    with _open_catalog(index) as db:
        version = _schema_version(db)
        fields = _offer_columns(version)
        row = db.execute(
            f"SELECT {fields} FROM offers CROSS JOIN snapshot WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        return _offer_with_evidence(db, version, row) if row is not None else None


def product_card(offer: Offer, match_summary: str) -> ProductCard | None:
    url = validated_url(offer.url)
    if url is None:
        return None

    title = offer.title or offer.sku or f"Предложение {offer.offer_id}"
    source = Source(title=title, url=url)
    facts = list(offer.evidence)
    documented = {fact.field for fact in facts}
    for field in OFFER_FACT_FIELDS:
        value = getattr(offer, field)
        if value is not None and field not in documented:
            facts.append(VerifiedFact(field=field, value=str(value), source=source))
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


def find_task_cards(
    index: Path,
    expression: str,
    *,
    user_limit: int | None,
    deployment: str | None,
    budget_kopecks: int | None,
    origin: str | None,
) -> list[ProductCard] | None:
    with _open_catalog(index) as db:
        version = _schema_version(db)
        if version < TASK_SCHEMA_VERSION:
            return None
        predicates = ["task_terms MATCH ?", "available = 1", "url IS NOT NULL"]
        params: list[str | int] = [expression]
        filters = (
            ("user_limit >= ?", user_limit),
            ("deployment = ?", deployment),
            ("price_kopecks <= ?", budget_kopecks),
            ("origin = ?", origin),
        )
        for predicate, value in filters:
            if value is not None:
                predicates.append(predicate)
                params.append(value)
        rows = db.execute(
            f"""SELECT {OFFER_FIELDS}, edition, term, license_type, deployment, user_limit, origin, group_id
                FROM task_terms JOIN offers ON offers.rowid = task_terms.rowid CROSS JOIN snapshot
                WHERE {' AND '.join(predicates)}
                ORDER BY bm25(task_terms, 3.0, 1.0), offer_id""",
            params,
        )
        cards = []
        seen_groups = set()
        for *fields, group_id in rows:
            if group_id and group_id in seen_groups:
                continue
            offer = _offer_with_evidence(db, version, fields)
            card = product_card(offer, "Найдено по терминам задачи в каталоге")
            if card is None:
                continue
            cards.append(card)
            if len(cards) == 3:
                break
            if group_id:
                seen_groups.add(group_id)
        return cards


def find_verified_task_offers(
    index: Path,
    *,
    capabilities: tuple[str, ...],
    user_limit: int | None,
    deployment: str | None,
    origin: str | None,
) -> list[ProductCard] | None:
    """Return available offers with at least one of the requested explicit capabilities."""
    with _open_catalog(index) as db:
        version = _schema_version(db)
        if version < EVIDENCE_SCHEMA_VERSION:
            return None
        if not capabilities:
            return []
        placeholders = ", ".join("?" for _ in capabilities)
        predicates = ["available = 1", "url IS NOT NULL"]
        params: list[str | int] = list(capabilities)
        for field, value in (("user_limit", user_limit), ("deployment", deployment), ("origin", origin)):
            if value is not None:
                operator = ">=" if field == "user_limit" else "="
                predicates.append(f"{field} {operator} ?")
                params.append(value)
        rows = db.execute(
            f"""WITH eligible AS (
                    SELECT DISTINCT offers.offer_id, evidence.value AS capability, price_kopecks
                    FROM offer_evidence AS evidence JOIN offers ON offers.offer_id = evidence.offer_id
                    WHERE evidence.field = 'capability' AND evidence.value IN ({placeholders})
                    AND {' AND '.join(predicates)}
                ), ranked AS (
                    SELECT offer_id, ROW_NUMBER() OVER (
                        PARTITION BY capability ORDER BY price_kopecks IS NULL, price_kopecks, offer_id
                    ) AS rank
                    FROM eligible
                ), candidates AS (
                    SELECT offer_id AS candidate_id, MIN(rank) AS rank FROM ranked GROUP BY offer_id
                )
                SELECT {_offer_columns(version)} FROM candidates
                JOIN offers ON offers.offer_id = candidate_id CROSS JOIN snapshot
                ORDER BY rank, price_kopecks IS NULL, price_kopecks, offers.offer_id""",
            params,
        )
        cards = []
        for row in rows:
            offer = _offer_with_evidence(db, version, row)
            card = product_card(offer, "Подтверждённая возможность для задачи")
            if card is not None:
                cards.append(card)
            if len(cards) == 24:
                break
        return cards


def _answer(text: str, cards: list[ProductCard]) -> TurnResult:
    sources = {card.url: Source(title=card.title, url=card.url) for card in cards}
    for card in cards:
        for fact in card.verified_facts:
            sources.setdefault(fact.source.url, fact.source)
    return TurnResult(
        outcome="answer",
        text=text,
        products=cards,
        sources=list(sources.values()),
    )


def _sku_reply(index: Path, sku: str) -> TurnResult:
    matches = lookup_sku(index, sku)
    if not matches:
        return TurnResult(outcome="clarify", text=f"Артикул {sku} не найден в текущем снимке. Проверьте его написание.")
    if len(matches) > 1:
        return TurnResult(outcome="clarify", text=f"Для артикула {sku} найдено несколько предложений. Уточните редакцию или срок лицензии.")

    card = product_card(matches[0], "Точное совпадение артикула в каталоге")
    if card is None:
        return TurnResult(outcome="clarify", text=f"Для артикула {sku} в каталоге нет проверяемой ссылки. Могу передать вопрос менеджеру.")
    return _answer(f"Нашёл карточку по артикулу {card.sku}. Данные о цене и наличии относятся к снимку каталога.", [card])


def _offer_id_reply(index: Path, offer_id: str) -> TurnResult:
    offer = lookup_offer(index, offer_id)
    if offer is None:
        return TurnResult(outcome="clarify", text=f"Предложение {offer_id} не найдено в текущем снимке. Проверьте его ID.")
    card = product_card(offer, "Точное совпадение ID предложения в каталоге")
    if card is None:
        return TurnResult(outcome="clarify", text=f"Для предложения {offer_id} в каталоге нет проверяемой ссылки.")
    return _answer(f"Нашёл карточку предложения {offer_id}. Данные о цене и наличии относятся к снимку каталога.", [card])


def _compare_offers(db: sqlite3.Connection, key: str) -> TurnResult:
    identities = db.execute(
        """SELECT DISTINCT group_id, CASE WHEN group_id IS NULL THEN offer_id END
           FROM offers WHERE title_key = ? OR family_key = ? LIMIT 2""",
        (key, key),
    ).fetchall()
    if len(identities) != 1:
        return TurnResult(outcome="clarify", text="Не удалось однозначно определить семейство. Укажите точное название редакции.")

    group_id, offer_id = identities[0]
    return _group_comparison(db, group_id, offer_id)


def _group_comparison(
    db: sqlite3.Connection, group_id: str | None, offer_id: str | None, *, preferred: str | None = None
) -> TurnResult:
    condition, value = ("group_id", group_id) if group_id else ("offer_id", offer_id)
    version = _schema_version(db)
    fields = _offer_columns(version) if version >= EVIDENCE_SCHEMA_VERSION else f"{OFFER_FIELDS}, edition, term, license_type"
    rows = db.execute(
        f"""SELECT {fields} FROM offers CROSS JOIN snapshot
            WHERE {condition} = ? ORDER BY (offer_id = ?) DESC, offer_id LIMIT ?""",
        (value, preferred, COMPARISON_LIMIT + 1),
    ).fetchall()
    cards = [
        card
        for row in rows[:COMPARISON_LIMIT]
        if (card := product_card(
            _offer_with_evidence(db, version, row), "Предложение из найденного семейства"
        )) is not None
    ]
    if not cards:
        return TurnResult(outcome="clarify", text="У найденных предложений нет проверяемых ссылок. Могу передать вопрос менеджеру.")

    summary = ["Параметры предложений по данным каталога"]
    labels = FACT_LABELS | {"user_limit": "лимит пользователей"}
    for card in cards:
        values = {fact.field: fact.value for fact in card.verified_facts if fact.field in labels}
        facts = ", ".join(f"{labels[field]} — {value}" for field, value in values.items())
        summary.append(f"• {card.title} — {facts or 'редакция и условия лицензии не указаны'}")
    if len(rows) > len(cards):
        summary.append("Показана часть предложений. Уточните редакцию или срок лицензии, чтобы сузить список.")
    return _answer("\n".join(summary), cards)


def _compare_by_offer_id(index: Path, offer_id: str) -> TurnResult:
    with _open_catalog(index) as db:
        if _schema_version(db) < NAMED_SCHEMA_VERSION:
            return TurnResult(outcome="clarify", text="Для сравнения предложений нужно обновить снимок каталога.")
        row = db.execute("SELECT group_id FROM offers WHERE offer_id = ?", (offer_id,)).fetchone()
        if row is None:
            return TurnResult(outcome="clarify", text=f"Предложение {offer_id} не найдено в текущем снимке.")
        return _group_comparison(db, row[0], offer_id, preferred=offer_id)


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
        version = _schema_version(db)
        if version < NAMED_SCHEMA_VERSION:
            if explicit:
                return TurnResult(outcome="clarify", text="Для поиска по названию нужно обновить снимок каталога. Если знаете артикул, пришлите его.")
            return None

        if compare:
            return _compare_offers(db, key)
        fields = _offer_columns(version) if version >= EVIDENCE_SCHEMA_VERSION else f"{OFFER_FIELDS}, edition, term, license_type"
        rows = db.execute(
            f"""SELECT {fields} FROM offers CROSS JOIN snapshot
                WHERE title_key = ? LIMIT 2""",
            (key,),
        ).fetchall()
        if not rows and not explicit and not _known_family_prefix(db, key):
            return None
        if len(rows) != 1:
            return TurnResult(outcome="clarify", text=f"Не удалось подтвердить одно предложение с названием «{name}». Укажите точную редакцию или артикул.")
        offer = _offer_with_evidence(db, version, rows[0])
    card = product_card(offer, "Точное совпадение названия в каталоге")
    if card is None:
        return TurnResult(outcome="clarify", text=f"Для «{name}» в каталоге нет проверяемой ссылки. Могу передать вопрос менеджеру.")
    return _answer(f"Нашёл «{card.title}» по точному названию в каталоге.", [card])


def catalog_reply(index: Path, text: str) -> TurnResult | None:
    text = text.strip()
    if request := SKU_REQUEST.fullmatch(text):
        return _sku_reply(index, request[1])
    if request := OFFER_ID_REQUEST.fullmatch(text):
        return _offer_id_reply(index, request[1])
    if request := COMPARE_ID_REQUEST.fullmatch(text):
        return _compare_by_offer_id(index, request[1])
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
    parser.add_argument("--knowledge", type=Path, help="Reviewed local JSON or JSONL evidence manifest")
    parser.add_argument("--coverage", action="store_true", help="Print JSON coverage of the feed and resulting index")
    args = parser.parse_args()
    try:
        snapshot = build_index(
            args.feed, args.index, source_at=args.snapshot_at, knowledge=args.knowledge, coverage=args.coverage
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    if snapshot.coverage is not None:
        print(json.dumps(snapshot.coverage, ensure_ascii=False, sort_keys=True))
        return
    print(
        f"Offers: {snapshot.offer_count}; missing ID: {snapshot.missing_id_count}; "
        f"snapshot: {snapshot.source_at.isoformat()}; SHA-256: {snapshot.sha256}"
    )


if __name__ == "__main__":
    main()
