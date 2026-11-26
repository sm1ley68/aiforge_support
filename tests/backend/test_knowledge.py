import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from softline_backend import catalog


FEED = """<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>
<offer id="one" group_id="mail" available="true">
  <name>Demo Mail Standard</name><vendorCode>MAIL-A</vendorCode>
  <param name="Family">Demo Mail</param><param name="Edition">Standard</param>
  <param name="Unmapped attribute">Unknown</param>
  <description>Защита почты и файлов</description>
  <url>https://store.example/product/one</url><price>1000.00</price><currencyId>RUB</currencyId>
</offer>
<offer id="two" group_id="mail" available="true">
  <name>Demo Mail Premium</name><vendorCode>MAIL-B</vendorCode>
  <param name="Family">Demo Mail</param><param name="Edition">Premium</param>
  <param name="Capability">email_protection</param>
  <param name="Количество пользователей в лицензии">80</param>
  <param name="Единица цены">за лицензионный пакет</param>
  <description>Защита файлов</description>
  <url>https://store.example/product/two</url>
</offer>
<offer><name>Missing stable identifier</name></offer>
</offers></shop></yml_catalog>"""


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        self.feed = folder / "feed.xml"
        self.index = folder / "catalog.sqlite"
        self.manifest = folder / "manifest.json"
        self.feed.write_text(FEED, encoding="utf-8")

    def evidence(self, field="deployment", value="on-premises", **overrides):
        row = {
            "scope": "offer",
            "offer_id": "one",
            "field": field,
            "value": value,
            "source_url": "https://docs.example/product-one",
            "source_title": "Product one guide",
        }
        row.update(overrides)
        return row

    def write_manifest(self, *rows):
        self.manifest.write_text(json.dumps(rows), encoding="utf-8")

    def test_exact_offer_evidence_is_cited_with_its_own_source(self):
        self.write_manifest(
            self.evidence(),
            self.evidence(source_url="https://kb.example/product-one", source_title="Product one KB"),
        )
        catalog.build_index(self.feed, self.index, knowledge=self.manifest)
        reply = catalog.catalog_reply(self.index, "Нужен Demo Mail Standard")
        card = reply.products[0]

        self.assertEqual(
            {(fact.value, str(fact.source.url)) for fact in card.verified_facts if fact.field == "deployment"},
            {("локально", "https://docs.example/product-one"), ("локально", "https://kb.example/product-one")},
        )
        self.assertEqual(str(card.url), "https://store.example/product/one")
        self.assertIn("https://docs.example/product-one", [str(source.url) for source in reply.sources])
        self.assertIsNone(catalog.lookup_offer(self.index, "two").deployment)

    def test_jsonl_sku_scope_resolves_case_insensitively(self):
        manifest = self.manifest.with_suffix(".jsonl")
        row = self.evidence("user_limit", 60, scope="sku", sku="mail-a")
        del row["offer_id"]
        manifest.write_text("\n" + json.dumps(row) + "\n", encoding="utf-8")
        catalog.build_index(self.feed, self.index, knowledge=manifest)

        self.assertEqual(catalog.lookup_sku(self.index, "MAIL-A")[0].user_limit, 60)
        comparison = catalog.catalog_reply(self.index, "Сравни редакции Demo Mail")
        self.assertEqual(comparison.outcome, "answer")
        self.assertIn("Standard", comparison.text)

    def test_invalid_evidence_preserves_active_catalog(self):
        original = catalog.build_index(self.feed, self.index)
        self.feed.write_text(FEED.replace("Demo Mail Standard", "Changed title"), encoding="utf-8")
        cases = [
            (self.evidence(offer_id="missing"),),
            (self.evidence(scope="family"),),
            (self.evidence(sku="MAIL-A"),),
            (self.evidence(field="price"),),
            (self.evidence(source_url="file:///private/kb"),),
            (self.evidence(source_url="https://user:secret@docs.example/product-one"),),
            (self.evidence("user_limit", True),),
            (self.evidence("edition", "Other edition"),),
            (self.evidence(), self.evidence(value="cloud")),
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.write_manifest(*rows)
                with self.assertRaises(ValueError):
                    catalog.build_index(self.feed, self.index, knowledge=self.manifest)
                offer = catalog.lookup_offer(self.index, "one")
                self.assertEqual(offer.title, "Demo Mail Standard")
                self.assertIsNone(offer.deployment)
                self.assertEqual(offer.source_at, original.source_at.isoformat())

    def test_ambiguous_sku_is_rejected_instead_of_fanning_out(self):
        self.feed.write_text(FEED.replace("MAIL-B", "MAIL-A"), encoding="utf-8")
        row = self.evidence(scope="sku", sku="MAIL-A")
        del row["offer_id"]
        self.write_manifest(row)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            catalog.build_index(self.feed, self.index, knowledge=self.manifest)
        self.assertFalse(self.index.exists())

    def test_duplicate_manifest_keys_cannot_retarget_evidence(self):
        self.manifest.write_text(
            json.dumps([self.evidence()]).replace('"offer_id": "one"', '"offer_id": "one", "offer_id": "two"'),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            catalog.build_index(self.feed, self.index, knowledge=self.manifest)
        self.assertFalse(self.index.exists())

    def test_evidence_cannot_mask_conflicting_feed_parameters(self):
        self.feed.write_text(
            FEED.replace('</description>', '</description><param name="Deployment">cloud</param>'
                         '<param name="Deployment">on-premises</param>', 1),
            encoding="utf-8",
        )
        self.write_manifest(self.evidence())
        with self.assertRaisesRegex(ValueError, "conflict"):
            catalog.build_index(self.feed, self.index, knowledge=self.manifest)

    def test_cli_reports_before_and_after_coverage_without_listing_offer_data(self):
        self.write_manifest(self.evidence("user_limit", 60))
        command = subprocess.run(
            [sys.executable, "-m", "softline_backend.catalog", str(self.feed), str(self.index),
             "--knowledge", str(self.manifest), "--coverage"],
            check=True, capture_output=True, text=True,
        )
        report = json.loads(command.stdout)
        self.assertEqual(report["offer_count"], 2)
        self.assertEqual(report["missing_id_count"], 1)
        self.assertEqual(report["feed"]["verifiable_url"], 2)
        self.assertEqual(report["feed"]["rub_price"], 1)
        self.assertEqual(report["feed"]["user_limit"], 0)
        self.assertEqual(report["effective"]["user_limit"], 1)
        self.assertEqual(report["unmapped_parameter_names"], {"unmapped attribute": 1})
        self.assertNotIn("MAIL-A", command.stdout)
        self.assertNotIn("https://docs.example", command.stdout)

    def test_verified_task_candidates_use_explicit_capabilities_and_pack_size(self):
        self.write_manifest(
            self.evidence("capability", "file_protection"),
            self.evidence("user_limit", "60"),
            self.evidence(),
        )
        catalog.build_index(self.feed, self.index, knowledge=self.manifest)

        cards = catalog.find_verified_task_offers(
            self.index, capabilities=("email_protection", "file_protection"),
            user_limit=None, deployment=None, origin=None,
        )
        self.assertEqual({card.offer_id for card in cards}, {"one", "two"})
        by_id = {card.offer_id: {fact.field: fact.value for fact in card.verified_facts} for card in cards}
        self.assertEqual(by_id["one"]["capability"], "file_protection")
        self.assertNotIn("license_quantity", by_id["one"])
        self.assertEqual(by_id["two"]["capability"], "email_protection")
        self.assertEqual(by_id["two"]["license_quantity"], "80")
        self.assertEqual(by_id["two"]["price_basis"], "license_pack")

        cards = catalog.find_verified_task_offers(
            self.index, capabilities=("file_protection",),
            user_limit=50, deployment="локально", origin=None,
        )
        self.assertEqual([card.offer_id for card in cards], ["one"])

        cards = catalog.find_verified_task_offers(
            self.index, capabilities=("email_protection",),
            user_limit=None, deployment=None, origin=None,
        )
        self.assertEqual([card.offer_id for card in cards], ["two"])

    def test_mindbox_named_fields_and_offer_id_without_sku(self):
        self.feed.write_text(
            FEED.replace('<vendorCode>MAIL-A</vendorCode>', '')
            .replace('id="one" group_id="mail"', 'id="one"')
            .replace('<param name="Edition">Standard</param>',
                     '<group_id>mail</group_id><param name="Срок действия">12 мес.</param>'
                     '<param name="К-во пользователей до">50</param>')
            .replace('<currencyId>RUB</currencyId>', '<currencyId>RUR</currencyId>'),
            encoding="utf-8",
        )
        snapshot = catalog.build_index(self.feed, self.index, coverage=True)
        self.assertEqual(snapshot.coverage["feed"]["rub_price"], 1)
        self.assertEqual(snapshot.coverage["feed"]["group_id"], 2)
        self.assertEqual(catalog.lookup_sku(self.index, "one"), [])
        reply = catalog.catalog_reply(self.index, "ID предложения one")
        self.assertEqual(reply.outcome, "answer")
        self.assertIsNone(reply.products[0].sku)
        self.assertEqual(reply.products[0].currency, "RUB")
        facts = {fact.field: fact.value for fact in reply.products[0].verified_facts}
        self.assertEqual(facts, {"term": "12 мес.", "user_limit": "50"})

    def test_mindbox_doctype_is_allowed_without_loading_any_dtd(self):
        self.feed.write_text('<!DOCTYPE yml_catalog\nSYSTEM "shops.dtd">\n' + FEED, encoding="utf-8")
        original = catalog.build_index(self.feed, self.index)
        self.assertEqual(original.offer_count, 2)

        for declaration in (
            '<!DOCTYPE yml_catalog SYSTEM "https://example.com/shops.dtd">',
            '<!DOCTYPE yml_catalog SYSTEM "shops.dtd" [<!ENTITY x "external data">]>',
            '<!DOCTYPE yml_catalog PUBLIC "shops" "shops.dtd">',
        ):
            with self.subTest(declaration=declaration):
                self.feed.write_text(declaration + FEED, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    catalog.build_index(self.feed, self.index)
                self.assertEqual(catalog.lookup_offer(self.index, "one").sku, "MAIL-A")
