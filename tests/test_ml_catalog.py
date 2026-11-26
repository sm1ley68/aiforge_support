from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aisupport_ml.commerce.catalog import SoftlineCatalog, build_catalog


FEED = """<yml_catalog date="2026-11-25 14:12"><shop><offers>
<offer id="one" group_id="g" available="true">
  <name>NetDesk Mail Starter</name><vendorCode>MAIL-1</vendorCode>
  <url>https://store.example/one</url><price>1100.20</price><currencyId>RUR</currencyId>
  <param name="Тип лицензии">Полная версия</param>
  <param name="К-во пользователей до">50</param>
  <param name="Версия">другое или отсутствует</param>
</offer>
<offer id="two" group_id="g" available="false">
  <name>NetDesk Mail Plus</name><vendorCode>MAIL-2</vendorCode>
  <url>https://store.example/two</url><price>2100</price><currencyId>RUR</currencyId>
  <param name="Версия">Plus</param>
</offer>
<offer id="three" available="false">
  <name>NetDesk Mail Archive</name><url>https://store.example/three</url>
  <price>0</price><currencyId>RUR</currencyId>
</offer>
</offers></shop></yml_catalog>"""


class MLCatalogTests(unittest.TestCase):
    def test_import_lookup_and_filters(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            feed, index = path / "feed.xml", path / "catalog.sqlite"
            feed.write_text(FEED, encoding="utf-8")
            summary = build_catalog(feed, index)
            self.assertEqual((summary.offers, summary.available), (3, 1))
            catalog = SoftlineCatalog(index)
            offer, = catalog.by_reference("mail-1")
            self.assertEqual((offer.offer_id, offer.price, offer.currency), ("one", Decimal("1100.20"), "RUB"))
            self.assertEqual((offer.user_limit, offer.edition), (50, None))
            self.assertEqual({item.offer_id for item in catalog.variants("g")}, {"one", "two"})
            self.assertEqual([item.offer_id for item in catalog.search("NetDesk Mail", available_only=True)], ["one"])
            self.assertEqual(catalog.search("NetDesk Enterprise"), ())
            self.assertTrue(catalog.has_title_phrase("netdesk mail plus"))
            self.assertFalse(catalog.has_title_phrase("netdesk plus mail"))
            unavailable, = catalog.by_reference("two")
            self.assertEqual((unavailable.available, unavailable.price), (False, Decimal("2100")))
            self.assertIsNone(catalog.by_reference("three")[0].price)
            with self.assertRaises(FileExistsError):
                build_catalog(feed, index)
