from html import escape
import re
from uuid import UUID

from .contracts import HandoffDetails, QuoteSnapshot, TurnResult


QUOTE_REQUEST = re.compile(
    r"(?:(?:подготовьте|сделайте|оформите|пришлите)\s+)?(?:кп|коммерческое предложение)"
    r"(?:\s+на\s+(?P<quantity>[0-9]{1,5})\s+"
    r"(?P<unit>упаков\w*|комплект\w*|лицензи\w*|пк|уз(?:ел|ла|лов)))?"
    r"(?:[, ]+id предложения\s*[:№#]?\s*(?P<offer_id>[0-9]{2,40}))?[.!?]?",
    re.IGNORECASE,
)


_DISCOUNT = re.compile(r"\bскидк\w*\b", re.I)
_STACKED_DISCOUNT = re.compile(r"\b(?:купон|промокод|акци|корпоративн\w*\s+цен)\w*\b", re.I)


def discount_response(text: str) -> TurnResult | None:
    if not _DISCOUNT.search(text):
        return None
    if _STACKED_DISCOUNT.search(text):
        return TurnResult(outcome="answer", text="Скидка агента не суммируется с купоном, акцией или корпоративной ценой.")
    return TurnResult(
        outcome="handoff", text="Передал менеджеру запрос на скидку, чтобы проверить условия цены.",
        handoff=HandoffDetails(reason="commercial_terms", summary="Проверить возможность предоставить скидку"),
    )


def render_quote(turn_id: UUID, quote: QuoteSnapshot) -> str:
    source = escape(str(quote.source.url), quote=True)
    item = escape(quote.title)
    sku = escape(quote.sku or quote.offer_id)
    currency = escape(quote.currency)
    snapshot = escape(quote.catalog_snapshot_at.isoformat(timespec="minutes"))
    issued = escape(quote.issued_at.isoformat(timespec="minutes"))
    buyer = quote.customer
    customer = (
        f'<h2>Заказчик</h2><p>{escape(buyer.company)} · ИНН {escape(buyer.inn)} · КПП {escape(buyer.kpp)}</p>'
        if buyer is not None else ""
    )
    delivery = (
        '<p><strong>Поставка требует подтверждения</strong></p>'
        if quote.delivery_status == "requires_confirmation" else ""
    )
    vat = f'<p>{escape(quote.vat_label)}</p>' if quote.vat_label else ""
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<title>Коммерческое предложение</title></head><body>'
        '<h1>Коммерческое предложение</h1>'
        f'<p>№ {turn_id} · {issued}</p>'
        f'{customer}{delivery}'
        f'<p><a href="{source}">{item}</a> · {sku}</p>'
        f'<p>Количество: {quote.quantity} {quote.unit_label}</p>'
        f'<p>Цена за единицу: {quote.unit_price:.2f} {currency}</p>'
        f'<p>Итого: <strong>{quote.total:.2f} {currency}</strong></p>'
        f'{vat}'
        f'<p>Источник цены: {escape(quote.price_origin_label)}</p>'
        f'<p>Снимок каталога: {snapshot}</p>'
        '</body></html>'
    )
