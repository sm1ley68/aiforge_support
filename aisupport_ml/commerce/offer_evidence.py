"""Facts checked on an exact offer card and rules for conflicting evidence."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .catalog import CatalogOffer
from .contracts import Source
from .retrieval import normalize
from .softline_evidence import BACKUP_SOURCES, PACKAGES, PACKAGE_SOURCES, VerifiedPackage, desktop_evidence


@dataclass(frozen=True)
class OfferCardEvidence:
    offer_id: str
    sku: str
    edition: str
    source: Source
    language: str | None = None
    term: str | None = None
    price_rub: Decimal | None = None
    available: bool | None = None


OFFER_CARDS = {
    "473583": OfferCardEvidence(
        "473583", "EP2-07001", "Microsoft Project Professional 2024",
        Source(
            "softline-card-project-2024", "2026-11-27", "Softline — карточка EP2-07001",
            "Для EP2-07001 указана русская версия интерфейса и бессрочное лицензирование одного ПК.",
            "https://store.softline.ru/microsoft/ep2-07001-473583/",
        ),
        language="русская версия", term="бессрочная",
    ),
}


def offer_card(offer: CatalogOffer) -> OfferCardEvidence | None:
    record = OFFER_CARDS.get(offer.offer_id)
    if (record is not None and record.sku == offer.vendor_code
            and normalize(record.edition) in normalize(offer.title)
            and (offer.edition is None or normalize(offer.edition) in normalize(record.edition))):
        return record
    return None


def verified_security_package(offer: CatalogOffer) -> VerifiedPackage | None:
    if "kaspersky total security для бизнеса базовая лицензия" not in normalize(offer.title):
        return None
    return next((package for package in PACKAGES if package.sku == offer.vendor_code), None)


def verified_term(offer: CatalogOffer) -> tuple[int | str, Source] | None:
    if desktop := desktop_evidence(offer):
        return desktop.term_months or "perpetual", desktop.source
    if package := verified_security_package(offer):
        return package.term_months, PACKAGE_SOURCES[0]
    if (offer.offer_id, offer.vendor_code) == ("421471", "PCSCNL") and (
        "кибер бэкап стандартная" in normalize(offer.title)
    ):
        return "perpetual", BACKUP_SOURCES["cyber"][0]
    return None


def commercial_dispute(offer: CatalogOffer, card: OfferCardEvidence, fact: str | None) -> str | None:
    # Older prices and stale availability are observations of a different point in time.
    try:
        if date.fromisoformat(card.source.version) < date.fromisoformat(offer.snapshot_at[:10]):
            return None
    except ValueError:
        return None
    if (fact in (None, "price") and offer.currency == "RUB" and offer.price is not None
            and card.price_rub is not None and offer.price != card.price_rub):
        return (f"Цена {card.sku}: {offer.price:.2f} RUB в фиде от {offer.snapshot_at}, "
                f"{card.price_rub:.2f} RUB в карточке от {card.source.version}.")
    if (fact in (None, "availability") and offer.available is not None
            and card.available is not None and offer.available != card.available):
        labels = {True: "доступно", False: "недоступно"}
        return f"Наличие {card.sku}: {labels[offer.available]} в фиде от {offer.snapshot_at}, " \
               f"{labels[card.available]} в карточке от {card.source.version}."
    return None
