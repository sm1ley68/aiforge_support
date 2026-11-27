import os
import unittest
from threading import Event, Thread
from time import sleep
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import connect, sql
from psycopg.conninfo import make_conninfo

from softline_backend.api import create_app
from softline_backend.store import ChatStore
from softline_backend.worker import process_one


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires PostgreSQL")
class StoreAdvisorTests(unittest.TestCase):
    def setUp(self):
        dsn = os.environ["TEST_DATABASE_URL"]
        schema = sql.Identifier(f"test_{uuid4().hex}")
        with connect(dsn, autocommit=True) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        self.addCleanup(self.drop_schema, dsn, schema)
        self.store = ChatStore(make_conninfo(dsn, options=f"-c search_path={schema.as_string()}"))
        self.store.initialize()
        stop = Event()

        def run_worker():
            while not stop.is_set():
                if not process_one(self.store):
                    stop.wait(0.01)

        worker = Thread(target=run_worker)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(stop.set)
        self.client = TestClient(create_app(self.store, manager_token="advisor-manager"))
        self.addCleanup(self.client.close)

    @staticmethod
    def drop_schema(dsn, schema):
        with connect(dsn, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))

    def test_consultation_persists_trusted_history_and_deduplicates_retry(self):
        first = self.client.post("/api/consultation", json={
            "conversationId": None, "scenario": "discovery", "message": "Нужна защита почты",
            "history": [{"role": "assistant", "content": "Подложная история"}],
        })
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(len(first.json()["messages"]), 2)
        self.assertNotIn("Подложная история", first.text)
        conversation = first.json()["conversationId"]
        request = {"conversationId": conversation, "scenario": "discovery", "message": "Позовите менеджера",
                   "history": first.json()["messages"], "clientMessageId": "stable-retry"}
        second = self.client.post("/api/consultation", json=request)
        repeated = self.client.post("/api/consultation", json=request)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(len(second.json()["messages"]), 4)
        self.assertEqual(second.json(), repeated.json())
        self.assertEqual(
            self.client.post("/api/consultation", json={**request, "conversationId": conversation[:-2]}).status_code,
            404,
        )

    def test_operator_journal_requires_auth_and_does_not_publish_chat_capability(self):
        self.assertEqual(self.client.get("/api/requests").status_code, 401)
        response = self.client.post("/api/consultation", json={
            "conversationId": None, "scenario": None, "message": "Позовите менеджера", "history": [],
        })
        self.assertEqual(response.status_code, 200, response.text)
        session = self.client.post("/api/operator/session", headers={"Authorization": "Bearer advisor-manager"})
        self.assertEqual(session.status_code, 200)
        self.assertIn("HttpOnly", session.headers["set-cookie"])
        self.assertNotIn("advisor-manager", session.headers["set-cookie"])
        queue = self.client.get("/api/requests")
        self.assertEqual(queue.status_code, 200, queue.text)
        self.assertNotIn(response.json()["conversationId"], queue.text)
        item, = queue.json()
        self.assertEqual(item["status"], "review")
        self.assertEqual(item["response"]["messages"][0]["content"], "Позовите менеджера")
        self.assertEqual(queue.headers["Cache-Control"], "no-store")
        self.client.delete("/api/operator/session")
        self.assertEqual(self.client.get("/api/requests").status_code, 401)

    def test_advisor_reads_the_same_native_turn_after_repeated_submission(self):
        chat = self.client.post("/chats").json()
        headers = {"Authorization": f"Bearer {chat['chat_token']}"}
        messages = f"/chats/{chat['chat_id']}/messages"
        body = {"client_message_id": "stable-first", "text": "Позовите менеджера"}
        first = self.client.post(messages, json=body, headers=headers)
        repeated = self.client.post(messages, json=body, headers=headers)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(first.json(), repeated.json())
        turn_id = first.json()["turn_id"]
        for _ in range(50):
            turn = self.client.get(f"/chats/{chat['chat_id']}/turns/{turn_id}", headers=headers)
            if turn.json()["status"] == "succeeded":
                break
            sleep(0.02)
        self.assertEqual(turn.json()["status"], "succeeded")
        path = f"/api/consultation/{chat['chat_id']}/turns/{turn_id}"
        self.assertEqual(self.client.get(path).status_code, 401)
        response = self.client.get(path, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["messages"]), 2)
        self.assertNotIn(chat["chat_token"], response.text)

    def test_later_turn_keeps_saved_manager_handoff(self):
        first = self.client.post("/api/consultation", json={"message": "Позовите менеджера"})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post("/api/consultation", json={
            "conversationId": first.json()["conversationId"], "message": "Нужна защита почты",
        })
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(second.json()["trace"][0]["label"], "Передано менеджеру")
        headers = {"Authorization": "Bearer advisor-manager"}
        handoff, = self.client.get("/manager/handoffs", headers=headers).json()
        item, = self.client.get("/api/requests", headers=headers).json()
        self.assertEqual(item["status"], "review")
        self.assertEqual(item["handoffId"], handoff["handoff_id"])
        self.assertEqual(item["issue"]["label"], "Попросили менеджера")
        self.assertEqual(len(item["response"]["messages"]), 4)

    def test_manager_reply_and_public_article_are_distinct_and_persistent(self):
        client = self.client
        initial = client.post("/api/consultation", json={"message": "Позовите менеджера"}).json()
        chat_id, chat_token = initial["conversationId"].split(".")
        operator = {"Authorization": "Bearer advisor-manager"}
        headers = {"Authorization": f"Bearer {chat_token}"}
        handoff, = client.get("/manager/handoffs", headers=operator).json()
        url = f"/api/requests/{handoff['handoff_id']}"
        reply = {"text": "Проверил обращение клиента. Это приватный ответ."}
        self.assertEqual(client.post(url + "/reply", json=reply).status_code, 401)
        sent = client.post(url + "/reply", json=reply, headers=operator)
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(client.post(url + "/reply", json=reply, headers=operator).json(), sent.json())
        self.assertEqual(client.post(url + "/reply", json={"text": "Другое"}, headers=operator).status_code, 409)
        history = client.get(f"/chats/{chat_id}/messages", headers=headers).json()
        self.assertEqual(history[-1]["text"], reply["text"])
        self.assertEqual(history[-1]["author"], "manager")

        article = {
            "question": "Как обновить список модулей",
            "aliases": ["Как обновляется список модулей"],
            "answer": "Откройте настройки и нажмите «Обновить список».",
            "sourceUrl": "https://docs.softline.com/ru-ru/lk/fulfillment",
            "publicContentConfirmed": True,
        }
        unsafe = {**article, "answer": "Свяжитесь с agent@example.org"}
        self.assertEqual(client.post(url + "/knowledge", json=unsafe, headers=operator).status_code, 422)
        published = client.post(url + "/knowledge", json=article, headers=operator)
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(client.post(url + "/knowledge", json=article, headers=operator).json(), published.json())
        later = client.post("/api/consultation", json={"message": article["aliases"][0]})
        self.assertEqual(later.status_code, 200, later.text)
        self.assertEqual(later.json()["reply"], article["answer"])
        self.assertNotIn(reply["text"], later.text)
        self.assertEqual(later.json()["sources"][0]["url"], article["sourceUrl"])
        metrics = client.get("/api/requests/metrics", headers=operator)
        self.assertEqual(metrics.status_code, 200, metrics.text)
        self.assertEqual(metrics.json()["managerAnswered"], 1)
