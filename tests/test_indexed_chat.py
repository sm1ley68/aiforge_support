from dataclasses import replace
from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4
from xml.sax.saxutils import escape

from aisupport_ml.commerce import CommerceAgent
from aisupport_ml.commerce.catalog import SoftlineCatalog, build_catalog
from aisupport_ml.commerce.indexed_chat import INDEXED_SCHEMA
from aisupport_ml.commerce.mock import MockSupport
from aisupport_ml.commerce.offer_evidence import OFFER_CARDS
from aisupport_ml.commerce.retrieval import KnowledgeBase
from aisupport_ml.commerce.softline_evidence import CATALOG_KNOWLEDGE
from aisupport_ml.contracts import TemporaryReadError, Usage
from softline_backend.commerce_bridge import CommerceBridge
from softline_backend.store import ClaimedTurn


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
            self.index_path = Path(override)
        else:
            temporary = TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            folder = Path(temporary.name)
            feed = folder / "feed.xml"
            index = folder / "catalog.sqlite"
            sample = [
                offer_xml("19578", "MDaemon Messaging Server, 40 пользователей", "94341", count="40"),
                offer_xml("19579", "MDaemon Messaging Server, 50 пользователей", "101171", count="50"),
                offer_xml("19580", "MDaemon Messaging Server, 60 пользователей", "108001", count="60"),
                offer_xml("19590", "MDaemon Messaging Server продление", "50585", kind="Продление", count="50"),
                offer_xml("19601", "MDaemon Messaging Server продление просроченной подписки", "80937",
                          kind="Продление", count="50"),
                offer_xml("359849", "MDaemon Connector for Outlook", "888", count="50"),
                offer_xml("5065", "Kaspersky Total Security для бизнеса базовая лицензия по количеству узлов", "7735.50",
                          code="KL4869RAPFS"),
                offer_xml("5057", "Kaspersky Total Security для бизнеса базовая лицензия по количеству узлов", "11601",
                          code="KL4869RAPDS", term="24 мес."),
                offer_xml("5066", "Kaspersky Total Security для бизнеса базовая лицензия по количеству узлов", "7691.40",
                          code="KL4869RAQFS"),
                offer_xml("5058", "Kaspersky Total Security для бизнеса базовая лицензия по количеству узлов", "11536.20",
                          code="KL4869RAQDS", term="24 мес."),
                offer_xml("339688", "Handy Backup Standard", "3080", code="HBS10", term=""),
                offer_xml("339675", "Handy Backup Professional", "4656", code="HBP10", term=""),
                offer_xml("339674", "Handy Backup Professional", "4930", code="HBP4-9", term=""),
                offer_xml("421471", "Кибер Бэкап Стандартная для рабочей станции Windows", "9066",
                          code="PCSCNL", term="бессрочная"),
                offer_xml("473583", "Microsoft Project Professional 2024, электронная лицензия на 1 ПК, бессрочная",
                          "176639", code="EP2-07001", kind="Full", term=""),
                offer_xml("541420", "PDF Commander Бизнес (бессрочная лицензия), Количество рабочих мест", "4900",
                          term="бессрочная"),
                offer_xml("541424", "PDF Commander Бизнес (подписка на 1 год), Количество рабочих мест", "2800",
                          kind="Подписка"),
            ]
            feed.write_text(f'<yml_catalog date="2026-11-25 14:12"><shop><offers>{"".join(sample)}</offers></shop></yml_catalog>',
                            encoding="utf-8")
            build_catalog(feed, index)
            self.index_path = index
        self.index = SoftlineCatalog(self.index_path)
        self.model = ExtractionStub()
        self.chat = MockSupport(CommerceAgent(self.model, knowledge=KnowledgeBase([]), catalog_index=self.index))

    async def test_smallest_sufficient_seat_package_keeps_license_types_distinct(self):
        compared = await self.chat.reply("seats", "1", "Нужен MDaemon на 49 пользователей")
        self.assertEqual({offer.offer_id for offer in compared.products}, {"19579", "19590", "19601"})
        self.assertTrue(all(offer.user_limit == 50 for offer in compared.products))

        new = await self.chat.reply("seats", "2", "Нужна новая лицензия")
        self.assertEqual([offer.offer_id for offer in new.products], ["19579"])
        expired = await self.chat.reply("seats", "3", "Продлить просроченную подписку")
        self.assertEqual([offer.offer_id for offer in expired.products], ["19601"])

    async def test_named_product_keeps_edition_and_seats_before_extraction(self):
        requested = await self.chat.reply("named", "1", "Интересует MDaemon Messaging Server Standard, 46 сотрудников")
        context = requested.state.catalog_context
        self.assertEqual(requested.outcome, "clarify")
        self.assertEqual((context.mode, context.product, context.edition, context.users),
                         ("named", "MDaemon Messaging Server", "Standard", 46))
        self.assertFalse(requested.products)

        compared = await self.chat.reply("named", "2", "Можно без привязки к редакции?")
        self.assertEqual(compared.state.catalog_context.users, 46)
        self.assertIsNone(compared.state.catalog_context.edition)
        self.assertEqual({offer.offer_id for offer in compared.products}, {"19579", "19590", "19601"})

        expired = await self.chat.reply("named", "3", "Подписка уже истекла")
        self.assertEqual([offer.offer_id for offer in expired.products], ["19601"])
        price = await self.chat.reply("named", "4", "А сколько это стоит?")
        self.assertEqual(price.outcome, "answer")
        self.assertEqual([offer.offer_id for offer in price.products], ["19601"])
        self.assertIn(f"{expired.products[0].price:.2f} RUB", price.text)
        self.assertTrue(all(not result.trace.calls for result in (requested, compared, expired, price)))

    async def test_unknown_edition_then_mdaemon_comparison_and_exact_sku(self):
        unknown = await self.chat.reply("md", "1", "Нужен MDaemon Standard на 50 пользователей")
        self.assertEqual(unknown.outcome, "clarify")
        self.assertIn("«Standard»", unknown.text)
        self.assertFalse(unknown.products)
        self.assertEqual(unknown.state.catalog_context.users, 50)
        self.assertEqual(unknown.sources[0].url, "https://mdaemon.com/products/mdaemon-email-server")

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

        self.model.expect("named", product="Windows Server 2019")
        options = await self.chat.reply("needs", "2", "Windows Server 2019, локально, бюджет до 650 тысяч рублей")
        self.assertEqual(options.outcome, "recommend")
        self.assertEqual(options.state.catalog_context.mode, "need")
        self.assertEqual(options.state.catalog_context.mail, "Exchange")
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

    async def test_security_recommendation_respects_node_price_tier(self):
        self.model.expect("need", goal="защитить почту и файлы")
        request = "Нужно защитить почту и файлы, Exchange, Windows Server, локально, 40 устройств, бюджет до 350 тысяч рублей"
        result = await self.chat.reply("security", "1", request)
        self.assertEqual([offer.vendor_code for offer in result.products], ["KL4869RAPFS"])
        self.assertIn("309420.00 RUB за 40 узлов", result.text)

    async def test_demo_flows_keep_working_during_provider_outage(self):
        class UnavailableModel:
            async def complete(self, system, text, schema):
                raise TemporaryReadError("offline")

        chat = MockSupport(CommerceAgent(UnavailableModel(), knowledge=KnowledgeBase([]), catalog_index=self.index))
        unknown = await chat.reply("md", "1", "Нужен MDaemon Standard на 50 пользователей")
        self.assertEqual(unknown.outcome, "clarify")
        self.assertIn("«Standard»", unknown.text)
        self.assertFalse(unknown.trace.calls)
        relaxed = await chat.reply("md", "unfiltered", "Покажите без фильтра по редакции")
        self.assertEqual(relaxed.outcome, "answer")
        self.assertEqual(relaxed.state.catalog_context.users, 50)
        self.assertIsNone(relaxed.state.catalog_context.edition)
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

    async def test_softline_help_matches_rephrased_questions_and_leaves_other_requests_open(self):
        agent = CommerceAgent(self.model, knowledge=KnowledgeBase(CATALOG_KNOWLEDGE), catalog_index=self.index)
        for message, path in (
            ("А где же скачать счёт на оплату?", "/invoices"),
            ("Подскажите, где найти ключ активации после покупки?", "/fulfillment"),
            ("Можно скачать УПД по заказу?", "/closing-documents"),
            ("Оплатить картой можно?", "/delivery_info/"),
        ):
            with self.subTest(message=message):
                result = await agent.reply("kb", message, message)
                self.assertEqual(result.outcome, "answer")
                self.assertTrue(result.sources[0].url.endswith(path))
                self.assertFalse(result.trace.calls)
        self.model.expect("other")
        unrelated = await agent.reply("kb", "custom", "Где скачать счёт и как автоматизировать выдачу ключей через API?")
        self.assertNotEqual(unrelated.outcome, "answer")
        self.assertFalse(unrelated.sources)

    async def test_desktop_recommendations_check_amount_platform_term_and_vendor_evidence(self):
        requirements = await self.chat.reply("projects", "1", "Нужно управление задачами для 20 пользователей")
        self.assertEqual(requirements.outcome, "clarify")
        self.assertIn("версия ОС", requirements.text)
        selected = await self.chat.reply("projects", "2", "Windows 11, 20 компьютеров, бюджет до 4 000 000 рублей")
        self.assertEqual([offer.offer_id for offer in selected.products], ["473583"])
        self.assertIn("3532780.00 RUB за 20 ПК", selected.text)
        self.assertTrue(any(source.id == "ms-project-2024" for source in selected.sources))
        self.assertFalse(selected.trace.calls)
        compatible = await self.chat.reply("projects", "3", "Подойдёт ли для Windows 10?")
        self.assertIn("подтверждена поддержка Windows 10", compatible.text)
        self.assertEqual(compatible.sources[-1].id, "ms-project-2024")
        term = await self.chat.reply("projects", "4", "Какой срок лицензии?")
        self.assertIn("бессрочная", term.text)
        self.assertFalse(term.trace.calls)

        pdf = await self.chat.reply("pdf", "1", "Нужен российский PDF-редактор на 3 ПК с Windows 11")
        self.assertEqual([offer.offer_id for offer in pdf.products], ["541424", "541420"])
        perpetual = await self.chat.reply("pdf", "2", "Только бессрочная")
        self.assertEqual([offer.offer_id for offer in perpetual.products], ["541420"])
        unsupported = await self.chat.reply("pdf", "3", "Нужна интеграция с 1С")
        self.assertEqual(unsupported.outcome, "clarify")
        self.assertFalse(unsupported.products)
        another_refinement = await self.chat.reply("pdf", "4", "Бюджет до 100 тысяч рублей")
        self.assertFalse(another_refinement.products)
        tier_unverified = await self.chat.reply("pdf-tier", "1", "PDF-редактор для 4 ПК на Windows 11")
        self.assertEqual(tier_unverified.outcome, "clarify")
        self.assertFalse(tier_unverified.products)

    async def test_catalog_verified_named_lookup_does_not_require_provider(self):
        answer = await self.chat.reply("exact-name", "1", "Нужен Microsoft Project Professional 2024")
        self.assertEqual([offer.offer_id for offer in answer.products], ["473583"])
        self.assertIn("за ПК", answer.text)
        self.assertFalse(answer.trace.calls)

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


    async def test_three_categories_expose_verified_license_details(self):
        class Offline:
            async def complete(self, *_):
                raise TemporaryReadError("no outbound calls")

        chat = MockSupport(CommerceAgent(Offline(), knowledge=KnowledgeBase([]), catalog_index=self.index))
        examples = (
            ("security", "Надо защитить почту и файлы, Exchange, Windows Server, локально, "
                         "40 устройств, бюджет до 350 тысяч рублей", "5065", "Базовая",
             "Тариф 25–49 узлов", 40, "309420.00"),
            ("backup", "Резервное копирование файлов, 10 компьютеров с Windows 11 на внешние диски, "
                       "бюджет до 40 тысяч рублей", "339688", "Standard",
             "1 ПК (тариф 10–999 ПК)", 10, "30800.00"),
            ("projects", "Нужно планирование проектов на 2 ПК с Windows 11", "473583", "Professional 2024",
             "1 ПК", 2, "353278.00"),
        )
        for key, query, offer_id, edition, size, quantity, price in examples:
            with self.subTest(category=key):
                result = await chat.reply(key, "1", query)
                self.assertEqual(result.outcome, "recommend")
                detail, = result.recommendations
                self.assertEqual((detail.offer_id, detail.edition, detail.package_size, detail.quantity, detail.total),
                                 (offer_id, edition, size, quantity, Decimal(price)))
                self.assertIn(detail.edition_source, result.sources)
                self.assertIn(detail.package_source, result.sources)
                self.assertTrue(any(source.sku == offer_id and "фид от" in source.title for source in result.sources))

        increased = await chat.reply("security", "2", "Теперь 50 узлов, бюджет до 650 тысяч рублей")
        self.assertEqual({detail.offer_id for detail in increased.recommendations}, {"5066", "5058"})
        term = await chat.reply("security", "3", "А на 24 месяца?")
        two_year, = term.recommendations
        self.assertEqual((two_year.offer_id, two_year.quantity, two_year.total), ("5058", 50, Decimal("576810.00")))
        outside_budget = await chat.reply("security", "4", "Бюджет до 450 тысяч рублей")
        self.assertEqual(outside_budget.outcome, "clarify")
        self.assertEqual(outside_budget.state.catalog_context.shown_offers, ())
        self.assertFalse(outside_budget.recommendations)

        sku = await chat.reply("security", "5", "Есть ли в наличии KL4869RAQDS?")
        self.assertEqual([offer.offer_id for offer in sku.products], ["5058"])
        self.assertIn("наличие по фиду от", sku.text)
        self.assertFalse(sku.trace.calls)

    async def test_card_fallback_requires_exact_sku_and_edition(self):
        ask = "Какой язык интерфейса у EP2-07001?"
        exact = await self.chat.reply("card", "1", ask)
        self.assertIn("русская версия", exact.text)
        self.assertEqual(exact.sources[-1].id, "softline-card-project-2024")
        self.assertFalse(exact.trace.calls)

        term = await self.chat.reply("card", "2", "Какой срок лицензии у EP2-07001?")
        self.assertEqual(term.sources[-1].id, "softline-card-project-2024")
        for wrong in ({"sku": "ANOTHER-SKU"}, {"edition": "Microsoft Project Standard 2024"}):
            record = replace(OFFER_CARDS["473583"], **wrong)
            with patch.dict(OFFER_CARDS, {"473583": record}):
                result = await self.chat.reply("unmatched", str(wrong), ask)
                self.assertEqual(result.outcome, "handoff")
                self.assertNotIn("русская версия", result.text)
                self.assertEqual([source.id for source in result.sources], ["softline-offer-473583"])

    async def test_support_answers_follow_topic_and_escalate_only_when_needed(self):
        chat = MockSupport(CommerceAgent(self.model, knowledge=KnowledgeBase(CATALOG_KNOWLEDGE),
                                         catalog_index=self.index))
        for key, query, evidence, follow_up in (
            ("keys", "Откуда взять ключ после покупки?", "softline-lk-keys", "Зашёл в кабинет, ключа всё ещё нет"),
            ("activation", "Софт выдаёт ошибку при активации", "softline-lk-activation-instructions", "Не помогло"),
            ("returns", "Как мне вернуть деньги за лицензию?", "softline-store-return-instructions",
             "Не удалось оформить возврат, проверьте мой заказ"),
        ):
            with self.subTest(topic=key):
                first = await chat.reply(key, "1", query)
                self.assertEqual(first.outcome, "answer")
                self.assertEqual(first.sources[0].id, evidence)
                handoff = await chat.reply(key, "2", follow_up)
                self.assertEqual(handoff.outcome, "handoff")
                self.assertEqual(handoff.handoff.reason, "support_follow_up")
                self.assertEqual(handoff.sources[0].id, evidence)
                self.assertEqual(len(handoff.handoff.history), 3)
                self.assertFalse(first.trace.calls or handoff.trace.calls)

        order = await chat.reply("order", "1", "Проверьте ключ по заказу №12345")
        self.assertEqual(order.handoff.reason, "support_follow_up")
        unrelated = "Как получить ключ для SSH?"
        self.model.expect("other")
        result = await chat.reply("activation", "3", unrelated)
        self.assertEqual(result.outcome, "clarify")
        self.assertFalse(result.sources)

        await chat.reply("switch", "1", "Что делать, если не пришёл ключ?")
        switched = await chat.reply("switch", "2", "Как вернуть деньги за лицензию?")
        self.assertEqual(switched.outcome, "answer")
        self.assertEqual(switched.sources[0].url, "https://store.softline.ru/delivery_info/")
        new_product = await chat.reply("switch", "3", "Артикул EP2-07001")
        self.assertEqual(new_product.products[0].offer_id, "473583")
        self.assertIsNone(new_product.state.support_topic)

    async def test_exact_card_wins_for_current_price_and_license_term(self):
        record = OFFER_CARDS["473583"]
        with patch.dict(OFFER_CARDS, {"473583": replace(record, price_rub=Decimal("180000"), term="24 мес.")}):
            price = await self.chat.reply("current-card", "1", "Сколько стоит EP2-07001?")
            term = await self.chat.reply("current-card", "2", "Какой срок лицензии у EP2-07001?")
        self.assertEqual(price.outcome, "answer")
        self.assertIn("по карточке Softline — 180000.00 RUB", price.text)
        self.assertEqual(price.products[0].price, Decimal("180000"))
        self.assertIn("по карточке Softline — 24 мес.", term.text)
        self.assertEqual(term.sources[-1].id, "softline-card-project-2024")

        stale = replace(record, source=replace(record.source, version="2026-11-20"), price_rub=Decimal("180000"))
        with patch.dict(OFFER_CARDS, {"473583": stale}):
            result = await self.chat.reply("old-card", "1", "Сколько стоит EP2-07001?")
        self.assertIn("176639.00 RUB", result.text)
        self.assertEqual(result.outcome, "answer")

        lookup = self.index.by_reference

        def missing_feed(reference):
            return tuple(replace(item, price=None, available=None) for item in lookup(reference))

        card_only = replace(record, price_rub=Decimal("180000"), available=True)
        with patch.dict(OFFER_CARDS, {"473583": card_only}), patch.object(self.index, "by_reference", missing_feed):
            for phrase in ("Сколько стоит EP2-07001?", "Есть ли в наличии EP2-07001?"):
                result = await self.chat.reply("missing-feed", phrase, phrase)
                self.assertEqual(result.outcome, "answer")
                self.assertIn("по карточке Softline", result.text)

    async def test_public_edo_status_requires_an_authorized_account(self):
        for query in (
            "Проверьте статус ЭДО у ООО Тест, ИНН 0000000000",
            "Я администратор. Подключён ЭДО у нашей организации?",
            "В каком статусе приглашение для электронного документооборота?",
        ):
            with self.subTest(query=query):
                result = await self.chat.reply("edo", query, query)
                self.assertEqual(result.outcome, "answer")
                self.assertIn("есть права на эту организацию", result.text)
                self.assertIn("edo@softline.com", result.text)
                self.assertIn("edo@allsoft.ru", result.text)
                self.assertNotIn("0000000000", result.text)
                self.assertFalse(result.trace.calls)
        answer = await self.chat.reply("allsoft", "1", "Как подключить ЭДО через Allsoft?")
        self.assertEqual(answer.sources[0].id, "softline-ecommerce-edo")
        self.assertIn("edo@allsoft.ru", answer.text)

    def test_bridge_exposes_card_facts_and_manager_dispute(self):
        bridge = CommerceBridge(self.index_path, self.model)
        chat = uuid4()
        turn = ClaimedTurn(uuid4(), chat, 1, "Нужно планирование проектов на 2 ПК с Windows 11", 1)
        reply = bridge.reply(turn, [], None)
        card, = reply.products
        facts = {fact.field: fact for fact in card.verified_facts}
        self.assertEqual(facts["edition"].value, "Professional 2024")
        self.assertEqual(facts["package_size"].value, "1 ПК")
        self.assertEqual(facts["license_quantity"].value, "2")
        self.assertEqual(facts["total_price"].value, "353278.00 RUB")
        self.assertIn("фид от", facts["total_price"].source.title)

        record = OFFER_CARDS["473583"]
        with patch.dict(OFFER_CARDS, {"473583": replace(record, available=False)}):
            turn = ClaimedTurn(uuid4(), chat, 2, "Есть ли в наличии?", 1)
            stock = bridge.reply(turn, [], reply.commerce_state)
        self.assertEqual(stock.outcome, "answer")
        self.assertFalse(stock.products[0].availability)
        self.assertTrue(any(fact.field == "availability" and fact.source.title.startswith("Карточка Softline")
                            for fact in stock.products[0].verified_facts))

        question = "Есть ли в наличии EP2-07001?"
        disputed = replace(record, conflicts=frozenset({"availability"}))
        with patch.dict(OFFER_CARDS, {"473583": disputed}):
            turn = ClaimedTurn(uuid4(), chat, 3, question, 1)
            handoff = bridge.reply(turn, [], stock.commerce_state)
        self.assertEqual(handoff.outcome, "handoff")
        self.assertIn("наличие", handoff.handoff.requirements["Спорный факт"])
        self.assertEqual(handoff.handoff.requirements["Вопрос клиента"], question)
        self.assertEqual(handoff.handoff.candidate_ids, ["473583"])
        self.assertEqual(len(handoff.handoff.evidence), 2)
