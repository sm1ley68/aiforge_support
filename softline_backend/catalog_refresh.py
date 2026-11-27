"""Refresh the live commerce index without exposing a partial SQLite file."""

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from fcntl import LOCK_EX, flock
import gzip
import logging
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import sleep

import httpx

from aisupport_ml.commerce.catalog import build_catalog
from .readiness import commerce_snapshot_at


FEED_URL = "https://store.softline.ru/feeds/Mindbox.yml.gz"
DAY_SECONDS = 86400
MAX_DOWNLOAD_BYTES = 1024 ** 3
MAX_EXPANDED_BYTES = 2 * 1024 ** 3
FEED_TIMEZONE = timezone(timedelta(hours=3))
logger = logging.getLogger(__name__)


def _write_bounded(destination: Path, chunks, limit: int):
    size = 0
    with destination.open("wb") as output:
        for chunk in chunks:
            size += len(chunk)
            if size > limit:
                raise ValueError("Feed exceeds the configured size limit")
            output.write(chunk)


def _xml_input(source: Path, temporary: Path) -> Path:
    with source.open("rb") as file:
        compressed = file.read(2) == b"\x1f\x8b"
    if not compressed:
        return source
    with gzip.open(source, "rb") as file:
        _write_bounded(temporary, iter(lambda: file.read(1024 * 1024), b""), MAX_EXPANDED_BYTES)
    return temporary


def _snapshot_time(value: str) -> datetime:
    date = datetime.fromisoformat(value)
    return date.replace(tzinfo=FEED_TIMEZONE) if date.tzinfo is None else date


def refresh(target: Path, *, source: Path | None = None) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("Use the live SQLite file path instead of a symlink")
    with target.with_suffix(target.suffix + ".lock").open("a") as lock:
        flock(lock, LOCK_EX)
        with TemporaryDirectory(prefix=".commerce-refresh-", dir=target.parent) as temporary:
            work = Path(temporary)
            if source is None:
                source = work / "feed"
                with httpx.stream("GET", FEED_URL, timeout=httpx.Timeout(30, connect=10), trust_env=False) as response:
                    response.raise_for_status()
                    _write_bounded(source, response.iter_bytes(), MAX_DOWNLOAD_BYTES)
            staged = work / "catalog.sqlite3"
            imported = build_catalog(_xml_input(source, work / "feed.xml"), staged)
            incoming_date = _snapshot_time(imported.snapshot_at)
            with closing(sqlite3.connect(f"{staged.absolute().as_uri()}?mode=ro", uri=True)) as db:
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("New catalog failed SQLite integrity check")
                if db.execute("SELECT count(*) FROM offers_fts").fetchone()[0] != imported.offers:
                    raise ValueError("New catalog is missing search entries")
            current = commerce_snapshot_at(target)
            if current is not None and incoming_date <= _snapshot_time(current):
                return False
            if target.is_file():
                staged.chmod(target.stat().st_mode & 0o777)
            else:
                staged.chmod(0o644)
            os.replace(staged, target)
            logger.info("catalog_snapshot_activated snapshot=%s offers=%d", imported.snapshot_at, imported.offers)
            return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=os.getenv("COMMERCE_CATALOG_INDEX_PATH") or None, required=not os.getenv("COMMERCE_CATALOG_INDEX_PATH"))
    parser.add_argument("--from-file", type=Path)
    parser.add_argument("--daily", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            changed = refresh(args.index, source=args.from_file)
            if not changed:
                logger.info("Catalog already has this snapshot or a newer one")
        except Exception:
            if not args.daily:
                raise
            logger.exception("Catalog refresh failed. Keeping the active snapshot.")
        if not args.daily:
            break
        sleep(DAY_SECONDS)


if __name__ == "__main__":
    main()
