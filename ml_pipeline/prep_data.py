from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from zipfile import ZipFile


ROUTES = (
    "find_named_product",
    "recommend_by_need",
    "answer_product_question",
    "handoff",
    "clarify",
)

_RECORD = re.compile(r"^#(\d+)\s*\[([^\]]+)\]\s*(.*)$")
_PAGE = re.compile(r"^\[(?:https?://)?store\.softline\.ru[^\]]*\]\s*", re.I)
_GREETING = re.compile(r"^(?:(?:добрый (?:день|вечер)|доброе утро|здравствуйте|привет)\b[\s,!.:-]*)+", re.I)
_LATER_GREETING = re.compile(r"\b(?:добрый (?:день|вечер)|доброе утро|здравствуйте)\b", re.I)
_CONTACT = re.compile(
    r"\b[\w.+-]+@[\w.-]+\.[a-zа-я]{2,}\b|\[(?:email|phone|url|name)\]|"
    r"(?:https?://|www\.)\S+|(?<!\d)(?:\+?\d[ .()/-]*){10,}(?!\d)",
    re.I,
)
_OPERATOR_MARKER = re.compile(r"\b(?:оператор|консультант|менеджер|клиент)\s*:", re.I)
_FORBIDDEN_PRIVATE_TOKEN = re.compile(r"\b(?:инн|кпп|огрн|номер заказа)\s*[:№]?[\s-]*\d", re.I)
_PRIVATE_CONTEXT = re.compile(r"(?:\bменя зовут\b|^[а-яё]+ [а-яё]+:|\b(?:ооо|ип)\s+[«\"])", re.I)


@dataclass(frozen=True)
class Candidate:
    archive_position: int
    record_id: str
    topic: str
    text: str


def collect_candidates(source: Path) -> tuple[list[Candidate], Counter]:
    """Collect short first questions for review. A candidate is not an approved client message."""
    candidates: list[Candidate] = []
    counts: Counter = Counter()
    ids = set()
    with ZipFile(source) as archive:
        names = sorted(name for name in archive.namelist() if name.endswith(".txt"))
        for name in names:
            for line in archive.read(name).decode("utf-8-sig").splitlines():
                if not line.strip():
                    continue
                counts["archive_records"] += 1
                match = _RECORD.fullmatch(line.strip())
                if not match:
                    raise ValueError(f"Unrecognized record at archive position {counts['archive_records']}")
                record_id, topic, body = match.groups()
                if record_id in ids:
                    counts["duplicate_record"] += 1
                    continue
                ids.add(record_id)
                without_page, removed = _PAGE.subn("", body)
                if not removed:
                    counts["missing_page_header"] += 1
                    continue
                first_question, delimiter, _ = without_page.partition("?")
                text = _GREETING.sub("", " ".join(first_question.split())).strip()
                if not delimiter or not 4 <= len(text) <= 235:
                    counts["unclear_question_boundary"] += 1
                    continue
                matches_private = _CONTACT.search(text) or _FORBIDDEN_PRIVATE_TOKEN.search(text) or _PRIVATE_CONTEXT.search(text)
                if matches_private or _OPERATOR_MARKER.search(text) or _LATER_GREETING.search(text):
                    counts["sensitive_or_marked"] += 1
                    continue
                if not re.search(r"[а-яёa-z]", text, re.I):
                    counts["non_text"] += 1
                    continue
                candidates.append(Candidate(counts["archive_records"], record_id, topic, text + "?"))
    counts["candidates"] = len(candidates)
    return candidates, counts


def normalize_route_text(text: str) -> str:
    """Shared text normalization. Keep product spellings, hyphens, and version digits."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().replace("ё", "е").split())


def _comparison_text(text: str) -> str:
    return " ".join(re.findall(r"[\w]+", normalize_route_text(text)))


def checked_archive_rows(archive_path: Path, decisions_path: Path, candidates: list[Candidate]):
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != decisions["archive_sha256"]:
        raise ValueError("Review positions refer to another archive snapshot")
    by_position = {item.archive_position: item for item in candidates}
    selected = {}
    for route in ROUTES:
        for position in decisions["routes"][route]:
            if position in selected or position not in by_position:
                raise ValueError(f"Invalid reviewed archive position {position}")
            selected[position] = route
    comparisons: list[str] = []
    rows = []
    duplicates = 0
    for position, route in sorted(selected.items()):
        candidate = by_position[position]
        comparison = _comparison_text(candidate.text)
        if any(SequenceMatcher(a=other, b=comparison, autojunk=False).ratio() >= 0.92 for other in comparisons):
            duplicates += 1
            continue
        comparisons.append(comparison)
        rows.append({"group_id": f"archive-{candidate.archive_position:03}", "origin": "archive_prefix",
                     "text": candidate.text, "route": route})
    return rows, duplicates


def synthetic_train_rows(path: Path):
    rows = []
    inputs = json.loads(path.read_text(encoding="utf-8"))
    known_text = set()
    for route, messages in inputs.items():
        if route not in ROUTES:
            raise ValueError("Unrecognized synthetic route")
        for index, message in enumerate(messages, 1):
            text = _comparison_text(message)
            if not text or text in known_text:
                raise ValueError("Bad or duplicate synthetic text")
            known_text.add(text)
            rows.append({"group_id": f"synthetic-{route}-{index:03}", "origin": "synthetic",
                         "text": message, "route": route})
    return rows


def make_text_features():
    """Build an unfitted transformer for a route's text, with no metadata columns."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion

    return FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), preprocessor=normalize_route_text, sublinear_tf=True)),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                  preprocessor=normalize_route_text, sublinear_tf=True)),
    ])
