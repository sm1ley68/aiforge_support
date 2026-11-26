import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from softline_backend.catalog import build_index
from softline_backend.contracts import CatalogReference, MessageView
from softline_backend.product_questions import product_question_reply


class ProductQuestionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name)
        feed = folder / "feed.xml"
        feed.write_text(
            '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
            '<offer id="1"><name>Demo Mail One</name><vendorCode>MAIL-1</vendorCode>'
            '<url>https://example.com/one</url></offer>'
            '<offer id="2" available="false"><name>Demo Mail Two</name><vendorCode>MAIL-2</vendorCode>'
            '<url>https://example.com/two</url></offer></offers></shop></yml_catalog>'
        )
        self.index = folder / "catalog.sqlite3"
        build_index(feed, self.index)

    @staticmethod
    def history(*references):
        return [
            MessageView(
                turn_id=uuid4(), role="assistant", text="Каталожный ответ",
                catalog_references=list(references),
            )
        ]

    def test_multiple_candidates_require_sku_and_explicit_sku_wins(self):
        history = self.history(
            CatalogReference(offer_id="1", sku="MAIL-1", title="Demo Mail One"),
            CatalogReference(offer_id="2", sku="MAIL-2", title="Demo Mail Two"),
        )
        ambiguous = product_question_reply(self.index, "Есть в наличии?", history)
        self.assertEqual(ambiguous.outcome, "clarify")
        self.assertEqual(ambiguous.sources, [])
        answer = product_question_reply(self.index, "Есть в наличии у SKU: MAIL-2?", history)
        self.assertEqual(answer.outcome, "answer")
        self.assertIn("нет в наличии", answer.text)
        self.assertEqual(str(answer.sources[0].url), "https://example.com/two")

    def test_changed_offer_identity_and_unsupported_fact_do_not_leak_claims(self):
        stale = self.history(CatalogReference(offer_id="1", sku="RETIRED", title="Retired product"))
        answer = product_question_reply(self.index, "Какая цена?", stale)
        self.assertEqual(answer.outcome, "clarify")
        self.assertEqual(answer.sources, [])
        unknown = product_question_reply(self.index, "Совместим с Windows для SKU: MAIL-2?", [])
        self.assertEqual(unknown.outcome, "clarify")
        self.assertIn("не подтверждается совместимость", unknown.text)
