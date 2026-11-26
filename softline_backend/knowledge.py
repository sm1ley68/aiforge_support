import json
import re
import sqlite3
from pathlib import Path

from pydantic import HttpUrl, TypeAdapter, ValidationError

from .task_vocabulary import CAPABILITY_LABELS


OFFER_FACT_FIELDS = ("edition", "term", "license_type", "deployment", "user_limit", "origin")
SUPPLEMENTAL_FIELDS = ("license_quantity", "price_basis", "capability")
KNOWLEDGE_FIELDS = (*OFFER_FACT_FIELDS, *SUPPLEMENTAL_FIELDS, "compatibility")
HTTP_URL = TypeAdapter(HttpUrl)
NAMED_CAPABILITIES = {label.casefold(): name for name, label in CAPABILITY_LABELS.items()}
DEPLOYMENTS = {
    "on-premise": "локально",
    "on-premises": "локально",
    "on-prem": "локально",
    "локально": "локально",
    "локальное": "локально",
    "cloud": "облако",
    "облако": "облако",
    "облачное": "облако",
}
RUSSIAN_ORIGINS = {"ru", "rus", "russia", "russian federation", "рф", "россия", "российская федерация"}
EVIDENCE_FIELDS = {"scope", "field", "value", "source_url", "source_title"}


def normalized_value(field: str, value: str) -> str | None:
    value = " ".join(value.split())
    if not value:
        return None
    key = value.casefold()
    if field in ("user_limit", "license_quantity"):
        return value if re.fullmatch(r"[1-9][0-9]{0,6}", value) else None
    if field == "deployment":
        return DEPLOYMENTS.get(key)
    if field == "origin" and key in RUSSIAN_ORIGINS:
        return "Россия"
    if field == "price_basis":
        return "license_pack" if key in {"license_pack", "за лицензионный пакет"} else None
    if field == "capability":
        return key if key in CAPABILITY_LABELS else NAMED_CAPABILITIES.get(key)
    return value


def validated_url(value: str | None) -> HttpUrl | None:
    if not value or not value.lower().startswith(("https://", "http://")):
        return None
    try:
        url = HTTP_URL.validate_python(value)
    except ValidationError:
        return None
    return url if url.username is None and url.password is None else None


def insert_evidence(db: sqlite3.Connection, offer_id: str, field: str, value: str, url: str, title: str) -> None:
    db.execute(
        """INSERT INTO offer_evidence (offer_id, field, value, source_url, source_title)
           VALUES (?, ?, ?, ?, ?) ON CONFLICT (offer_id, field, value, source_url) DO NOTHING""",
        (offer_id, field, value, url, title),
    )


def _required_text(row: dict, key: str, limit: int) -> str:
    value = row[key]
    if isinstance(value, str) and value.strip() and len(value) <= limit and "\x00" not in value:
        return value.strip()
    raise ValueError(f"{key} must be a nonempty string up to {limit} characters")


def _record_identity(db: sqlite3.Connection, row: dict) -> str:
    scope = row.get("scope")
    if scope == "offer":
        field, column = "offer_id", "offer_id"
    elif scope == "sku":
        field, column = "sku", "sku_key"
    else:
        raise ValueError("scope must be 'offer' or 'sku'")
    if row.keys() != EVIDENCE_FIELDS | {field}:
        raise ValueError(f"{scope} scope requires {field} and the evidence fields only")
    identity = _required_text(row, field, 512)
    if field == "sku":
        identity = identity.casefold()
    matches = db.execute(f"SELECT offer_id FROM offers WHERE {column} = ? LIMIT 2", (identity,)).fetchall()
    if not matches:
        raise ValueError(f"{scope} was not found in the feed")
    if len(matches) > 1:
        raise ValueError(f"{scope} is ambiguous in the feed")
    return matches[0][0]


def _offer_value(db: sqlite3.Connection, offer_id: str, field: str) -> str | int | None:
    if field in OFFER_FACT_FIELDS:
        return db.execute(f"SELECT {field} FROM offers WHERE offer_id = ?", (offer_id,)).fetchone()[0]
    result = db.execute(
        "SELECT value FROM offer_evidence WHERE offer_id = ? AND field = ? LIMIT 1", (offer_id, field)
    ).fetchone()
    return result[0] if result else None


def _import_record(db: sqlite3.Connection, row: object) -> None:
    if not isinstance(row, dict):
        raise ValueError("expected an evidence object")
    offer_id = _record_identity(db, row)
    field = _required_text(row, "field", 32)
    if field not in KNOWLEDGE_FIELDS:
        raise ValueError("unsupported evidence field")
    raw_value = row["value"]
    if field in ("user_limit", "license_quantity") and type(raw_value) is int:
        if not 1 <= raw_value <= 9_999_999:
            raise ValueError(f"invalid value for {field}")
        raw_value = str(raw_value)
    if not isinstance(raw_value, str) or len(raw_value) > 1000 or "\x00" in raw_value:
        raise ValueError(f"invalid value for {field}")
    value = normalized_value(field, raw_value)
    if value is None:
        raise ValueError(f"invalid value for {field}")
    title = _required_text(row, "source_title", 300)
    url = validated_url(_required_text(row, "source_url", 2083))
    if url is None:
        raise ValueError("source_url must be an absolute HTTP(S) URL without credentials")

    if field != "capability":
        feed_conflict = db.execute(
            "SELECT 1 FROM feed_field_conflicts WHERE offer_id = ? AND field = ?", (offer_id, field)
        ).fetchone()
        current = _offer_value(db, offer_id, field)
        if feed_conflict or (current is not None and str(current).casefold() != value.casefold()):
            raise ValueError(f"conflicting evidence for {field}")
        if current is not None:
            value = str(current)

    if field in OFFER_FACT_FIELDS:
        db.execute(f"UPDATE offers SET {field} = ? WHERE offer_id = ?", (value, offer_id))
    insert_evidence(db, offer_id, field, value, str(url), title)


def _unique_json_object(pairs: list[tuple]) -> dict:
    record = dict(pairs)
    if len(record) != len(pairs):
        raise ValueError("duplicate keys in evidence object")
    return record


def _manifest_rows(path: Path):
    with path.open(encoding="utf-8-sig") as stream:
        if path.suffix.lower() == ".jsonl":
            for number, line in enumerate(stream, start=1):
                if line.strip():
                    try:
                        yield number, json.loads(line, object_pairs_hook=_unique_json_object)
                    except ValueError as exc:
                        raise ValueError(f"Knowledge manifest line {number}: invalid JSON") from exc
        else:
            try:
                rows = json.load(stream, object_pairs_hook=_unique_json_object)
            except ValueError as exc:
                raise ValueError("Knowledge manifest: invalid JSON") from exc
            if not isinstance(rows, list):
                raise ValueError("Knowledge manifest JSON must contain an array of evidence records")
            yield from enumerate(rows, start=1)


def import_knowledge(db: sqlite3.Connection, path: Path) -> None:
    location = "line" if path.suffix.lower() == ".jsonl" else "record"
    try:
        for number, row in _manifest_rows(path):
            try:
                _import_record(db, row)
            except ValueError as exc:
                raise ValueError(f"Knowledge manifest {location} {number}: {exc}") from exc
    except UnicodeError as exc:
        raise ValueError("Knowledge manifest must use UTF-8") from exc
