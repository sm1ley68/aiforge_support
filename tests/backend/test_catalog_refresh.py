import gzip
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lxml.etree import XMLSyntaxError

from aisupport_ml.commerce.catalog import SoftlineCatalog
from softline_backend.catalog_refresh import refresh
from softline_backend.readiness import commerce_snapshot_at


class CatalogRefreshTests(unittest.TestCase):
    def test_valid_gzip_replaces_snapshot_and_invalid_or_old_feed_preserves_it(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "commerce.sqlite3"
            feed = root / "feed.gz"

            def write(day, price):
                feed.write_bytes(gzip.compress((
                    f'<yml_catalog date="2026-11-{day} 10:00"><shop><offers>'
                    '<offer id="1001" available="true"><name>Тестовый товар</name>'
                    '<url>https://store.softline.ru/sample/</url>'
                    f'<price>{price}</price><currencyId>RUR</currencyId></offer>'
                    '</offers></shop></yml_catalog>'
                ).encode()))

            write("25", "100")
            self.assertTrue(refresh(target, source=feed))
            catalog = SoftlineCatalog(target)
            self.assertEqual(str(catalog.by_reference("1001")[0].price), "100")
            write("26", "150")
            self.assertTrue(refresh(target, source=feed))
            self.assertEqual(str(catalog.by_reference("1001")[0].price), "150")
            self.assertEqual(commerce_snapshot_at(target), "2026-11-26 10:00")
            original = target.read_bytes()
            write("25", "99")
            self.assertFalse(refresh(target, source=feed))
            feed.write_bytes(b"corrupt feed")
            with self.assertRaises(XMLSyntaxError):
                refresh(target, source=feed)
            self.assertEqual(target.read_bytes(), original)
