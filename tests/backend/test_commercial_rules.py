from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from types import SimpleNamespace
import unittest

from fastapi.testclient import TestClient

from aisupport_ml.commerce.catalog import CatalogOffer
from softline_backend.api import create_app
from softline_backend.commerce_bridge import CatalogModel, CommerceBridge
from softline_backend.quotes import discount_response
from softline_backend.site_card import SiteTerms, read_card_evidence, read_terms
from softline_backend.store import ChatStore, ClaimedTurn
from softline_backend.support_hours import SupportHours


URL = "https://store.softline.ru/test/sku-1001/"


class CommercialTests(unittest.TestCase):
    def test_card_accepts_only_same_sku_and_consistent_labeled_price(self):
        html = f'''<script type="application/ld+json">{{
          "@type":"Product","sku":"EXACT","name":"Редактор Professional",
          "offers":{{"@type":"Offer","url":"{URL}","price":"120","priceCurrency":"RUB"}}
        }}</script>
        <div class="b-checkout-modal__body">
          <span class="js-pay_in_one_click-price">120</span>
          <span>Размер НДС (20%)</span>
        </div>'''
        offer = SimpleNamespace(vendor_code="EXACT", offer_id="1001", url=URL, title="Редактор Professional",
                                edition="Professional")
        terms = read_terms(offer, html)
        self.assertEqual(terms.price, Decimal("120"))
        self.assertEqual(terms.vat_label, "НДС 20%")
        self.assertIsNone(read_terms(offer, html.replace('"EXACT"', '"OTHER"')))
        self.assertTrue(read_terms(offer, html.replace(">120</span>", ">119</span>")).conflicting_price)
        self.assertIsNone(read_terms(offer, html.replace("Размер НДС (20%)", "Общие сведения об НДС")).vat_label)

    def test_bulk_checkout_total_matches_unit_price_and_verified_quantity_range(self):
        url = "https://store.softline.ru/novosoft/hbs10-339688/"
        title = "Новософт Handy Backup (лицензии), стоимость 1 лицензии версии Standard"
        offer = CatalogOffer(
            "339688", "HBS10", None, None, title, None, url, "2026-11-27 22:26",
            Decimal("3080"), "RUB", True, None, None, None, None, None, None,
        )
        html = f'''<script type="application/ld+json">{{
          "@type":"Product","sku":"HBS10","name":"{title}",
          "offers":{{"@type":"Offer","url":"{url}","price":"3080","priceCurrency":"RUB"}}
        }}</script>
        <div id="product_counter_wrapper" data-range-products='[
          {{"minQuantity":4,"maxQuantity":9,"link":"/novosoft/hbs4-9-339687/"}},
          {{"minQuantity":10,"maxQuantity":999,"link":"/novosoft/hbs10-339688/"}}
        ]'>
          <input name="product-amount" class="js-product-quantity" value="10">
        </div>
        <div class="b-checkout-modal__body">
          <strong><span class="js-pay_in_one_click-price">30 800</span> ₽</strong>
          <span>Полная стоимость</span><span>Размер НДС (22%)</span>
        </div>'''
        terms = read_terms(offer, html)
        self.assertEqual((terms.price, terms.currency, terms.vat_label), (Decimal("3080"), "RUB", "НДС 22%"))
        self.assertEqual(terms.quantity_range, (10, 999))
        for invalid in (
            html.replace("30 800", "30 900"),
            html.replace('value="10"', 'value="9"'),
            html.replace('name="product-amount"', 'name="unknown"'),
        ):
            self.assertTrue(read_terms(offer, invalid).conflicting_price)

        bridge = CommerceBridge(Path("/unused"), CatalogModel("", ""), verify_site=True)
        bridge.agent.catalog_index = SimpleNamespace(by_reference=lambda _ref: (offer,))
        with patch("softline_backend.commerce_bridge.fetch_terms", return_value=terms):
            turn = ClaimedTurn(uuid4(), uuid4(), 1, "КП на 10 лицензий, ID предложения 339688", 1)
            result = bridge.reply(turn, [], None)
            self.assertEqual(result.quote.total, Decimal("30800.00"))
            self.assertEqual(result.quote.vat_label, "НДС 22%")
            too_few = ClaimedTurn(uuid4(), uuid4(), 1, "КП на 9 лицензий, ID предложения 339688", 1)
            result = bridge.reply(too_few, [], None)
            self.assertEqual(result.outcome, "clarify")
            self.assertIsNone(result.quote)

    def test_product_facts_require_the_same_sku_offer_and_edition(self):
        offer = CatalogOffer(
            "1001", "EXACT", None, None, "Редактор Professional 2024", None, URL, "2026-11-27 10:00",
            Decimal("99"), "RUB", False, None, None, None, "Professional 2024", None, None,
        )
        html = f'''<script type="application/ld+json">{{
          "@type":"Product","sku":"EXACT","name":"Редактор Professional 2024",
          "additionalProperty":[{{"name":"Срок лицензии","value":"24 мес."}},
                                 {{"name":"Операционная система","value":"Windows 11"}}],
          "offers":{{"@type":"Offer","url":"{URL}","price":"120","priceCurrency":"RUB",
                     "availability":"https://schema.org/InStock"}}
        }}</script>'''
        card = read_card_evidence(offer, html)
        self.assertEqual((card.price_rub, card.available, card.term, card.platforms),
                         (Decimal("120"), True, "24 мес.", ("windows 11",)))
        for wrong in (html.replace("Professional", "Standard"), html.replace('"EXACT"', '"OTHER"'),
                      html.replace("/sku-1001/", "/other-1001/")):
            self.assertIsNone(read_card_evidence(offer, wrong))
        disputed = read_card_evidence(offer, html + html.replace('"120"', '"121"'))
        self.assertIn("price", disputed.conflicts)
        self.assertIsNone(disputed.price_rub)

    def test_quote_uses_authoritative_card_or_escalates_an_ambiguous_price(self):
        offer = CatalogOffer(
            "1001", "EXACT", None, None, "Тестовая позиция", None, URL, "2026-11-27 10:00",
            Decimal("99"), "RUB", True, None, None, None, None, None, None,
        )
        bridge = CommerceBridge(Path("/unused"), CatalogModel("", ""), verify_site=True)
        bridge.agent.catalog_index = SimpleNamespace(by_reference=lambda _ref: (offer,))
        turn = ClaimedTurn(uuid4(), uuid4(), 1, "КП на 2 упаковки, ID предложения 1001", 1)
        with patch("softline_backend.commerce_bridge.fetch_terms", return_value=SiteTerms(Decimal("120"), "RUB", "НДС 20%")):
            result = bridge.reply(turn, [], None)
        self.assertEqual(result.quote.total, Decimal("240"))
        self.assertEqual(result.quote.vat_label, "НДС 20%")
        self.assertEqual(result.quote.price_origin_label, "Карточка Softline")
        self.assertEqual(result.products[0].price_amount, Decimal("120"))
        with patch("softline_backend.commerce_bridge.fetch_terms", return_value=SiteTerms(conflicting_price=True)):
            result = bridge.reply(turn, [], None)
        self.assertIsNone(result.quote)
        self.assertEqual(result.handoff.summary, "Сверить цену позиции")
        with patch("softline_backend.commerce_bridge.fetch_terms", return_value=None):
            result = bridge.reply(turn, [], None)
        self.assertEqual(result.quote.total, Decimal("198"))
        self.assertIsNone(result.quote.vat_label)

    def test_discount_cannot_stack_and_unverified_goes_to_manager(self):
        self.assertIn("не суммируется", discount_response("Добавьте скидку поверх купона").text)
        self.assertIsNone(discount_response("КП на 2 упаковки, ID предложения 1001"))
        answer = discount_response("Сделайте скидку 5%")
        self.assertEqual(answer.outcome, "handoff")
        self.assertEqual(answer.handoff.reason, "commercial_terms")

    def test_availability_is_separate_from_queue_and_uses_configured_window(self):
        hours = SupportHours.from_values("09:00", "18:00", "1,2,3,4,5", "Europe/Moscow", "team@example.org")
        working = hours.status(datetime(2026, 11, 27, 10, tzinfo=timezone.utc))
        after = hours.status(datetime(2026, 11, 27, 16, tzinfo=timezone.utc))
        self.assertEqual(working["status"], "working_hours")
        self.assertNotIn("email", working)
        self.assertEqual(after["status"], "outside_working_hours")
        self.assertEqual(after["email"], "team@example.org")
        with TestClient(create_app(ChatStore(""), support_hours=SupportHours())) as client:
            status = client.get("/api/support/availability")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.headers["Cache-Control"], "no-store")
            self.assertEqual(status.json()["status"], "unknown")
