import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from math import log
from urllib.parse import quote

from .contracts import Evidence, Order, Ticket


def terms(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold().replace("ё", "е"))


@dataclass(frozen=True)
class PolicySection:
    tenant_id: str
    document_id: str
    section_id: str
    version: str
    title: str
    text: str
    url: str
    valid_from: datetime
    valid_until: datetime | None = None
    region: str | None = None
    product: str | None = None
    required_grant: str | None = None
    # References are (document_id, section_id, version).
    exceptions: tuple[tuple[str, str, str], ...] = ()

    @property
    def key(self) -> tuple[str, str, str]:
        return self.document_id, self.section_id, self.version


class PolicyIndex:
    """Small in-memory full-text index for authorized policy excerpts."""

    def __init__(self, sections: tuple[PolicySection, ...]):
        keys = {(section.tenant_id, section.key) for section in sections}
        if len(keys) != len(sections):
            raise ValueError("Duplicate policy section")
        self.documents = tuple(
            (section, Counter(terms(f"{section.title} {section.title} {section.text}")))
            for section in sections
        )

    def search(
        self, ticket: Ticket, order: Order, query: str, *,
        now: datetime, grants: frozenset[str], limit: int = 5,
    ) -> tuple[Evidence, ...]:
        if not 1 <= limit <= 5:
            raise ValueError("limit must be between 1 and 5")
        eligible = {
            section.key: (section, counts)
            for section, counts in self.documents
            if section.tenant_id == ticket.tenant_id
            and section.valid_from <= now
            and (section.valid_until is None or now < section.valid_until)
            and section.region in (None, order.region)
            and section.product in (None, order.product)
            and (section.required_grant is None or section.required_grant in grants)
        }
        query_terms = set(terms(query))
        frequency = Counter(word for _, counts in eligible.values() for word in counts.keys() & query_terms)
        scored = []
        for key, (section, counts) in eligible.items():
            exact = query.strip().casefold() in {
                section.document_id.casefold(), f"{section.document_id}#{section.section_id}".casefold()
            }
            score = sum(
                (1 + log(counts[word])) * log(1 + len(eligible) / frequency[word])
                for word in sorted(counts.keys() & query_terms)
            )
            if exact or score:
                scored.append((not exact, -score, key))
        selected = {}
        for _, _, key in sorted(scored):
            group = {key: None}
            queue = [key]
            while queue:
                for related in eligible[queue.pop()][0].exceptions:
                    if related in eligible and related not in group:
                        group[related] = None
                        queue.append(related)
            if len(selected.keys() | group.keys()) <= limit:
                selected.update(group)
        return tuple(
            Evidence(
                id="kb:" + ":".join(quote(part, safe="") for part in key),
                source="kb", record_id=f"{key[0]}#{key[1]}",
                label=eligible[key][0].title, observed_at=now, url=eligible[key][0].url,
                excerpt=eligible[key][0].text[:480], version=key[2],
            )
            for key in selected
        )
