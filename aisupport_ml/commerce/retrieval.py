from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import datetime
from difflib import SequenceMatcher
from hashlib import sha256
from math import log, sqrt
import re

from .contracts import KnowledgeUpdate, Source
from ..search import terms


_FAQ_FILLERS = {
    "а", "вы", "где", "же", "здравствуйте", "как", "мне", "можно", "пожалуйста", "подскажите", "привет", "скажите",
}


def normalize(text: str) -> str:
    return " ".join(terms(text))


def _context(source: Source) -> str:
    return " ".join((source.title, source.sku or "", *source.aliases, source.text))


def _article_id(source: Source) -> str:
    return "faq-" + sha256(f"{source.id}:{source.version}".encode()).hexdigest()[:16]


class KnowledgeBase:
    """Indexes authoritative sections and versioned, extractive FAQ entries."""

    def __init__(self, sources: Sequence[Source]):
        self.original = {source.id: source for source in sources}
        if len(self.original) != len(sources):
            raise ValueError("Duplicate knowledge source")
        self.generated: dict[str, tuple[Source, Source]] = {}
        self.drafts: dict[str, str] = {}

    def eligible(self, now: datetime, sku: str | None, customer_id: str | None):
        result = {}
        for source in self.original.values():
            if source.active(now, customer_id) and source.sku in (None, sku):
                result[source.id] = source
        for source, parent in self.generated.values():
            if result.get(parent.id) == parent:
                result[source.id] = source
        return result

    def search(self, query: str, now: datetime, sku=None, customer_id=None):
        eligible = self.eligible(now, sku, customer_id)
        ranked = lexical(query, tuple(eligible.values()))
        return expand_exceptions(ranked, eligible, limit=5)

    def direct(self, query, now, sku=None, customer_id=None):
        eligible = self.eligible(now, sku, customer_id)
        simplified = re.sub(r"^(?:подскажите|скажите|пожалуйста)\s+", "", normalize(query))
        matches = {
            self.prefer_article(source, eligible).id
            for source in eligible.values()
            if simplified in {normalize(text) for text in (source.title, *source.aliases)}
        }
        if len(matches) == 1:
            return expand_exceptions((eligible[source_id] for source_id in matches), eligible, limit=5)
        return ()

    def match_faq(self, query: str, now: datetime, sku: str | None = None, customer_id: str | None = None):
        """Return a single reviewed FAQ when its wording matches unambiguously."""
        if direct := self.direct(query, now, sku, customer_id):
            return direct
        words = set(terms(query)) - _FAQ_FILLERS
        if len(words) < 2:
            return ()
        eligible = self.eligible(now, sku, customer_id)
        ranked: dict[str, float] = {}
        for source in self.original.values():
            if source.id not in eligible or not source.reusable:
                continue
            for alias in source.aliases:
                alias_words = set(terms(alias)) - _FAQ_FILLERS
                overlap = words & alias_words
                if len(overlap) < 2 or words - alias_words:
                    continue
                score = 2 * len(overlap) / (len(words) + len(alias_words))
                if score >= 0.8:
                    match = self.prefer_article(source, eligible)
                    ranked[match.id] = max(score, ranked.get(match.id, 0.0))
        matches = sorted(ranked, key=ranked.__getitem__, reverse=True)
        if not matches or (len(matches) > 1 and ranked[matches[0]] - ranked[matches[1]] < 0.15):
            return ()
        return expand_exceptions((eligible[matches[0]],), eligible, limit=5)

    def prefer_article(self, source, eligible):
        for article, parent in self.generated.values():
            if parent == source and article.id in eligible:
                return article
        return source

    def restore_publications(self, publications: Iterable[tuple[str, str, str]], now: datetime) -> None:
        for article_id, source_id, version in publications:
            source = self.original.get(source_id)
            if source is not None and source.version == version and _article_id(source) == article_id:
                self.learn(source, now)

    def learn(self, source: Source, now: datetime, *, multi_source=False) -> KnowledgeUpdate:
        canonical = self.original.get(source.id)
        if canonical is None:
            generated = self.generated.get(source.id)
            if generated:
                _, parent = generated
                return KnowledgeUpdate("existing", source.id, parent.id, parent.version)
        article_id = _article_id(source)
        if article_id in self.generated:
            return KnowledgeUpdate("existing", article_id, source.id, source.version)
        # Reusable is a trusted property set when importing approved public material.
        # New FAQs copy verified facts verbatim and never use dialogue text.
        has_contact = re.search(r"[\w.+-]+@[\w.-]+\.[a-zа-я]{2,}|(?:\+?\d[ ()-]*){10,}", f"{source.title} {source.text} {source.aliases}", re.I)
        if (multi_source or canonical != source or not source.active(now) or not source.reusable
                or source.customer_id or source.exceptions or has_contact or not source.text.strip()):
            self.drafts[article_id] = source.id
            return KnowledgeUpdate("draft", article_id, source.id, source.version)
        article = replace(source, id=article_id, title=f"Частый вопрос: {source.title}", reusable=False)
        self.generated[article_id] = article, source
        self.drafts.pop(article_id, None)
        return KnowledgeUpdate("published", article_id, source.id, source.version)


def lexical(query: str, sources: Sequence[Source]) -> list[Source]:
    words = set(terms(query))
    documents = [Counter(terms(_context(source))) for source in sources]
    if not documents:
        return []
    frequencies = Counter(word for doc in documents for word in doc.keys() & words)
    avg_length = max(1, sum(doc.total() for doc in documents) / len(documents))
    scores = []
    for source, doc in zip(sources, documents):
        length_factor = 1.2 * (0.25 + 0.75 * doc.total() / avg_length)
        score = sum(
            log(1 + (len(documents) - frequencies[word] + 0.5) / (frequencies[word] + 0.5))
            * 2.2 * doc[word] / (doc[word] + length_factor)
            for word in sorted(doc.keys() & words)
        )
        if score:
            scores.append((score, source))
    return [source for _, source in sorted(scores, key=lambda row: (-row[0], row[1].id))]


def expand_exceptions(ranked, eligible, *, limit):
    selected = {}
    for source in ranked:
        group = {source.id: source}
        queue = [source]
        missing = False
        while queue:
            for exception in queue.pop().exceptions:
                if exception not in eligible:
                    missing = True
                elif exception not in group:
                    group[exception] = eligible[exception]
                    queue.append(eligible[exception])
        if not missing and len(selected.keys() | group.keys()) <= limit:
            selected.update(group)
    return tuple(selected.values())


def fuzzy_candidates(query: str, choices) -> list[str]:
    key = normalize(query)
    if not key:
        return []
    scored = []
    for sku, names in choices:
        aliases = [normalize(name) for name in names]
        score = max((SequenceMatcher(None, key, alias).ratio() for alias in aliases), default=0)
        if score >= 0.53:
            scored.append((score, sku))
    return [sku for _, sku in sorted(scored, key=lambda row: (-row[0], row[1]))[:5]]


def _cosine(one, two):
    denominator = sqrt(sum(x * x for x in one) * sum(y * y for y in two))
    return sum(x * y for x, y in zip(one, two, strict=True)) / denominator if denominator else 0.0


class HybridSearch:
    """Optional BM25 + embeddings with RRF and cross-encoder reranking."""

    def __init__(self, encode: Callable, rerank: Callable | None = None):
        self.encode = encode
        self.rerank = rerank
        self.documents: dict[str, Sequence[float]] = {}

    def __call__(self, query, eligible, *, limit=5):
        sources = tuple(eligible.values())
        if not sources:
            return ()
        contexts = {_context(source) for source in sources}
        missing = sorted(contexts - self.documents.keys())
        if missing:
            vectors = self.encode(missing, is_query=False)
            self.documents.update(zip(missing, vectors, strict=True))
        query_vector, = self.encode([query], is_query=True)
        dense = sorted(sources, key=lambda item: (-_cosine(query_vector, self.documents[_context(item)]), item.id))
        scores: dict[str, float] = {}
        for ranking in (lexical(query, sources)[:12], dense[:12]):
            for rank, source in enumerate(ranking, 1):
                scores[source.id] = scores.get(source.id, 0) + 1 / (60 + rank)
        ranked = sorted(scores, key=lambda source_id: (-scores[source_id], source_id))[:12]
        if self.rerank:
            values = self.rerank([(query, _context(eligible[source_id])) for source_id in ranked])
            ranked = [key for key, _ in sorted(zip(ranked, values, strict=True), key=lambda row: -row[1])]
        return expand_exceptions((eligible[key] for key in ranked), eligible, limit=limit)
