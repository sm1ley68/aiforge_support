import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import httpx

from softline_backend.catalog import build_index
from softline_backend.contracts import MessageView
from softline_backend.task_search import task_reply


def offer(sku, capabilities=(), *, quantity=None, price=9000, price_basis=True, term="12 месяцев"):
    params = "".join(f'<param name="Capability">{capability}</param>' for capability in capabilities)
    if quantity is not None:
        params += f'<param name="License quantity">{quantity}</param>'
        if price_basis:
            params += '<param name="Price basis">license_pack</param>'
    return f"""
        <offer id="{sku}" available="true">
          <name>Решение {sku}</name>
          <vendorCode>{sku}</vendorCode>
          <description>Защита почты и файлов</description>
          {params}
          <param name="Deployment">on-premise</param>
          <param name="User limit">100</param>
          <param name="Country of origin">Россия</param>
          <param name="License term">{term}</param>
          <price>{price}</price><currencyId>RUB</currencyId>
          <url>https://example.com/{sku}</url>
        </offer>"""


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.index = self.folder / "catalog.sqlite3"

    def build(self, *positions, knowledge=None):
        feed = self.folder / "offers.xml"
        feed.write_text(
            '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
            f'{"".join(positions)}</offers></shop></yml_catalog>',
            encoding="utf-8",
        )
        build_index(feed, self.index, knowledge=knowledge)

    @staticmethod
    def history(*messages):
        return [MessageView(turn_id=uuid4(), role="user", text=text) for text in messages]

    def test_natural_task_and_analogue_preserve_quantity_and_use_explicit_capability(self):
        self.build(
            offer("LEXICAL"),
            offer("VERIFIED", ("email_protection", "file_protection"), quantity=50),
        )
        history = self.history("Не знаю, что нужно, но хотим защитить почту и файлы на 50 сотрудников")
        result = task_reply(self.index, "А есть ли российский аналог?", history)
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, "recommend")
        self.assertEqual([product.sku for product in result.products], ["VERIFIED"])
        self.assertIn("50", result.text)

    def test_bundle_uses_two_proven_packs_and_checks_total_budget(self):
        self.build(
            offer("EMAIL", ("email_protection",), quantity=50, price=9000),
            offer("FILE", ("file_protection",), quantity=50, price=7000),
            offer("UNKNOWN", ("file_protection",), quantity=50, price=1, price_basis=False),
            offer("SMALL", ("file_protection",), quantity=25, price=1),
        )
        task = "Подбери защиту почты и файлов на 50 сотрудников"
        result = task_reply(self.index, task + ", бюджет до 16 000 рублей", [])
        self.assertEqual(result.outcome, "recommend")
        self.assertEqual({product.sku for product in result.products}, {"EMAIL", "FILE"})
        self.assertEqual(len(result.sources), 2)
        self.assertIn("16 000 ₽", result.text)
        lower_budget = task_reply(self.index, task + ", бюджет до 15 999 рублей", [])
        self.assertEqual(lower_budget.outcome, "clarify")
        self.assertEqual(lower_budget.products, [])

    def test_lexical_matches_are_answers_even_if_description_looks_like_proof(self):
        self.build(offer("LEXICAL"))
        result = task_reply(self.index, "Подбери защиту почты и файлов", [])
        self.assertEqual(result.outcome, "answer")
        self.assertEqual([product.sku for product in result.products], ["LEXICAL"])

    def test_missing_bundle_term_or_license_quantity_prevents_recommendation(self):
        self.build(
            offer("EMAIL", ("email_protection",), quantity=50, price=9000, term=""),
            offer("FILE", ("file_protection",), price=7000),
        )
        result = task_reply(self.index, "Подбери защиту почты и файлов на 50 сотрудников, бюджет до 16 000 рублей", [])
        self.assertEqual(result.outcome, "clarify")
        self.assertIn("лицензи", result.text)

    def test_manifest_capability_source_is_cited_with_recommended_offer(self):
        manifest = self.folder / "knowledge.json"
        manifest.write_text(json.dumps([{
            "scope": "offer",
            "offer_id": "VERIFIED",
            "field": "capability",
            "value": "email_protection",
            "source_url": "https://docs.example/mail",
            "source_title": "Документация по защите почты",
        }]), encoding="utf-8")
        self.build(offer("VERIFIED"), knowledge=manifest)
        result = task_reply(self.index, "Подбери защиту почты", [])
        self.assertEqual(result.outcome, "recommend")
        self.assertEqual(
            {str(source.url) for source in result.sources},
            {"https://example.com/VERIFIED", "https://docs.example/mail"},
        )


class TaskModelTests(unittest.TestCase):
    def test_polza_whole_request_is_cancelled_at_timeout(self):
        from softline_backend.task_extraction import PolzaTaskExtractor

        cancelled = []

        async def handle(_request):
            try:
                await asyncio.sleep(2)
            finally:
                cancelled.append(True)

        extractor = PolzaTaskExtractor("fake-key", timeout=0.01, transport=httpx.MockTransport(handle))
        self.assertIsNone(extractor("Нужна защита почты", []))
        self.assertEqual(cancelled, [True])

    def test_polza_requests_strict_schema_and_rejects_invented_facts(self):
        from softline_backend.task_extraction import PolzaTaskExtractor

        raw = {
            "intent": "task",
            "terms": ["шифрование"],
            "capabilities": [],
            "user_limit": 50,
            "deployment": "локально",
            "budget_rubles": 10000,
            "origin": "Россия",
            "missing": None,
        }
        requests = []

        def handle(request):
            requests.append(request)
            payload = json.loads(request.content)
            self.assertEqual(str(request.url), "https://polza.ai/api/v1/chat/completions")
            self.assertEqual(payload["response_format"]["type"], "json_schema")
            schema = payload["response_format"]["json_schema"]
            self.assertTrue(schema["strict"])
            self.assertFalse(schema["schema"]["additionalProperties"])
            self.assertNotIn("assistant context", request.content.decode())
            content = raw if len(requests) == 1 else raw | {"price": 100, "url": "https://bogus.example"}
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]})

        extractor = PolzaTaskExtractor("fake-key", transport=httpx.MockTransport(handle))
        history = [MessageView(turn_id=uuid4(), role="assistant", text="assistant context")]
        result = extractor("Нужен вариант шифрования для 50 человек в нашей инфраструктуре", history)
        self.assertEqual(result.user_limit, 50)
        self.assertIsNone(extractor("Нужен вариант шифрования", history))

    def test_free_text_structured_parse_is_used_only_to_search_and_prove_catalog_data(self):
        from softline_backend.task_extraction import TaskExtraction

        extraction = TaskExtraction(
            intent="task", terms=["почта"], capabilities=["email_protection"],
            user_limit=50, deployment="локально", budget_rubles=None, origin=None, missing=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "catalog.sqlite3"
            feed = Path(directory) / "catalog.xml"
            feed.write_text(
                '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
                + offer("GROUNDED", ("email_protection",), quantity=50)
                + '</offers></shop></yml_catalog>',
                encoding="utf-8",
            )
            build_index(feed, index)
            text = "Внутри собственной инфраструктуры надо обезопасить корпоративную переписку для 50 человек."
            result = task_reply(index, text, [], extractor=lambda *_: extraction)
            self.assertEqual(result.outcome, "recommend")
            self.assertEqual(result.products[0].sku, "GROUNDED")
            self.assertEqual(str(result.sources[0].url), "https://example.com/GROUNDED")
            self.assertIsNone(task_reply(index, text, [], extractor=lambda *_: None))

    def test_polza_http_error_falls_back_to_deterministic_search(self):
        from softline_backend.task_extraction import PolzaTaskExtractor

        def handle(_request):
            return httpx.Response(503)

        extractor = PolzaTaskExtractor("fake-key", transport=httpx.MockTransport(handle))
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "catalog.sqlite3"
            feed = Path(directory) / "catalog.xml"
            feed.write_text(
                '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
                + offer("LEXICAL")
                + '</offers></shop></yml_catalog>',
                encoding="utf-8",
            )
            build_index(feed, index)
            text = "Подбери защиту почты и файлов"
            result = task_reply(index, text, [], extractor=extractor)
            self.assertEqual(result, task_reply(index, text, []))
