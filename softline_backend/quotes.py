from base64 import b64encode
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from html import escape
import re
from uuid import UUID
from zoneinfo import ZoneInfo

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


_QUOTE_CSS = """
:root {
      color-scheme: light;
      --ink: #2b252b;
      --muted: #655b64;
      --burgundy: #842b47;
      --dark: #622139;
      --line: #ece1e6;
      --tint: #fbf3f5;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #f6edef;
    }
    * { box-sizing: border-box; }
    body { margin: 0; padding: clamp(14px, 5vw, 60px); line-height: 1.45; }
    main {
      max-width: 880px; margin: 0 auto; overflow: hidden;
      background: #fff; border: 1px solid var(--line); border-radius: 24px;
      box-shadow: 0 28px 80px #62213913, 0 8px 24px #6221390b;
    }
    .document-head { padding: 31px 39px 28px; background: var(--burgundy); color: #fff; }
    .brand { margin: 0 0 25px; font-size: .94rem; font-weight: 710; }
    h1 { margin: 0; font-size: clamp(1.75rem, 4.9vw, 2.85rem); line-height: 1.04; letter-spacing: -.043em; }
    .document-meta {
      display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 16px;
      margin-top: 15px; font-size: .81rem; color: #ffebf2;
    }
    .document-meta span { overflow-wrap: anywhere; }
    .main-content { display: grid; gap: 24px; padding: 25px 39px 27px; }
    h2 { margin: 0; font-size: 1rem; font-weight: 740; }
    .customer {
      display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 14px 28px;
      padding: 15px 18px; border-radius: 14px; background: var(--tint);
    }
    .customer-name { margin: 3px 0 0; font-size: 1.18rem; font-weight: 730; }
    dl { margin: 0; }
    .customer dl { display: flex; gap: 7px 23px; flex-wrap: wrap; align-self: center; }
    .customer dt { color: var(--muted); font-size: .75rem; }
    .customer dd { margin: 2px 0 0; font-size: .88rem; font-weight: 660; font-variant-numeric: tabular-nums; }
    .delivery { margin: 0; color: var(--dark); font-weight: 700; }
    .line-item { overflow: hidden; border: 1px solid var(--line); border-radius: 14px; }
    table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
    th { background: #fbf7f8; color: var(--muted); text-align: left; font-size: .81rem; font-weight: 660; }
    th, td { padding: 12px 17px; }
    td { border-top: 1px solid var(--line); }
    th:last-child, td:last-child { text-align: right; }
    th:nth-child(2), td:nth-child(2) { width: 82px; white-space: nowrap; }
    td:last-child { white-space: nowrap; }
    .product { max-width: 395px; font-weight: 730; overflow-wrap: anywhere; }
    .sku { display: block; margin-top: 4px; color: var(--muted); font-size: .82rem; font-weight: 500; }
    .price { font-size: 1.04rem; font-weight: 710; }
    .summary { display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 18px; }
    .sources { margin: 0; color: var(--muted); font-size: .81rem; }
    .sources + .sources { margin-top: 4px; }
    .sources a { color: var(--burgundy); font-weight: 670; text-underline-offset: 3px; }
    .total { min-width: 232px; padding: 14px 18px 16px; border-radius: 13px; background: var(--tint); text-align: right; }
    .total p { margin: 0; color: var(--muted); font-size: .79rem; }
    .total strong { display: block; margin: 1px 0 3px; color: var(--dark); font-size: 2rem; line-height: 1.15; letter-spacing: -.04em; }
    footer {
      display: flex; align-items: center; justify-content: space-between; gap: 5px 16px; flex-wrap: wrap;
      padding: 13px 39px; border-top: 1px solid var(--line); font-size: .78rem; color: var(--muted);
    }
    footer span { color: var(--burgundy); font-weight: 680; }
    @media (max-width: 560px) {
      .document-head, .main-content, footer { padding-inline: 17px; }
      .document-head { padding-block: 21px; }
      .main-content { gap: 17px; }
      th,td { padding: 10px 8px; }
      th:nth-child(2), td:nth-child(2) { width: auto; }
      .product { font-size: .86rem; }
      .price { font-size: .92rem; }
      .summary { align-items: stretch; }
      .total { width: 100%; }
    }
    @page { size: A4; margin: 15mm; }
    @media print {
      :root { background: #fff; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      body { padding: 0; }
      main { max-width: none; box-shadow: none; }
      .document-head, .customer, .line-item, .summary { break-inside: avoid; }
    }
"""
_STYLE_HASH = b64encode(sha256(_QUOTE_CSS.encode()).digest()).decode()
QUOTE_CSP = f"default-src 'none'; style-src 'sha256-{_STYLE_HASH}'; base-uri 'none'; form-action 'none'"
_MOSCOW = ZoneInfo("Europe/Moscow")


def _money(value: Decimal, currency: str) -> str:
    amount = f"{value:,.2f}".replace(",", "\u00a0").replace(".", ",")
    return f"{amount}\u00a0{'₽' if currency == 'RUB' else escape(currency)}"


def _time(value: datetime) -> str:
    local = value.astimezone(_MOSCOW)
    return f'<time datetime="{local.isoformat(timespec="minutes")}">{local:%d.%m.%Y, %H:%M} МСК</time>'


def render_quote(turn_id: UUID, quote: QuoteSnapshot) -> str:
    source = escape(str(quote.source.url), quote=True)
    buyer = quote.customer
    customer = (
        '<section class="customer" aria-labelledby="customer-title">'
        '<div><h2 id="customer-title">Заказчик</h2>'
        f'<p class="customer-name">{escape(buyer.company)}</p></div>'
        f'<dl><div><dt>ИНН</dt><dd>{escape(buyer.inn)}</dd></div>'
        f'<div><dt>КПП</dt><dd>{escape(buyer.kpp)}</dd></div></dl></section>'
        if buyer is not None else ""
    )
    delivery = (
        '<p class="delivery">Поставка требует подтверждения</p>'
        if quote.delivery_status == "requires_confirmation" else ""
    )
    vat = f'<p>{escape(quote.vat_label)}</p>' if quote.vat_label else ""
    sku = f"Артикул {escape(quote.sku)} · " if quote.sku else ""
    return f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="Content-Security-Policy" content="{escape(QUOTE_CSP, quote=True)}">
<title>Коммерческое предложение · Softline Store</title>
<style>{_QUOTE_CSS}</style>
</head>
<body><main>
<header class="document-head">
  <p class="brand">Softline Store</p>
  <h1>Коммерческое предложение</h1>
  <div class="document-meta"><span>№ {turn_id}</span>{_time(quote.issued_at)}</div>
</header>
<div class="main-content">
  {customer}{delivery}
  <section class="line-item" aria-label="Позиция и расчёт">
    <table>
      <thead><tr><th scope="col">Позиция</th><th scope="col">Кол-во</th><th scope="col">Цена за единицу</th></tr></thead>
      <tbody><tr>
        <td><div class="product">{escape(quote.title)}</div>
          <span class="sku">{sku}Предложение {escape(quote.offer_id)}</span></td>
        <td>{quote.quantity} {escape(quote.unit_label)}</td>
        <td class="price">{_money(quote.unit_price, quote.currency)}</td>
      </tr></tbody>
    </table>
  </section>
  <div class="summary">
    <div>
      <p class="sources">Источник цены · <a href="{source}">{escape(quote.price_origin_label)} ↗</a></p>
      <p class="sources">Снимок каталога · {_time(quote.catalog_snapshot_at)}</p>
    </div>
    <div class="total"><p>Итого</p><strong>{_money(quote.total, quote.currency)}</strong>{vat}</div>
  </div>
</div>
<footer><span>Демо-прототип конкурса «ИИкузница»</span><div>Softline Store Advisor</div></footer>
</main></body>
</html>'''
