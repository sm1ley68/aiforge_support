from html import escape
import re
from uuid import UUID

from .contracts import QuoteSnapshot


QUOTE_REQUEST = re.compile(
    r"(?:(?:подготовьте|сделайте|оформите|пришлите)\s+)?(?:кп|коммерческое предложение)"
    r"(?:\s+на\s+(?P<quantity>[0-9]{1,5})\s+"
    r"(?P<unit>упаков\w*|комплект\w*|лицензи\w*|пк|уз(?:ел|ла|лов)))?"
    r"(?:[, ]+id предложения\s*[:№#]?\s*(?P<offer_id>[0-9]{2,40}))?[.!?]?",
    re.IGNORECASE,
)


def render_quote(turn_id: UUID, quote: QuoteSnapshot) -> str:
    source = escape(str(quote.source.url), quote=True)
    item = escape(quote.title)
    sku = escape(quote.sku or quote.offer_id)
    currency = escape(quote.currency)
    snapshot = escape(quote.catalog_snapshot_at.isoformat(timespec="minutes"))
    issued = escape(quote.issued_at.isoformat(timespec="minutes"))
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<title>Коммерческое предложение</title></head><body>'
        '<h1>Коммерческое предложение</h1>'
        f'<p>№ {turn_id} · {issued}</p>'
        f'<p><a href="{source}">{item}</a> · {sku}</p>'
        f'<p>Количество: {quote.quantity} {quote.unit_label}</p>'
        f'<p>Цена за единицу: {quote.unit_price:.2f} {currency}</p>'
        f'<p>Итого: <strong>{quote.total:.2f} {currency}</strong></p>'
        f'<p>Снимок каталога: {snapshot}</p>'
        '</body></html>'
    )
