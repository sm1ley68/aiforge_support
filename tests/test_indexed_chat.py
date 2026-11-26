import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.sax.saxutils import escape

from aisupport_ml.commerce import CommerceAgent
from aisupport_ml.commerce.catalog import SoftlineCatalog, build_catalog
from aisupport_ml.commerce.indexed_chat import INDEXED_SCHEMA
from aisupport_ml.commerce.mock import MockSupport
from aisupport_ml.commerce.retrieval import KnowledgeBase
from aisupport_ml.commerce.softline_evidence import CATALOG_KNOWLEDGE
from aisupport_ml.contracts import TemporaryReadError, Usage


class ExtractionStub:
    def __init__(self):
        self.responses = []

    def expect(self, action, **fields):
        response = dict.fromkeys(INDEXED_SCHEMA["properties"])
        self.responses.append({**response, "action": action, **fields})

    async def complete(self, system, text, schema):
        if not self.responses:
            raise AssertionError("Unexpected model call")
        return self.responses.pop(0), Usage(3, 2)


def offer_xml(id, title, price, *, code="", term="12 мес.", kind="Полная версия", count=""):
    return f'''<offer id="{id}" available="true">
    <name>{escape(title)}</name><url>https://store.softline.ru/test/{id}/</url>
    <vendorCode>{code}</vendorCode><price>{price}</price><currencyId>RUR</currencyId>
    <param name="Срок действия">{term}</param><param name="Тип лицензии">{kind}</param>
    <param name="К-во пользователей до">{count}</param>
    </offer>'''


class IndexedChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        override = os.environ.get("SOFTLINE_CHAT_TEST_INDEX")
        if override:
            self.index = SoftlineCatalog(Path(override))
        else:
            temporary = TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            folder = Path(temporary.name)
            feed = folder / "feed.xml"
            index = folder / "catalog.sqlite"
            sample = [
                offer_xml("19579", "MDaemon Messaging Server, 50 пользователей", "101171", count="50"),
                offer_xml("19590", "MDaemon Messaging Server продление", "50585", kind="Продление", count="50"),
                offer_xml("19601", "MDaemon Messaging Server продление другой лицензии", "80937", kind="Продление", count="50"),
                offer_xml("5066", "Kaspersky Total Security для бизнеса базовая лицензия по количеству узлов", "7691.40",
                          code="KL4869RAQFS"),
                offer_xml("5058", "Kaspersky Total Security для бизнеса базовая лицензия по количеству узлов", "11536.20",
                          code="KL4869RAQDS", term="24 мес."),
                offer_xml("339688", "Handy Backup Standard", "3080", code="HBS10", term=""),
                offer_xml("339675", "Handy Backup Professional", "4656", code="HBP10", term=""),
                offer_xml("339674", "Handy Backup Professional", "4930", code="HBP4-9", term=""),
                offer_xml("421471", "Кибер Бэкап Стандартная для рабочей станции Windows", "9066",
                          code="PCSCNL", term="бессрочная"),
            ]
            feed.write_text(f'<yml_catalog date="2026-11-25 14:12"><shop><offers>{"".join(sample)}</offers></shop></yml_catalog>',
                            encoding="utf-8")
            build_catalog(feed, index)
            self.index = SoftlineCatalog(index)
        self.model = ExtractionStub()
        self.chat = MockSupport(CommerceAgent(self.model, knowledge=KnowledgeBase([]), catalog_index=self.index))

    async def test_unknown_edition_then_mdaemon_comparison_and_exact_sku(self):
        self.model.expect("named", product="MDaemon")
        unknown = await self.chat.reply("md", "1", "Нужен MDaemon Standard на 50 пользователей")
        self.assertEqual(unknown.outcome, "clarify")
        self.assertIn("«Standard»", unknown.text)
        self.assertFalse(unknown.products)
        self.assertEqual(unknown.state.catalog_context.users, 50)

        self.model.expect("named", product="MDaemon Messaging Server")
        matched = await self.chat.reply("md", "2", "MDaemon Messaging Server на 50 пользователей, без привязки к редакции")
        self.assertEqual(matched.outcome, "answer")
        self.assertTrue({"19579", "19590", "19601"} <= {offer.offer_id for offer in matched.products})
        self.assertTrue(all(offer.user_limit == 50 for offer in matched.products))
        self.assertTrue(all(source.url.startswith("https://store.softline.ru/") for source in matched.sources))

        sku = await self.chat.reply("md", "3", "Сколько стоит 19579?")
        self.assertEqual([item.offer_id for item in sku.products], ["19579"])
        self.assertIn("101171.00 RUB", sku.text)
        self.assertFalse(sku.trace.calls)

        self.model.expect("named", product="MDaemon Messaging Server")
        incompatible = await self.chat.reply("linux", "1", "Нужен MDaemon Messaging Server на 50 пользователей под Linux")
        self.assertEqual(incompatible.outcome, "clarify")
        self.assertFalse(incompatible.products)

    async def test_recommendation_context_budget_origin_and_handoff(self):
        self.model.expect("need", goal="защитить почту и файлы")
        first = await self.chat.reply("needs", "1", "Хотим защитить почту и файлы на 50 сотрудников")
        self.assertEqual(first.outcome, "clarify")
        self.assertEqual(first.state.catalog_context.users, 50)
        self.assertIsNone(first.state.catalog_context.nodes)
        self.assertIn("узлов", first.text)
        self.assertFalse(first.products)

        self.model.expect("continue", mail="Exchange")
        partial = await self.chat.reply("needs", "count", "Exchange, 50 узлов")
        self.assertEqual(partial.text, "Какая ОС у файлового сервера?")
        self.assertEqual(partial.state.catalog_context.nodes, 50)

        self.model.expect("continue", mail="Exchange", file_os="Windows Server 2019")
        options = await self.chat.reply("needs", "2", "Exchange и Windows Server 2019, локально, 50 узлов, бюджет до 650 тысяч рублей")
        self.assertEqual(options.outcome, "recommend")
        self.assertEqual({item.offer_id for item in options.products}, {"5066", "5058"})
        self.assertIn("384570.00 RUB за 50 узлов", options.text)

        origin = await self.chat.reply("needs", "origin", "А российский аналог?")
        self.assertEqual(origin.state.catalog_context.budget_rub, 650_000)
        self.assertEqual({item.offer_id for item in origin.products}, {"5066", "5058"})
        self.assertFalse(origin.trace.calls)

        self.model.expect("continue")
        filtered = await self.chat.reply("needs", "3", "А российский аналог? Бюджет до 450 тысяч рублей.")
        self.assertEqual([item.offer_id for item in filtered.products], ["5066"])
        self.assertEqual(filtered.state.catalog_context.nodes, 50)
        self.assertEqual(filtered.state.catalog_context.mail, "Exchange")
        self.assertTrue(filtered.state.catalog_context.russian_only)
        self.assertTrue(any("/registry" in source.url for source in filtered.sources))

        handed = await self.chat.reply("needs", "4", "Согласуете индивидуальную скидку?")
        self.assertEqual(handed.outcome, "handoff")
        self.assertEqual(handed.handoff.catalog_context.shown_offers, ("5066",))
        self.assertEqual(handed.handoff.history[-1].text, "Согласуете индивидуальную скидку?")
        self.assertEqual([source.sku for source in handed.handoff.sources], ["5066"])
        repeated = await self.chat.reply("needs", "4", "Согласуете индивидуальную скидку?")
        self.assertIs(handed, repeated)
        self.assertEqual(len(self.chat.manager_queue), 1)

    async def test_demo_flows_keep_working_during_provider_outage(self):
        class UnavailableModel:
            async def complete(self, system, text, schema):
                raise TemporaryReadError("offline")

        chat = MockSupport(CommerceAgent(UnavailableModel(), knowledge=KnowledgeBase([]), catalog_index=self.index))
        unknown = await chat.reply("md", "1", "Нужен MDaemon Standard на 50 пользователей")
        self.assertEqual(unknown.outcome, "clarify")
        self.assertIn("«Standard»", unknown.text)
        self.assertEqual(unknown.trace.calls[0].error, "TemporaryReadError")
        offers = await chat.reply("md", "2", "MDaemon Messaging Server на 50 пользователей, без привязки к редакции")
        self.assertEqual(offers.outcome, "answer")
        self.assertTrue({"19579", "19590", "19601"} <= {item.offer_id for item in offers.products})
        need = await chat.reply("need", "1", "Не знаю, что нужно, но хотим защитить почту и файлы на 50 сотрудников")
        self.assertEqual(need.outcome, "clarify")
        self.assertIn("узлов", need.text)
        recommended = await chat.reply("need", "2", "Exchange и Windows Server 2019, локально, 50 узлов, бюджет до 650 тысяч рублей")
        self.assertEqual({item.offer_id for item in recommended.products}, {"5066", "5058"})
        changed = await chat.reply("need", "3", "Теперь не локально, нужно в облаке")
        self.assertEqual(changed.outcome, "clarify")
        self.assertFalse(changed.products)
        linux = await chat.reply("new-md", "1", "Нужен MDaemon Messaging Server на 50 пользователей под Linux")
        self.assertEqual(linux.outcome, "clarify")
        self.assertFalse(linux.products)
        antivirus = await chat.reply("platform", "1", "Нужен антивирус для Windows")
        self.assertEqual(antivirus.outcome, "clarify")
        self.assertEqual(antivirus.state.catalog_context.file_os, "Windows")
        self.assertIn("сколько устройств", antivirus.text)
        self.assertFalse(antivirus.products)
        windows = await chat.reply("known-windows", "1", "Нужен Windows Server 2022")
        self.assertEqual(windows.state.catalog_context.product, "Windows Server 2022")
        self.assertIsNone(windows.state.catalog_context.file_os)
        other = await chat.reply("different", "1", "Как автоматизировать выставление счетов?")
        self.assertEqual(other.handoff.reason, "extraction_unavailable")

    async def test_platform_requirement_does_not_become_a_product(self):
        self.model.expect("named", product="Windows")
        needs = await self.chat.reply("platform", "1", "Нужен антивирус для Windows")
        self.assertEqual(needs.outcome, "clarify")
        self.assertEqual(needs.state.catalog_context.mode, "need")
        self.assertEqual(needs.state.catalog_context.goal, "антивирус")
        self.assertEqual(needs.state.catalog_context.file_os, "Windows")
        self.assertIsNone(needs.state.catalog_context.product)
        self.assertFalse(needs.products)

        self.model.expect("named", product="Windows Server", file_os="Windows Server")
        selected = await self.chat.reply("product", "1", "Нужен Windows Server")
        self.assertEqual(selected.state.catalog_context.mode, "named")
        self.assertEqual(selected.state.catalog_context.product, "Windows Server")
        self.assertIsNone(selected.state.catalog_context.file_os)

    async def test_bare_price_resolves_one_card_or_asks_which_one(self):
        no_context = await self.chat.reply("price", "1", "А сколько стоит?")
        self.assertEqual(no_context.outcome, "clarify")
        self.assertIn("название или артикул", no_context.text)
        self.assertFalse(no_context.trace.calls)

        await self.chat.reply("price", "2", "19579")
        price = await self.chat.reply("price", "3", "А сколько стоит?")
        self.assertEqual(price.outcome, "answer")
        self.assertIn("101171.00 RUB", price.text)
        self.assertEqual([offer.offer_id for offer in price.products], ["19579"])
        self.assertFalse(price.trace.calls)

        self.model.expect("fact", fact="price")
        unresolved = await self.chat.reply("price", "unspecified", "Какая цена Kaspersky Total Security?")
        self.assertEqual(unresolved.outcome, "clarify")
        self.assertFalse(unresolved.products)

        self.model.expect("fact", product="19579", fact="availability")
        fact = await self.chat.reply("fact", "1", "Доступен ли товар с кодом 19579?")
        self.assertEqual(fact.outcome, "answer")
        self.assertIn("наличие по фиду", fact.text)
        self.assertEqual([source.sku for source in fact.sources], ["19579"])

        self.model.expect("named", product="MDaemon Messaging Server")
        multiple = await self.chat.reply("price", "4", "MDaemon Messaging Server на 50 пользователей")
        self.assertGreater(len(multiple.products), 1)
        choice = await self.chat.reply("price", "5", "А сколько стоит?")
        self.assertEqual(choice.outcome, "clarify")
        self.assertIn("О каком варианте", choice.text)
        self.assertEqual(choice.state.catalog_context.shown_offers, multiple.state.catalog_context.shown_offers)
        self.assertFalse(choice.trace.calls)

    async def test_reviewed_knowledge_answers_without_a_model_call(self):
        agent = CommerceAgent(self.model, knowledge=KnowledgeBase(CATALOG_KNOWLEDGE), catalog_index=self.index)
        delivery = await agent.reply("kb", "1", "Как я получу электронную лицензию?")
        self.assertEqual(delivery.outcome, "answer")
        self.assertIn("электронной почты", delivery.text)
        self.assertEqual(delivery.sources[0].url, "https://store.softline.ru/delivery_info/")
        self.assertFalse(delivery.trace.calls)

        product = await agent.reply("kb", "2", "Kaspersky Total Security для бизнеса защищает Microsoft Exchange?")
        self.assertEqual(product.outcome, "answer")
        self.assertIn("Microsoft Exchange", product.text)
        self.assertTrue(product.sources[0].url.startswith("https://store.softline.ru/kaspersky/"))
        self.assertFalse(product.trace.calls)

    async def test_backup_uses_verified_licenses_for_changes_in_scope_budget_and_count(self):
        first = await self.chat.reply("backup", "1", "Подберите решение для резервного копирования")
        self.assertEqual(first.outcome, "clarify")
        self.assertIn("файлы и папки", first.text)

        second = await self.chat.reply("backup", "2", "Только файлы и папки, 10 компьютеров с Windows 11")
        self.assertEqual(second.outcome, "clarify")
        self.assertIn("локальном накопителе", second.text)
        self.assertEqual(second.state.catalog_context.nodes, 10)

        options = await self.chat.reply("backup", "3", "На внешние диски, бюджет до 100 тысяч рублей")
        self.assertEqual(options.outcome, "recommend")
        self.assertEqual([offer.vendor_code for offer in options.products], ["HBS10", "PCSCNL"])
        self.assertIn("30800.00 RUB за 10 ПК", options.text)
        self.assertIn("90660.00 RUB за 10 ПК", options.text)
        self.assertTrue(any("handybackup.ru" in source.url for source in options.sources))
        self.assertTrue(any("docs.cyberprotect.ru" in source.url for source in options.sources))
        self.assertFalse(options.trace.calls)

        cheaper = await self.chat.reply("backup", "4", "Бюджет до 40 тысяч рублей")
        self.assertEqual([offer.vendor_code for offer in cheaper.products], ["HBS10"])
        unavailable = await self.chat.reply("backup", "5", "Теперь нужен образ диска")
        self.assertEqual(unavailable.outcome, "clarify")
        self.assertFalse(unavailable.products)
        self.assertFalse(unavailable.state.catalog_context.shown_offers)
        self.assertEqual(unavailable.state.catalog_context.budget_rub, 40_000)

        expanded = await self.chat.reply("backup", "6", "Бюджет до 60 тысяч рублей")
        self.assertEqual([offer.vendor_code for offer in expanded.products], ["HBP10"])
        self.assertIn("46560.00 RUB за 10 ПК", expanded.text)
        fewer = await self.chat.reply("backup", "7", "В итоге 8 компьютеров")
        self.assertEqual([offer.vendor_code for offer in fewer.products], ["HBP4-9"])
        self.assertIn("39440.00 RUB за 8 ПК", fewer.text)

        self.model.expect("named", product="MDaemon Messaging Server")
        other = await self.chat.reply("backup", "8", "Нужен MDaemon Messaging Server под Linux")
        self.assertEqual(other.state.catalog_context.mode, "named")
        self.assertIsNone(other.state.catalog_context.backup_scope)

    async def test_backup_preserves_required_license_and_excludes_unverified_targets(self):
        result = await self.chat.reply(
            "backup", "1", "Нужно резервное копирование файлов для 10 ПК с Windows 11. "
            "Хранение локально, бюджет до 100 тысяч рублей, нужна бессрочная лицензия.",
        )
        self.assertEqual([offer.vendor_code for offer in result.products], ["PCSCNL"])
        cloud = await self.chat.reply("backup", "2", "Теперь только облако")
        self.assertEqual(cloud.outcome, "clarify")
        self.assertFalse(cloud.products)
        self.assertFalse(cloud.state.catalog_context.shown_offers)

        unsupported = await self.chat.reply(
            "outside", "1", "Нужны резервные копии базы данных 1С на 10 ПК с Windows 11, локально, бюджет до 100 тысяч рублей",
        )
        self.assertEqual(unsupported.outcome, "clarify")
        self.assertFalse(unsupported.products)
