import gzip
import tempfile
import unittest
from pathlib import Path

from softline_backend.catalog import build_index, catalog_reply, lookup_sku


FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<yml_catalog date="2026-11-26T12:00:00+03:00">
  <shop>
    <offers>
      <offer id="100" group_id="group" available="true">
        <name>Demo Mail One Year</name><vendorCode>MAIL-12</vendorCode>
        <price>1234.50</price><currencyId>RUB</currencyId>
        <url>https://example.com/offers/100</url>
      </offer>
      <offer id="101" group_id="group" available="false">
        <name>Demo Mail Two Years</name><vendorCode>MAIL-24</vendorCode>
        <price>2345.00</price><currencyId>RUB</currencyId>
        <url>https://example.com/offers/101</url>
      </offer>
      <offer id="102"><name>Demo Without Price</name><vendorCode>MAIL-NA</vendorCode>
        <url>https://example.com/offers/102</url>
      </offer>
    </offers>
  </shop>
</yml_catalog>
"""


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.feed = self.folder / "Mindbox.yml.gz.xml"
        self.index = self.folder / "catalog.sqlite3"

    def test_gzip_import_exact_sku_and_unknown_fields(self):
        self.feed.write_bytes(gzip.compress(FEED))
        snapshot = build_index(self.feed, self.index)
        self.assertEqual(snapshot.offer_count, 3)
        self.assertEqual(len(snapshot.sha256), 64)
        self.assertEqual(len(lookup_sku(self.index, " mail-12 ")), 1)
        self.assertEqual(lookup_sku(self.index, "MAIL"), [])
        self.assertEqual(lookup_sku(self.index, "100"), [])

        answer = catalog_reply(self.index, "Артикул MAIL-24")
        self.assertEqual(answer.outcome, "answer")
        self.assertFalse(answer.products[0].availability)
        self.assertEqual(str(answer.products[0].price_amount), "2345.00")
        self.assertEqual(str(answer.sources[0].url), "https://example.com/offers/101")

        unknown = catalog_reply(self.index, "SKU: MAIL-NA")
        self.assertIsNone(unknown.products[0].price_amount)
        self.assertIsNone(unknown.products[0].availability)
        self.assertEqual(catalog_reply(self.index, "SKU: MAIL").outcome, "clarify")
        self.assertIsNone(catalog_reply(self.index, "Нужна защита на 50 человек"))

    def test_bad_import_keeps_active_index(self):
        self.feed.write_bytes(FEED)
        build_index(self.feed, self.index)
        self.feed.write_bytes(FEED.replace(b'id="101"', b'id="100"'))
        with self.assertRaises(ValueError):
            build_index(self.feed, self.index)
        self.assertEqual(lookup_sku(self.index, "MAIL-24")[0].offer_id, "101")

    def test_ambiguous_sku_and_dtd_are_rejected_for_recommendation(self):
        self.feed.write_bytes(FEED.replace(b"MAIL-24", b"MAIL-12"))
        build_index(self.feed, self.index)
        self.assertEqual(catalog_reply(self.index, "SKU MAIL-12").outcome, "clarify")
        self.feed.write_bytes(FEED.replace(b"<yml_catalog", b"<!DOCTYPE yml_catalog><yml_catalog"))
        with self.assertRaises(ValueError):
            build_index(self.feed, self.index)
        self.assertEqual(len(lookup_sku(self.index, "MAIL-12")), 2)
