import asyncio
from dataclasses import replace
import json
import unittest

from aisupport_ml.commerce import render_document
from aisupport_ml.commerce.mock import MockSupport, load_fixture
from aisupport_ml.commerce.retrieval import HybridSearch
from evals.run_commerce import CASES, FIXTURE, NOW, ReplayModel, evaluate


def case_of(id):
    return next(case for case in json.loads(CASES.read_text()) if case["id"] == id)


class CommerceTests(unittest.IsolatedAsyncioTestCase):
    async def test_replay_checks_all_synthetic_dialogues(self):
        from argparse import Namespace

        for case in json.loads(CASES.read_text()):
            with self.subTest(case=case["id"]):
                result = await evaluate(case, Namespace(fixture=FIXTURE), None, 1)
                self.assertTrue(result["passed"], result)

    async def test_concurrent_invoice_retry_and_document_access(self):
        case = case_of("direct_invoice")
        turn, = case["turns"]
        agent, customers = load_fixture(FIXTURE, ReplayModel(case["turns"]))
        store = MockSupport(agent)
        buyer = customers["BUY-1"]
        repeated = await asyncio.gather(*(
            store.reply("chat", "same", turn["text"], customer=buyer, now=NOW)
            for _ in range(2)
        ))
        self.assertIs(repeated[0], repeated[1])
        self.assertEqual(len(store.documents), 1)
        document = store.get_document("chat", repeated[0].document.id, customer=buyer)
        self.assertIn("Расчётный счёт", render_document(document))
        self.assertIn("3701.00", render_document(document))
        with self.assertRaises(PermissionError):
            store.get_document("chat", document.id, customer=customers["BUY-2"])
        with self.assertRaises(ValueError):
            await store.reply("chat", "same", "Новое сообщение", customer=buyer, now=NOW)

    async def test_handoff_queue_includes_history_and_cart(self):
        case = case_of("special_terms_missing")
        agent, customers = load_fixture(FIXTURE, ReplayModel(case["turns"]))
        store = MockSupport(agent)
        message = case["turns"][0]["text"]
        result = await store.reply("chat", "request", message, customer=customers["BUY-1"], now=NOW)
        handoff = store.manager_queue[result.handoff.id]
        self.assertEqual(handoff.history[-1].text, message)
        self.assertEqual(handoff.cart[0].sku, "VG-PRO")
        self.assertTrue(handoff.sources)
        self.assertEqual(len(store.documents), 0)

    async def test_model_failure_creates_handoff(self):
        class UnavailableModel:
            async def complete(self, system, text, schema):
                await asyncio.sleep(1)

        agent, customers = load_fixture(FIXTURE, UnavailableModel(), model_timeout=0.001)
        store = MockSupport(agent)
        result = await store.reply("chat", "turn", "Выпишите счёт", customer=customers["BUY-1"], now=NOW)
        self.assertEqual(result.handoff.reason, "extraction_unavailable")
        self.assertEqual(result.trace.calls[0].error, "TimeoutError")
        self.assertFalse(store.documents)


class CommerceRetrievalTests(unittest.TestCase):
    def test_article_stops_serving_when_parent_changes(self):
        agent, _ = load_fixture(FIXTURE, None)
        kb = agent.knowledge
        parent = kb.original["kb-download-invoice"]
        update = kb.learn(parent, NOW)
        self.assertEqual(update.status, "published")
        self.assertIn(update.id, kb.eligible(NOW, None, None))
        kb.original[parent.id] = replace(parent, version="2")
        self.assertNotIn(update.id, kb.eligible(NOW, None, None))

    def test_rrf_brings_in_semantic_match_with_controlled_vectors(self):
        agent, _ = load_fixture(FIXTURE, None)
        kb = agent.knowledge
        query = "Хочу получить платёжный документ"

        def encode(inputs, *, is_query):
            return [[1, 0] if is_query or "Скачать счёт" in text else [0, 1] for text in inputs]

        def rerank(pairs):
            return [int("Скачать счёт" in doc) for _, doc in pairs]

        hybrid = HybridSearch(encode, rerank)
        self.assertEqual(kb.search(query, NOW), ())
        results = hybrid(query, kb.eligible(NOW, None, None))
        self.assertEqual(results[0].id, "kb-download-invoice")
        self.assertNotIn("kb-old", {source.id for source in results})
