"""Read commercial terms only from an exact public Softline product card."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import urljoin, urlsplit

import httpx

from aisupport_ml.commerce.catalog import CatalogOffer
from aisupport_ml.commerce.contracts import Source
from aisupport_ml.commerce.offer_evidence import OfferCardEvidence
from aisupport_ml.commerce.retrieval import normalize


MAX_CARD_BYTES = 3 * 1024 * 1024


@dataclass(frozen=True)
class SiteTerms:
    price: Decimal | None = None
    currency: str | None = None
    vat_label: str | None = None
    conflicting_price: bool = False
    quantity_range: tuple[int, int] | None = None


def _card_path(url: str, offer_id: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (
        parts.scheme == "https" and parts.netloc == "store.softline.ru" and not parts.query and not parts.fragment
        and re.search(rf"[-/]{re.escape(offer_id)}/?$", parts.path)
    ):
        return parts.path.rstrip("/")
    return None


def _price(value) -> Decimal | None:
    try:
        amount = Decimal(str(value).replace(" ", "").replace("\xa0", "").replace("\u202f", "").replace(",", "."))
        return amount if amount.is_finite() and 0 < amount < 10**12 else None
    except InvalidOperation:
        return None


def _exact_card(offer: CatalogOffer, document: str):
    from lxml import etree, html

    path = _card_path(offer.url, offer.offer_id)
    if not path or not offer.vendor_code or not document:
        return None
    try:
        page = html.fromstring(document)
    except (ValueError, etree.ParserError):
        return None

    edition = normalize(offer.edition or "")
    title = normalize(offer.title)
    if not title or (edition and f" {edition} " not in f" {title} "):
        return None
    products = tuple(_products(page, offer, path))
    if not products or any(not isinstance(product.get("name"), str) or normalize(product["name"]) != title
                           for product, _ in products):
        return None
    return page, products


def read_terms(offer: CatalogOffer, document: str) -> SiteTerms | None:
    matched = _exact_card(offer, document)
    return _read_terms(offer, *matched) if matched else None


def _products(page, offer: CatalogOffer, path: str):
    for script in page.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            product = json.loads(script)
        except (TypeError, ValueError):
            continue
        if not isinstance(product, dict) or product.get("@type") != "Product":
            continue
        sku = product.get("sku")
        item = product.get("offers")
        if not isinstance(sku, str) or sku.strip().casefold() != offer.vendor_code.casefold():
            continue
        if not isinstance(item, dict) or item.get("@type") != "Offer":
            continue
        item_url = item.get("url")
        if isinstance(item_url, str) and _card_path(item_url, offer.offer_id) == path:
            yield product, item


def _offer_quantity_range(counter, offer: CatalogOffer) -> tuple[int, int] | None:
    try:
        entries = json.loads(counter.get("data-range-products", "[]"))
    except (TypeError, ValueError):
        return None
    if not isinstance(entries, list):
        return None
    path = _card_path(offer.url, offer.offer_id)
    ranges = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(link := entry.get("link"), str):
            continue
        try:
            linked_url = urljoin(offer.url, link)
        except ValueError:
            continue
        if _card_path(linked_url, offer.offer_id) != path:
            continue
        minimum, maximum = entry.get("minQuantity"), entry.get("maxQuantity")
        if type(minimum) is int and type(maximum) is int and 1 <= minimum <= maximum:
            ranges.add((minimum, maximum))
    return next(iter(ranges)) if len(ranges) == 1 else None


def _read_terms(offer: CatalogOffer, page, products) -> SiteTerms | None:
    prices = set()
    for _, item in products:
        amount = _price(item.get("price"))
        currency = item.get("priceCurrency")
        if amount is not None and isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency):
            prices.add((amount, currency))
    if len(prices) != 1:
        return SiteTerms(conflicting_price=True) if prices else None

    price, currency = prices.pop()
    bodies = page.find_class("b-checkout-modal__body")
    displayed = [_price(element.text_content().strip()) for body in bodies
                 for element in body.find_class("js-pay_in_one_click-price")]
    quantity = 1
    quantity_range = None
    counters = page.xpath("//*[@id='product_counter_wrapper']")
    if counters:
        if len(counters) != 1:
            return SiteTerms(conflicting_price=True)
        counter, = counters
        values = counter.xpath(".//input[@name='product-amount']/@value")
        if len(values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,4}", values[0]):
            return SiteTerms(conflicting_price=True)
        quantity = int(values[0])
        quantity_range = _offer_quantity_range(counter, offer)
        if quantity_range is None and quantity > 1:
            quantity_range = (quantity, quantity)
        if quantity_range is not None and not quantity_range[0] <= quantity <= quantity_range[1]:
            return SiteTerms(conflicting_price=True)
    if any(amount != price * quantity for amount in displayed):
        return SiteTerms(conflicting_price=True)
    vat_labels = set()
    for node in (*bodies, *page.find_class("b-product__buy-options-standard-features")):
        for text in node.itertext():
            label = " ".join(text.split())
            if rate := re.fullmatch(r"Размер НДС \(([0-9]{1,2}(?:[.,][0-9]{1,2})?)%\)", label, re.I):
                vat_labels.add(f"НДС {rate[1].replace('.', ',')}%")
            if re.fullmatch(r"(?:Цена )?без НДС", label, re.I):
                vat_labels.add("Без НДС")
    return SiteTerms(price, currency, vat_labels.pop() if len(vat_labels) == 1 else None, quantity_range=quantity_range)


_CARD_FIELDS = {
    "срок действия": "term", "срок лицензии": "term", "язык интерфейса": "language",
    "операционная система": "compatibility",
}
_STOCK = {
    "https://schema.org/InStock": True, "http://schema.org/InStock": True,
    "https://schema.org/OutOfStock": False, "http://schema.org/OutOfStock": False,
}


def read_card_evidence(offer: CatalogOffer, document: str) -> OfferCardEvidence | None:
    """Accept only records identifying the same offer, SKU, and versioned title."""
    matched = _exact_card(offer, document)
    if matched is None:
        return None
    page, products = matched

    terms = _read_terms(offer, page, products)
    values = {field: set() for field in _CARD_FIELDS.values()}
    stock = set()
    conflicts = set()
    for product, item in products:
        raw_stock = item.get("availability")
        if isinstance(raw_stock, str) and raw_stock in _STOCK:
            stock.add(_STOCK[raw_stock])
        properties = product.get("additionalProperty", [])
        if not isinstance(properties, list):
            properties = [properties] if isinstance(properties, dict) else []
        for property_value in properties:
            if not isinstance(property_value, dict):
                continue
            label, value = property_value.get("name"), property_value.get("value")
            if not isinstance(label, str) or not isinstance(value, str):
                continue
            field = _CARD_FIELDS.get(normalize(label))
            value = " ".join(value.split())
            if field and 0 < len(value) <= 200:
                values[field].add(value)
    if terms and (terms.conflicting_price or terms.currency != "RUB"):
        conflicts.add("price")
    if len(stock) > 1:
        conflicts.add("availability")
    conflicts.update(field for field, options in values.items() if len(options) > 1)

    language = next(iter(values["language"])) if len(values["language"]) == 1 else None
    term = next(iter(values["term"])) if len(values["term"]) == 1 else None
    platform = next(iter(values["compatibility"])) if len(values["compatibility"]) == 1 else ""
    source = Source(
        f"softline-site-{offer.offer_id}", datetime.now(timezone.utc).date().isoformat(),
        f"Карточка Softline · {offer.vendor_code}", "", offer.url, sku=offer.offer_id,
    )
    return OfferCardEvidence(
        offer.offer_id, offer.vendor_code, offer.edition or offer.title, source, language=language, term=term,
        price_rub=terms.price if terms and "price" not in conflicts else None,
        available=next(iter(stock)) if len(stock) == 1 else None,
        platforms=tuple(normalize(value) for value in re.split(r"[,;/]", platform) if normalize(value)),
        conflicts=frozenset(conflicts),
    )


def _fetch_card(offer: CatalogOffer) -> str | None:
    if not _card_path(offer.url, offer.offer_id) or not offer.vendor_code:
        return None
    try:
        with httpx.stream("GET", offer.url, timeout=httpx.Timeout(4, connect=2),
                          trust_env=False, follow_redirects=False) as response:
            if response.status_code != 200:
                return None
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_CARD_BYTES:
                    return None
                data.extend(chunk)
            return data.decode(response.encoding or "utf-8", errors="replace")
    except (httpx.HTTPError, LookupError):
        return None


def fetch_terms(offer: CatalogOffer) -> SiteTerms | None:
    document = _fetch_card(offer)
    return read_terms(offer, document) if document else None


def fetch_card_evidence(offer: CatalogOffer) -> OfferCardEvidence | None:
    document = _fetch_card(offer)
    return read_card_evidence(offer, document) if document else None
