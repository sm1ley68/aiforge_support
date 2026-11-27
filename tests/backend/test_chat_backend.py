import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import connect, sql
from psycopg.conninfo import make_conninfo

from softline_backend.api import create_app
from softline_backend.catalog import build_index
from softline_backend.contracts import TurnResult
from softline_backend.store import ChatStore
from softline_backend.worker import process_one, reply_from_env


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires PostgreSQL")
class ChatBackendTests(unittest.TestCase):
    def setUp(self):
        database_url = os.environ["TEST_DATABASE_URL"]
        schema = f"test_{uuid4().hex}"
        with connect(database_url, autocommit=True) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        self.addCleanup(self.drop_schema, database_url, schema)
        self.store = ChatStore(make_conninfo(database_url, options=f"-c search_path={schema}"))
        self.store.initialize()
        self.client = TestClient(create_app(self.store))
        self.addCleanup(self.client.close)
        response = self.client.post("/chats")
        self.assertEqual(response.status_code, 201)
        self.chat = response.json()
        self.path = f"/chats/{self.chat['chat_id']}"
        self.headers = {"Authorization": f"Bearer {self.chat['chat_token']}"}

    @staticmethod
    def drop_schema(database_url, schema):
        with connect(database_url, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

    def submit(self, message_id, text):
        return self.client.post(
            f"{self.path}/messages",
            headers=self.headers,
            json={"client_message_id": message_id, "text": text},
        )

    def test_round_trip_and_idempotency(self):
        response = self.submit("phone-1", "Нужна защита для 50")
        self.assertEqual(response.status_code, 202)
        turn_id = response.json()["turn_id"]
        turn_url = f"{self.path}/turns/{turn_id}"
        self.assertEqual(self.client.get(turn_url, headers=self.headers).json()["status"], "queued")
        self.assertEqual(self.submit("phone-1", "Нужна защита для 50").json()["turn_id"], turn_id)
        self.assertEqual(self.submit("phone-1", "Другое").status_code, 409)
        self.assertTrue(process_one(self.store))
        self.assertFalse(process_one(self.store))
        turn = self.client.get(turn_url, headers=self.headers).json()
        self.assertEqual((turn["status"], turn["outcome"]), ("succeeded", "clarify"))
        messages = self.client.get(f"{self.path}/messages", headers=self.headers).json()
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])

    def test_chat_access_and_fifo(self):
        first = self.submit("first", "Первый").json()["turn_id"]
        second = self.submit("second", "Второй").json()["turn_id"]
        self.assertEqual(
            self.client.get(f"{self.path}/messages", headers={"Authorization": "Bearer wrong"}).status_code,
            404,
        )
        self.assertEqual(str(self.store.claim().turn_id), first)
        self.assertIsNone(self.store.claim())
        self.assertEqual(
            self.client.get(f"{self.path}/turns/{second}", headers=self.headers).json()["status"], "queued"
        )

    def test_expired_worker_cannot_publish(self):
        self.submit("first", "Нужен товар")
        expired = self.store.claim(lease_seconds=0)
        current = self.store.claim()
        self.assertEqual(current.turn_id, expired.turn_id)
        self.assertFalse(self.store.finish(expired, error="processing_failed"))
        self.assertTrue(self.store.finish(current, error="processing_failed"))

    def test_handler_receives_only_previous_turns(self):
        self.submit("first", "Сервер на 50 пользователей")
        second = self.submit("second", "Только локально").json()["turn_id"]
        self.submit("third", "Третий вопрос")
        self.assertTrue(process_one(self.store))

        def reply(text, history):
            self.assertEqual(text, "Только локально")
            self.assertEqual([message.role for message in history], ["user", "assistant"])
            self.assertEqual(history[0].text, "Сервер на 50 пользователей")
            return TurnResult(outcome="answer", text="Понял: только локально.")

        self.assertTrue(process_one(self.store, reply))
        result = self.client.get(f"{self.path}/turns/{second}", headers=self.headers).json()
        self.assertEqual((result["outcome"], result["text"]), ("answer", "Понял: только локально."))

    def test_customer_request_creates_one_manager_case(self):
        request = self.submit("handoff", "Позовите менеджера, пожалуйста.")
        turn_id = request.json()["turn_id"]
        self.assertEqual(self.submit("handoff", "Позовите менеджера, пожалуйста.").json()["turn_id"], turn_id)
        self.assertTrue(process_one(self.store))
        self.assertFalse(process_one(self.store))

        result = self.client.get(f"{self.path}/turns/{turn_id}", headers=self.headers).json()
        self.assertEqual(result["outcome"], "handoff")
        self.assertNotIn("handoff", result)
        self.assertEqual(self.client.get("/manager/handoffs").status_code, 401)
        self.assertEqual(self.client.get("/manager/handoffs", headers=self.headers).status_code, 403)

        with TestClient(create_app(self.store, manager_token="manager-secret")) as manager:
            headers = {"Authorization": "Bearer manager-secret"}
            cases = manager.get("/manager/handoffs", headers=headers).json()
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["handoff_id"], turn_id)
            self.assertEqual(cases[0]["reason"], "customer_requested")
            detail = manager.get(f"/manager/handoffs/{turn_id}", headers=headers).json()
            self.assertEqual(detail["messages"][0]["text"], "Позовите менеджера, пожалуйста.")
            self.assertEqual(detail["messages"][1]["role"], "assistant")


    def test_catalog_result_reaches_chat_through_configured_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            feed = Path(folder) / "feed.xml"
            feed.write_text(
                '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
                '<offer id="example" available="true"><name>Demo Mail</name>'
                '<vendorCode>MAIL-12</vendorCode><url>https://example.com/mail</url>'
                "</offer></offers></shop></yml_catalog>"
            )
            index = Path(folder) / "catalog.sqlite3"
            build_index(feed, index)
            turn_id = self.submit("sku", "SKU: MAIL-12").json()["turn_id"]
            with patch.dict(os.environ, CATALOG_INDEX_PATH=str(index)):
                self.assertTrue(process_one(self.store, reply_from_env()))

        turn = self.client.get(f"{self.path}/turns/{turn_id}", headers=self.headers).json()
        self.assertEqual(turn["outcome"], "answer")
        self.assertEqual(turn["products"][0]["sku"], "MAIL-12")
        self.assertEqual(turn["sources"][0]["url"], "https://example.com/mail")


    def test_task_constraints_reach_worker_from_persisted_chat_history(self):
        with tempfile.TemporaryDirectory() as folder:
            feed = Path(folder) / "feed.xml"
            index = Path(folder) / "catalog.sqlite3"
            feed.write_text(
                '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
                '<offer id="example" available="true"><name>Demo Mail</name>'
                '<vendorCode>MAIL-12</vendorCode><url>https://example.com/mail</url>'
                '<description>Защита почты и файлов</description>'
                '<param name="Развёртывание">on-premise</param>'
                '<param name="Количество пользователей">100</param>'
                '<currencyId>RUB</currencyId><price>9000</price>'
                "</offer></offers></shop></yml_catalog>"
            )
            build_index(feed, index)
            with patch.dict(os.environ, CATALOG_INDEX_PATH=str(index)):
                reply = reply_from_env()
            self.submit("task", "Нужна защита почты и файлов на 50 сотрудников")
            local_id = self.submit("deployment", "Только локально").json()["turn_id"]
            budget_id = self.submit("budget", "Бюджет до 8 500 рублей").json()["turn_id"]
            for _ in range(3):
                self.assertTrue(process_one(self.store, reply))

        local = self.client.get(f"{self.path}/turns/{local_id}", headers=self.headers).json()
        self.assertEqual(local["outcome"], "answer")
        self.assertEqual([card["sku"] for card in local["products"]], ["MAIL-12"])
        self.assertIn("локально", local["text"])
        self.assertIn("50", local["text"])
        budget = self.client.get(f"{self.path}/turns/{budget_id}", headers=self.headers).json()
        self.assertEqual((budget["status"], budget["outcome"], budget["products"]), ("succeeded", "clarify", []))

    def test_fact_questions_use_selected_offer_and_current_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            feed = Path(folder) / "feed.xml"
            index = Path(folder) / "catalog.sqlite3"
            contents = (
                '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
                '<offer id="demo" available="true"><name>Demo Mail</name>'
                '<vendorCode>MAIL-12</vendorCode><url>https://example.com/mail</url>'
                '<price>9000</price><currencyId>RUB</currencyId>'
                '<param name="Срок лицензии">12 месяцев</param>'
                "</offer></offers></shop></yml_catalog>"
            )
            feed.write_text(contents)
            build_index(feed, index)
            with patch.dict(os.environ, CATALOG_INDEX_PATH=str(index)):
                reply = reply_from_env()
            self.submit("sku", "Артикул MAIL-12")
            self.assertTrue(process_one(self.store, reply))

            feed.write_text(contents.replace("9000", "8500"))
            build_index(feed, index)
            questions = [
                ("price", "А сколько стоит?"),
                ("missing-fact", "Какое развёртывание?"),
                ("term", "Какой срок лицензии?"),
            ]
            turn_ids = [self.submit(key, question).json()["turn_id"] for key, question in questions]
            for _ in turn_ids:
                self.assertTrue(process_one(self.store, reply))

        price, missing, term = [
            self.client.get(f"{self.path}/turns/{turn_id}", headers=self.headers).json()
            for turn_id in turn_ids
        ]
        self.assertEqual(price["outcome"], "answer")
        self.assertIn("8500 RUB", price["text"])
        self.assertEqual(price["sources"][0]["url"], "https://example.com/mail")
        self.assertEqual(missing["outcome"], "clarify")
        self.assertEqual(term["outcome"], "answer")
        self.assertIn("12 месяцев", term["text"])
        self.assertNotIn("catalog_selection", price)
        history = self.client.get(f"{self.path}/messages", headers=self.headers).json()
        self.assertNotIn("catalog_references", history[-1])

    def test_commerce_worker_restores_requirements_and_projects_manager_case(self):
        from aisupport_ml.commerce.catalog import build_catalog
        from softline_backend.commerce_bridge import commerce_from_env

        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "commerce.xml"
            index = Path(folder) / "commerce.sqlite3"
            offers = []
            for offer_id, sku, price, months in (
                ("5066", "KL4869RAQFS", "7691.40", 12),
                ("5058", "KL4869RAQDS", "11536.20", 24),
            ):
                offers.append(
                    f'<offer id="{offer_id}" available="true">'
                    '<name>Kaspersky Total Security для бизнеса базовая лицензия по количеству узлов</name>'
                    f'<vendorCode>{sku}</vendorCode><url>https://store.softline.ru/kaspersky/-{offer_id}/</url>'
                    f'<price>{price}</price><currencyId>RUR</currencyId>'
                    f'<param name="Срок действия">{months} мес.</param></offer>'
                )
            fixture.write_text(
                '<yml_catalog date="2026-11-25 14:12"><shop><offers>'
                + "".join(offers) + "</offers></shop></yml_catalog>", encoding="utf-8"
            )
            build_catalog(fixture, index)
            steps = (
                ("need", "Хотим защитить почту и файлы на 50 сотрудников"),
                ("needs", "Exchange и Windows Server 2019, локально, 50 узлов, бюджет до 650 тысяч рублей"),
                ("origin", "А российский аналог?"),
                ("price", "А сколько стоит?"),
                ("delivery", "Как я получу электронную лицензию?"),
                ("discount", "Согласуете индивидуальную скидку?"),
            )
            turn_ids = []
            with patch.dict(os.environ, COMMERCE_CATALOG_INDEX_PATH=str(index), POLZA_API_KEY="", LLM_API_KEY=""):
                for key, question in steps:
                    response = self.submit(key, question)
                    self.assertEqual(response.status_code, 202)
                    turn_ids.append(response.json()["turn_id"])
                    # Fresh adapter each time simulates a worker restart without in-memory history.
                    self.assertTrue(process_one(self.store, commerce=commerce_from_env()))

        turns = [self.client.get(f"{self.path}/turns/{turn_id}", headers=self.headers).json() for turn_id in turn_ids]
        self.assertEqual([turn["outcome"] for turn in turns], [
            "clarify", "recommend", "recommend", "clarify", "answer", "handoff",
        ])
        self.assertEqual({card["sku"] for card in turns[1]["products"]}, {"KL4869RAQFS", "KL4869RAQDS"})
        self.assertIn("384570.00 RUB за 50 узлов", turns[1]["text"])
        self.assertTrue(any("/registry" in source["url"] for source in turns[2]["sources"]))
        self.assertNotIn("commerce_state", turns[2])
        self.assertIn("О каком варианте", turns[3]["text"])
        self.assertEqual(turns[4]["sources"][0]["url"], "https://store.softline.ru/delivery_info/")

        with TestClient(create_app(self.store, manager_token="manager-secret")) as manager:
            path = f"/manager/handoffs/{turn_ids[-1]}"
            case = manager.get(path, headers={"Authorization": "Bearer manager-secret"}).json()
        self.assertEqual(case["reason"], "commercial_terms")
        self.assertEqual(case["requirements"]["nodes"], "50")
        self.assertEqual(case["requirements"]["budget_rub"], "650000")
        self.assertEqual(set(case["candidate_ids"]), {"5066", "5058"})

    def test_public_knowledge_is_saved_with_turn_and_restored_in_new_worker(self):
        from softline_backend.commerce_bridge import commerce_from_env

        with patch.dict(os.environ, COMMERCE_CATALOG_INDEX_PATH="/unused", POLZA_API_KEY="", LLM_API_KEY=""):
            self.submit("keys", "А где найти ключ активации после покупки?")
            first = commerce_from_env()
            self.assertTrue(process_one(self.store, commerce=first))
            publications = self.store.published_knowledge()
            self.assertEqual([source for _, source, _ in publications], ["softline-lk-keys"])

            restarted = commerce_from_env()
            restarted.restore_knowledge(publications)
            second_id = self.submit("keys-again", "Где скачать ключ активации?").json()["turn_id"]
            self.assertTrue(process_one(self.store, commerce=restarted))
            response = self.client.get(f"{self.path}/turns/{second_id}", headers=self.headers).json()
            self.assertEqual(response["outcome"], "answer")
            self.assertIn("Частый вопрос", response["text"])
            self.assertNotIn("knowledge_update", response)
            self.assertEqual(self.store.published_knowledge(), publications)

    def test_automatic_quote_uses_verified_available_offer_and_stores_price_snapshot(self):
        from aisupport_ml.commerce.catalog import build_catalog
        from softline_backend.commerce_bridge import commerce_from_env

        with tempfile.TemporaryDirectory() as folder:
            feed = Path(folder) / "catalog.xml"
            index = Path(folder) / "catalog.sqlite3"

            def rebuild(price):
                feed.write_text(
                    '<yml_catalog date="2026-11-27 13:00"><shop><offers>'
                    f'<offer id="1001" available="true"><name>Тестовая лицензия</name>'
                    f'<vendorCode>TEST1</vendorCode><url>https://store.softline.ru/test/1001/</url>'
                    f'<price>{price}</price><currencyId>RUR</currencyId></offer>'
                    '<offer id="1002" available="false"><name>Недоступная лицензия</name>'
                    '<url>https://store.softline.ru/test/1002/</url><price>70</price>'
                    '<currencyId>RUR</currencyId></offer></offers></shop></yml_catalog>', encoding="utf-8",
                )
                replacement = index.with_suffix(".new")
                build_catalog(feed, replacement)
                replacement.replace(index)

            rebuild("123.45")
            with patch.dict(os.environ, COMMERCE_CATALOG_INDEX_PATH=str(index), POLZA_API_KEY="", LLM_API_KEY=""):
                responses = {}
                for key, text in (
                    ("available-quote", "КП на 2 упаковки, ID предложения 1001"),
                    ("unavailable-quote", "КП на 2 упаковки, ID предложения 1002"),
                ):
                    response = self.submit(key, text)
                    self.assertEqual(response.status_code, 202)
                    responses[key] = f"{self.path}/turns/{response.json()['turn_id']}"
                    self.assertTrue(process_one(self.store, commerce=commerce_from_env()))
                rebuild("200.00")

            quote_path = responses["available-quote"]
            turn = self.client.get(quote_path, headers=self.headers).json()
            self.assertEqual(turn["status"], "succeeded", turn)
            self.assertIsNotNone(turn["quote"], turn)
            self.assertEqual(turn["quote"]["total"], "246.90")
            self.assertEqual(turn["quote"]["quantity"], 2)
            self.assertEqual(turn["quote"]["currency"], "RUB")
            self.assertEqual(self.client.get(quote_path + "/quote").status_code, 401)
            document = self.client.get(quote_path + "/quote", headers=self.headers)
            self.assertEqual(document.status_code, 200, document.text)
            self.assertIn("attachment", document.headers["Content-Disposition"])
            self.assertIn("246.90", document.text)
            self.assertNotIn("400.00", document.text)
            self.assertEqual(self.client.post(quote_path + "/resolution", headers=self.headers).status_code, 204)
            self.assertEqual(self.client.post(quote_path + "/resolution", headers=self.headers).status_code, 204)
            rejected = self.client.get(responses["unavailable-quote"], headers=self.headers).json()
            self.assertEqual(rejected["outcome"], "handoff")
            self.assertIsNone(rejected["quote"])
            operator = {"Authorization": "Bearer manager-secret"}
            with TestClient(create_app(self.store, manager_token="manager-secret")) as manager:
                self.assertEqual(manager.post(f"/api/requests/{rejected['turn_id']}/reply", headers=operator, json={
                    "text": "Подтверждаю ранее выданное КП.", "confirmedQuoteTurnId": turn["turn_id"],
                }).status_code, 409)
                handoff = self.submit("review-previous-quote", "Позовите менеджера").json()["turn_id"]
                self.assertTrue(process_one(self.store))
                case_id = handoff
                summary_path = f"/api/requests/{case_id}/reply"
                summary = manager.post(summary_path, headers=operator, json={
                    "text": "Подтверждаю ранее выданное КП.",
                    "confirmedQuoteTurnId": turn["turn_id"],
                })
                self.assertEqual(summary.status_code, 200, summary.text)
                metrics = manager.get("/api/requests/metrics", headers=operator).json()
            self.assertEqual(metrics["managerConfirmedQuotes"], 1)
            self.assertEqual(metrics["automaticQuotes"], 0)
            self.assertEqual(metrics["customerConfirmedAnswers"], 0)
