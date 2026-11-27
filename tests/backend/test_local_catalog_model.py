import json
import unittest
from unittest.mock import patch

import httpx

from aisupport_ml.commerce.indexed_chat import INDEXED_SCHEMA
from aisupport_ml.contracts import TemporaryReadError
from softline_backend.commerce_bridge import commerce_egress_configured, commerce_from_env
from softline_backend.ollama_profile import DEFAULT_ENDPOINT, MODEL, MODEL_4B, PROFILE, LocalCatalogModel
from softline_backend.polza_egress import TurnScope, polza_scope


class LocalCatalogModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_endpoints_and_unknown_models_are_rejected(self):
        async def checker(_scope):
            self.fail("Invalid configuration must be rejected before filtering")

        for url, model in (
            ("http://example.org:11434/api/chat", MODEL_4B),
            ("http://u:p@127.0.0.1:11434/api/chat", MODEL_4B),
            ("http://ollama:11434/api/chat?forward=true", MODEL_4B),
            (DEFAULT_ENDPOINT, "qwen-cloud"),
        ):
            with self.subTest(url=url, model=model), self.assertRaises(TemporaryReadError):
                await LocalCatalogModel(url, checker, model=model).complete("", "{}", INDEXED_SCHEMA)

    def test_worker_configuration_selects_4b_explicitly(self):
        with patch.dict("os.environ", COMMERCE_CATALOG_INDEX_PATH="/unused", COMMERCE_MODEL_PROFILE=PROFILE,
                        COMMERCE_OLLAMA_ENDPOINT=DEFAULT_ENDPOINT, COMMERCE_OLLAMA_MODEL=MODEL_4B):
            bridge = commerce_from_env()
            self.assertEqual(bridge.agent.model.model, MODEL_4B)
            self.assertTrue(commerce_egress_configured())
            with patch.dict("os.environ", COMMERCE_OLLAMA_MODEL=""):
                self.assertEqual(commerce_from_env().agent.model.model, MODEL)
            with patch.dict("os.environ", COMMERCE_OLLAMA_MODEL="unknown"):
                self.assertFalse(commerce_egress_configured())

    async def test_local_endpoint_receives_the_same_guarded_json_contract(self):
        message = "Нужна программа на 10 компьютеров с Windows 11"
        calls = []

        async def checker(_scope):
            return {"decision": "allow", "fields": {"device_count": 10, "platform": "windows_11"}}

        def transport(request):
            payload = json.loads(request.content)
            calls.append(payload)
            self.assertEqual(str(request.url), DEFAULT_ENDPOINT)
            self.assertNotIn("authorization", request.headers)
            answer = dict.fromkeys(INDEXED_SCHEMA["properties"])
            answer.update(action="continue", file_os="Windows 11")
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "prompt_eval_count": 20,
                                             "eval_count": 4, "message": {"content": json.dumps(answer)}})

        model = LocalCatalogModel(DEFAULT_ENDPOINT, checker=checker, model=MODEL_4B, transport=httpx.MockTransport(transport))
        for text in (message, "Пишите на person@example.org"):
            token = polza_scope.set(TurnScope("turn", text, (), None))
            try:
                candidate = json.dumps({"message": text, "selection": None})
                if text != message:
                    with self.assertRaises(TemporaryReadError):
                        await model.complete("", candidate, INDEXED_SCHEMA)
                    continue
                result, usage = await model.complete("", candidate, INDEXED_SCHEMA)
                self.assertEqual(result["file_os"], "Windows 11")
                self.assertEqual((usage.input_tokens, usage.output_tokens), (20, 4))
            finally:
                polza_scope.reset(token)
        payload, = calls
        self.assertEqual(payload["model"], MODEL_4B)
        self.assertEqual(payload["format"], INDEXED_SCHEMA)
        self.assertEqual(payload["messages"][-1]["content"], "Технические условия для 10 ПК с Windows 11")
        self.assertEqual(payload["options"]["num_ctx"], 2048)
