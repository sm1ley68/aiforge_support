import re
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from pathlib import Path

from . import catalog
from .contracts import ProductCard, Source, TurnResult
from .task_vocabulary import CAPABILITY_LABELS, Capability


LICENSE_TERM = re.compile(
    r"(?:[1-9]\d{0,3}\s*(?:д(?:ень|ня|ней)|мес(?:яц(?:а|ев)?|\.?)|год(?:а|ов)?|лет)"
    r"|бессрочн(?:о|ая|ый|ое))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskRequest:
    query: str
    user_limit: int | None = None
    deployment: str | None = None
    budget_kopecks: int | None = None
    origin: str | None = None
    capabilities: tuple[Capability, ...] = ()


def _fact(card: ProductCard, field: str) -> str | None:
    return next((fact.value for fact in card.verified_facts if fact.field == field), None)


def _license_quantity(card: ProductCard) -> int | None:
    value = _fact(card, "license_quantity")
    return int(value) if value and value.isascii() and value.isdecimal() and len(value) <= 7 else None


def _license_term(card: ProductCard) -> str | None:
    term = _fact(card, "term")
    return term if term and LICENSE_TERM.fullmatch(term) else None


def _pack_price(card: ProductCard) -> int | None:
    amount = card.price_amount
    if (
        _fact(card, "price_basis") != "license_pack"
        or not _license_quantity(card)
        or card.currency != "RUB"
        or amount is None
        or not amount.is_finite()
        or not 0 <= amount <= Decimal("92233720368547758.07")
        or amount.quantize(Decimal("0.01")) != amount
    ):
        return None
    return int(amount * 100)


def _rubles(kopecks: int) -> str:
    rubles, rest = divmod(kopecks, 100)
    result = f"{rubles:,}".replace(",", " ")
    return f"{result},{rest:02} ₽" if rest else f"{result} ₽"


def catalog_sources(cards: list[ProductCard], requested_fields: set[str]) -> list[Source]:
    sources = {card.url: Source(title=card.title, url=card.url) for card in cards}
    for card in cards:
        for fact in card.verified_facts:
            if fact.field in requested_fields:
                sources.setdefault(fact.source.url, fact.source)
    return list(sources.values())


def request_fields(request: TaskRequest) -> set[str]:
    return {field for field in ("deployment", "origin", "user_limit") if getattr(request, field) is not None}


def _verified_result(
    request: TaskRequest,
    cards: list[ProductCard],
    total_kopecks: int | None,
) -> TurnResult:
    products = []
    fields = request_fields(request) | {"capability"}
    for card in cards:
        confirmed = ", ".join(
            CAPABILITY_LABELS[capability] for capability in request.capabilities
            if any(fact.field == "capability" and fact.value == capability for fact in card.verified_facts)
        )
        products.append(card.model_copy(update={"match_summary": f"Возможности по данным каталога — {confirmed}"}))
    if len(cards) == 1:
        message = "В каталоге подтверждены возможности, указанные в задаче."
    else:
        message = "Две отдельные позиции покрывают указанные возможности."
    details = []
    if request.user_limit is not None:
        fields.add("license_quantity")
        details.append(f"лицензии для {request.user_limit} пользователей")
    if request.deployment:
        details.append(f"развёртывание: {request.deployment}")
    if request.origin:
        details.append(f"происхождение: {request.origin}")
    if details:
        message += " Каталог подтверждает " + ", ".join(details) + "."
    if total_kopecks is not None:
        fields.update(("license_quantity", "price_basis", "term"))
        term = _license_term(cards[0])
        price_label = "Общая цена" if len(cards) > 1 else "Цена"
        message += f" {price_label} по снимку каталога за указанный срок лицензии ({term}) — {_rubles(total_kopecks)}."
    return TurnResult(
        outcome="recommend",
        text=message,
        products=products,
        sources=catalog_sources(products, fields),
    )


def recommend_task(index: Path, request: TaskRequest) -> TurnResult | None:
    if not request.capabilities:
        return None
    cards = catalog.find_verified_task_offers(
        index,
        capabilities=request.capabilities,
        user_limit=request.user_limit,
        deployment=request.deployment,
        origin=request.origin,
    )
    if not cards:
        return None

    required = set(request.capabilities)
    eligible = []
    for card in cards:
        quantity = _license_quantity(card)
        if request.user_limit is not None and (quantity or 0) < request.user_limit:
            continue
        coverage = {fact.value for fact in card.verified_facts if fact.field == "capability"} & required
        if coverage:
            eligible.append((card, coverage, _pack_price(card), _license_term(card)))

    for card, coverage, price, term in eligible:
        if coverage != required:
            continue
        if request.budget_kopecks is None or (price is not None and term and price <= request.budget_kopecks):
            return _verified_result(request, [card], price if term else None)

    if len(required) > 1 and request.user_limit is not None:
        bundle = []
        for first, second in combinations(eligible, 2):
            first_card, first_coverage, first_price, first_term = first
            second_card, second_coverage, second_price, second_term = second
            if (
                first_coverage == required or second_coverage == required
                or first_coverage | second_coverage != required
                or first_price is None or second_price is None
                or not first_term or not second_term or first_term.casefold() != second_term.casefold()
            ):
                continue
            total = first_price + second_price
            if request.budget_kopecks is None or total <= request.budget_kopecks:
                bundle.append((total, first_card.offer_id, second_card.offer_id, first_card, second_card))
        if bundle:
            total, _, _, first_card, second_card = min(bundle, key=lambda match: match[:3])
            return _verified_result(request, [first_card, second_card], total)

    if request.user_limit is None:
        question = "Сколько пользователей нужно лицензировать и на какой срок?"
    else:
        question = "Подойдёт ли другой срок лицензии или изменение бюджета?"
    return TurnResult(
        outcome="clarify",
        text="В снимке нет подходящих позиций с подтверждённым покрытием задачи и условиями лицензии. " + question,
    )
