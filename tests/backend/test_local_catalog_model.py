import json
import unittest

import httpx

from aisupport_ml.commerce.indexed_chat import INDEXED_SCHEMA
from aisupport_ml.contracts import TemporaryReadError
from softline_backend.local_catalog_model import DEFAULT_URL, MODEL, LocalCatalogModel
from softline_backend.polza_egress import TurnScope, polza_scope


class LocalCatalogModelTests(unittest.IsolatedAsyncioTestCase):
    def test_remote_or_credentials_are_rejected(self):
        for url in ("http://example.org:11434", "https://127.0.0.1:11434", "http://u:p@127.0.0.1:11434",
                    "http://127.0.0.1:11434/other", "http://ollama:11434?forward=true"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    LocalCatalogModel(url)

    async def test_local_endpoint_receives_the_same_guarded_json_contract(self):
        message = "Нужна программа на 10 компьютеров с Windows 11"
        calls = []

        async def checker(_scope):
            return {"decision": "allow", "fields": {"device_count": 10, "platform": "windows_11"}}

        def transport(request):
            payload = json.loads(request.content)
            calls.append(payload)
            self.assertEqual(str(request.url), DEFAULT_URL + "/api/chat")
            self.assertNotIn("authorization", request.headers)
            answer = dict.fromkeys(INDEXED_SCHEMA["properties"])
            answer.update(action="continue", file_os="Windows 11")
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "prompt_eval_count": 20,
                                             "eval_count": 4, "message": {"content": json.dumps(answer)}})

        model = LocalCatalogModel(DEFAULT_URL, checker=checker, transport=httpx.MockTransport(transport))
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
        self.assertEqual(payload["model"], MODEL)
        self.assertEqual(payload["format"], INDEXED_SCHEMA)
        self.assertEqual(payload["messages"][-1]["content"], "Технические условия для 10 ПК с Windows 11")
        self.assertEqual(payload["options"]["num_ctx"], 2048)
