import os
import unittest
from threading import Event, Thread
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
