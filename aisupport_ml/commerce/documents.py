from decimal import Decimal, ROUND_HALF_UP
from html import escape

from .contracts import Document, PricedLine


def build_document(id, kind, customer, cart, catalog, conditions, seller) -> Document:
    priced = []
    for item in cart:
        product = catalog[item.sku]
        if (item.quantity is None or item.quantity <= 0
                or not product.price.is_finite() or product.price < 0):
            raise ValueError("Invalid catalog price or quantity")
        unit = product.price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        priced.append(PricedLine(
            item.sku, product.name, item.quantity, unit, unit * item.quantity,
            product.currency, product.source,
        ))
    currencies = {line.currency for line in priced}
    if len(currencies) != 1:
        raise ValueError("Expected a single currency")
    currency, = currencies
    return Document(
        id, kind, customer, tuple(priced), currency,
        sum((line.subtotal for line in priced), Decimal("0.00")), tuple(conditions), seller,
    )


def render_document(document: Document) -> str:
    """Return a printable HTML document for the synthetic storefront."""
    title = "Коммерческое предложение" if document.kind == "quote" else "Счёт на оплату"
    rows = "\n".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in (
            line.sku, line.name, line.quantity, line.unit_price, line.subtotal,
        )) + "</tr>" for line in document.lines
    )
    buyer = ""
    if document.customer:
        buyer = (
            f"<p>Покупатель: {escape(document.customer.company)}. "
            f"ИНН: {escape(document.customer.tax_id)}</p>"
        )
    supplier = ""
    if document.seller:
        seller = document.seller
        supplier = f"<p>Поставщик: {escape(seller.company)}. ИНН: {escape(seller.tax_id)}</p>"
        if document.kind == "invoice":
            supplier += (f"<p>Банк: {escape(seller.bank)}. БИК: {escape(seller.bank_code)}. "
                         f"Расчётный счёт: {escape(seller.settlement_account)}</p>")
    conditions = "".join(f"<li>{escape(source.text)}</li>" for source in document.conditions)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 3rem auto; max-width: 65rem; padding: 0 1rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #999; padding: .6rem; text-align: left; }}
</style></head><body>
<h1>{title}</h1><p>№ {escape(document.id)}</p>
{supplier}{buyer}
<table><thead><tr><th>Артикул</th><th>Позиция</th><th>Количество</th><th>Цена</th><th>Сумма</th></tr></thead>
<tbody>{rows}</tbody></table>
<p><strong>Итого: {document.total} {escape(document.currency)}</strong></p>
<ul>{conditions}</ul><p>Демонстрационный документ</p>
</body></html>
"""
