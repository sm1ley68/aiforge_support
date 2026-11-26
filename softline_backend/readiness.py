import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from .catalog import EVIDENCE_SCHEMA_VERSION


ProviderStatus = Literal["deterministic", "configured"]
CatalogStatus = Literal["unconfigured", "ready", "unavailable", "incompatible"]


def catalog_status(index: Path | None) -> CatalogStatus:
    if index is None:
        return "unconfigured"
    try:
        with closing(sqlite3.connect(f"{index.absolute().as_uri()}?mode=ro", uri=True, timeout=1)) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != EVIDENCE_SCHEMA_VERSION:
                return "incompatible"
            if db.execute("SELECT source_at FROM snapshot LIMIT 1").fetchone() is None:
                return "incompatible"
            db.execute("SELECT offer_id, price_kopecks FROM offers LIMIT 0")
            db.execute("SELECT rowid FROM task_terms LIMIT 0")
            db.execute("SELECT offer_id, field, value, source_url, source_title FROM offer_evidence LIMIT 0")
    except (OSError, sqlite3.Error):
        return "unavailable"
    return "ready"
