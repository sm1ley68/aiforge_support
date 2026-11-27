import asyncio
import json
import os
import unittest
from dataclasses import asdict
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

import httpx

from aisupport_ml.commerce.contracts import CatalogContext
from aisupport_ml.commerce.indexed_chat import INDEXED_SCHEMA
from aisupport_ml.contracts import TemporaryReadError
from softline_backend.commerce_bridge import CatalogModel, CommerceBridge
from softline_backend.contracts import MessageView
from softline_backend.polza_egress import TurnScope, _screen_with_ml, load_egress_filter, polza_scope
from softline_backend.store import ClaimedTurn
from softline_backend.worker import reply_from_env


TECHNICAL = {
    "decision": "allow",
    "fields": {"task": "backup", "platform": "windows_11", "device_count": 10, "deployment": "local"},
    "cleaned_text": "Секрет из локального фильтра, который не должен попасть в запрос",
}
MESSAGE = "Прошу помочь. Нужно резервное копирование для 10 ПК с Windows 11, локально"
MODEL_RESPONSE = {
    "action": "need", "fact": None, "product": None, "edition": None,
    "goal": "резервное копирование", "mail": None, "file_os": "Windows 11",
}


class EgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests = []
        self.output = MODEL_RESPONSE
        self.scope = TurnScope("test-turn", MESSAGE, (), None)

    def receive(self, request):
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.output)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        })

    async def complete(self, checker=None, *, enabled=True, candidate=None):
        model = CatalogModel(
            "fake-key", "anthropic/claude-haiku-5.5", enabled=enabled, checker=checker,
            transport=httpx.MockTransport(self.receive),
        )
        token = polza_scope.set(self.scope)
        try:
            return await model.complete(
                "THIS MUST NOT BE SENT", json.dumps(candidate or {"message": MESSAGE, "selection": None}),
                INDEXED_SCHEMA,
            )
        finally:
            polza_scope.reset(token)

    async def test_actual_body_contains_only_allowlisted_projection(self):
        async def allow(scope):
            self.assertEqual(scope.message, MESSAGE)
            return TECHNICAL

        with patch.dict(os.environ, LLM_BASE_URL="https://polza.ai/api/v1"):
            result, usage = await self.complete(allow)
        self.assertEqual(result, MODEL_RESPONSE)
        self.assertEqual(usage.input_tokens, 10)
        request, = self.requests
        self.assertEqual(request["messages"][1]["content"],
                         "Нужно резервное копирование для 10 ПК с Windows 11, локально")
        self.assertNotIn("Секрет", json.dumps(request, ensure_ascii=False))
        self.assertNotIn("THIS MUST NOT BE SENT", json.dumps(request))
        self.assertNotIn("Прошу помочь", json.dumps(request, ensure_ascii=False))

    async def test_key_alone_and_missing_filter_do_not_open_network(self):
        async def allow(_scope):
            return TECHNICAL

        for checker, enabled in ((None, True), (allow, False)):
            with self.assertRaises(TemporaryReadError):
                await self.complete(checker, enabled=enabled)
        self.assertEqual(self.requests, [])

    async def test_scope_checks_old_history_saved_state_and_engine_candidate(self):
        async def allow(_scope):
            return TECHNICAL

        for history, state, candidate in (
            (("Телефон +7 999 123-45-67",), None, None),
            ((), {"catalog_context": {"goal": "Контакт +7 999 123-45-67"}}, None),
            ((), None, {"message": MESSAGE, "selection": {"name": "test@example.invalid"}}),
        ):
            self.scope = TurnScope("test-turn", MESSAGE, history, state)
            for _ in range(2):
                with self.assertRaises(TemporaryReadError):
                    await self.complete(allow, candidate=candidate)
        self.assertEqual(self.requests, [])

    async def test_filter_error_uncertainty_and_bad_projection_are_closed(self):
        async def crash(_scope):
            raise RuntimeError("do not log test@example.invalid")

        async def uncertain(_scope):
            return {"decision": "uncertain"}

        async def false_allow(_scope):
            return {**TECHNICAL, "fields": {**TECHNICAL["fields"], "platform": "[ТЕЛЕФОН]"}}

        with self.assertLogs("softline_backend.polza_egress", level="INFO") as logs:
            for checker in (crash, uncertain, false_allow):
                with self.assertRaises(TemporaryReadError):
                    await self.complete(checker)
        self.assertEqual(self.requests, [])
        logged = " ".join(logs.output)
        self.assertNotIn("test@example.invalid", logged)
        self.assertNotIn(MESSAGE, logged)

    async def test_invalid_model_values_cannot_enter_catalog_state(self):
        async def allow(_scope):
            return TECHNICAL

        self.output = {**MODEL_RESPONSE, "product": "[ФИО]"}
        with patch.dict(os.environ, LLM_BASE_URL="https://polza.ai/api/v1"):
            with self.assertRaises(TemporaryReadError):
                await self.complete(allow)
        self.assertEqual(len(self.requests), 1)

    async def test_old_mode_never_calls_http_even_with_key_and_real_mode(self):
        with (
            patch.dict(os.environ, CATALOG_INDEX_PATH="/unused", POLZA_API_KEY="fake-key", POLZA_EGRESS_MODE="real"),
            patch("softline_backend.worker.product_question_reply", return_value=None),
            patch("softline_backend.worker.catalog_reply", return_value=None),
            patch("softline_backend.worker.task_reply", return_value=None) as local,
            patch("httpx.AsyncClient.post") as post,
        ):
            result = reply_from_env()(MESSAGE, [])
        self.assertEqual(result.outcome, "clarify")
        self.assertEqual(local.call_count, 1)
        self.assertNotIn("extractor", local.call_args.kwargs)
        post.assert_not_called()


    async def test_explicit_filter_deny_timeout_and_wrong_destination_never_send(self):
        async def deny(_scope):
            return {"decision": "block"}

        async def expired(_scope):
            await asyncio.sleep(1)
            return TECHNICAL

        async def allow(_scope):
            return TECHNICAL

        with patch("softline_backend.polza_egress.FILTER_TIMEOUT_SECONDS", 0.005):
            for checker in (deny, expired):
                with self.assertRaises(TemporaryReadError):
                    await self.complete(checker)
        with patch.dict(os.environ, LLM_BASE_URL="https://wrong.example.invalid/api"):
            with self.assertRaises(TemporaryReadError):
                await self.complete(allow)
        self.assertEqual(self.requests, [])


    @unittest.skipUnless(find_spec("natasha") is not None, "requires the local privacy extra")
    async def test_teammate_filter_blocks_found_name_even_with_technical_payload(self):
        config = {"LLM_BASE_URL": "https://polza.ai/api/v1", "POLZA_EGRESS_MODE": "real"}
        with (
            patch.dict(os.environ, config),
            patch("softline_backend.polza_egress.FILTER_TIMEOUT_SECONDS", 10),
        ):
            enabled, native_filter = load_egress_filter()
            self.assertTrue(enabled)
            self.assertIsNotNone(native_filter)
            _, usage = await self.complete(native_filter)
            self.assertEqual(usage.input_tokens, 10)
            self.assertEqual(len(self.requests), 1)

            personal = "ФИО: Иван Петров. " + MESSAGE
            self.scope = TurnScope("test-turn", personal, (), None)
            with self.assertRaises(TemporaryReadError):
                await self.complete(native_filter, candidate={"message": personal, "selection": None})
            self.assertEqual(len(self.requests), 1)

    @unittest.skipUnless(find_spec("natasha") is not None, "requires the local privacy extra")
    async def test_long_history_egress_only_sends_approved_fields(self):
        history = tuple(f"Техническое уточнение {index}" for index in range(16))
        with (
            patch.dict(os.environ, LLM_BASE_URL="https://polza.ai/api/v1", POLZA_EGRESS_MODE="real"),
            patch("softline_backend.polza_egress.FILTER_TIMEOUT_SECONDS", 10),
        ):
            _, native_filter = load_egress_filter()
            self.scope = TurnScope("test-turn", MESSAGE, history, None)
            await self.complete(native_filter)
            self.assertEqual(self.requests[0]["messages"][1]["content"],
                             "Нужно резервное копирование для 10 ПК с Windows 11, локально")

            self.scope = TurnScope("test-turn", MESSAGE, ("В переписке есть диагноз", *history), None)
            with self.assertRaises(TemporaryReadError):
                await self.complete(native_filter)
            self.assertEqual(len(self.requests), 1)

class EgressBridgeTests(unittest.TestCase):
    def test_old_catalog_context_is_screened_with_current_default_fields(self):
        current = asdict(CatalogContext("need", goal="резервное копирование"))
        old = {key: value for key, value in current.items() if key not in {"license_action", "unverified_constraint"}}
        scope = TurnScope("old-turn", MESSAGE, (), {"catalog_context": old}, current)
        with patch("softline_backend.polza_egress.prepare_llm_input",
                   return_value=SimpleNamespace(categories=(), model_payload=TECHNICAL["fields"])) as checked:
            self.assertEqual(_screen_with_ml(scope)["decision"], "allow")
            checked.assert_called_once_with(MESSAGE, history=(), selection=current)
            current["goal"] = "другая задача"
            self.assertEqual(_screen_with_ml(scope)["decision"], "uncertain")

    def test_worker_guard_handoff_retains_original_only_in_local_case(self):
        outgoing = []
        sensitive = "Уточните требования, номер заказа TEST-4217"

        async def allow(_scope):
            return TECHNICAL

        def receive(request):
            outgoing.append(request)
            raise AssertionError("HTTP must stay blocked")

        model = CatalogModel(
            "fake-key", "anthropic/claude-haiku-5.5", enabled=True, checker=allow,
            transport=httpx.MockTransport(receive),
        )
        bridge = CommerceBridge(Path("/nonexistent.sqlite"), model)
        old_turn_id, chat_id, current_turn_id = uuid4(), uuid4(), uuid4()
        history = [MessageView(turn_id=old_turn_id, role="user", text="Мой номер +7 999 123-45-67")]
        turn = ClaimedTurn(current_turn_id, chat_id, 2, sensitive, 1)
        result = bridge.reply(turn, history, None)
        self.assertEqual(result.outcome, "handoff")
        self.assertIn("TEST-4217", result.handoff.summary)
        self.assertNotIn("TEST-4217", result.text)
        self.assertEqual(outgoing, [])
