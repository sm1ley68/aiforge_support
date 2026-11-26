import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.sax.saxutils import escape

from aisupport_ml.commerce import CommerceAgent
from aisupport_ml.commerce.catalog import SoftlineCatalog, build_catalog
from aisupport_ml.commerce.mock import MockSupport
from aisupport_ml.commerce.retrieval import KnowledgeBase
from aisupport_ml.contracts import TemporaryReadError, Usage


class ExtractionStub:
    def __init__(self):
        self.responses = []

    def expect(self, action, **fields):
        response = dict.fromkeys(("product", "edition", "goal", "mail", "file_os"))
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
        other = await chat.reply("different", "1", "Как автоматизировать выставление счетов?")
        self.assertEqual(other.handoff.reason, "extraction_unavailable")
