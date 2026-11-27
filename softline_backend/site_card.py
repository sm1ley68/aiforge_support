"""Read commercial terms only from an exact public Softline product card."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import urlsplit

import httpx

from aisupport_ml.commerce.catalog import CatalogOffer


MAX_CARD_BYTES = 3 * 1024 * 1024


@dataclass(frozen=True)
class SiteTerms:
    price: Decimal | None = None
    currency: str | None = None
    vat_label: str | None = None
    conflicting_price: bool = False


def _card_path(url: str, offer_id: str) -> str | None:
    parts = urlsplit(url)
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


def read_terms(offer: CatalogOffer, document: str) -> SiteTerms | None:
    from lxml import etree, html

    path = _card_path(offer.url, offer.offer_id)
    if not path or not offer.vendor_code or not document:
        return None
    try:
        page = html.fromstring(document)
    except (ValueError, etree.ParserError):
        return None

    prices = set()
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
        if not isinstance(item_url, str) or _card_path(item_url, offer.offer_id) != path:
            continue
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
    if any(amount != price for amount in displayed):
        return SiteTerms(conflicting_price=True)
    vat_labels = set()
    for node in (*bodies, *page.find_class("b-product__buy-options-standard-features")):
        for text in node.itertext():
            label = " ".join(text.split())
            if rate := re.fullmatch(r"Размер НДС \(([0-9]{1,2}(?:[.,][0-9]{1,2})?)%\)", label, re.I):
                vat_labels.add(f"НДС {rate[1].replace('.', ',')}%")
            if re.fullmatch(r"(?:Цена )?без НДС", label, re.I):
                vat_labels.add("Без НДС")
    return SiteTerms(price, currency, vat_labels.pop() if len(vat_labels) == 1 else None)


def fetch_terms(offer: CatalogOffer) -> SiteTerms | None:
    if not _card_path(offer.url, offer.offer_id) or not offer.vendor_code:
        return None
    try:
        with httpx.stream("GET", offer.url, timeout=httpx.Timeout(4, connect=2), trust_env=False) as response:
            if response.status_code != 200:
                return None
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_CARD_BYTES:
                    return None
                data.extend(chunk)
            return read_terms(offer, data.decode(response.encoding or "utf-8", errors="replace"))
    except (httpx.HTTPError, LookupError):
        return None
