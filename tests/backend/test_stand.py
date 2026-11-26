import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import connect, sql
from psycopg.conninfo import make_conninfo

from softline_backend.api import create_app
from softline_backend.catalog import build_index
from softline_backend.contracts import TurnResult
from softline_backend.store import ChatStore


class StandSurfaceTests(unittest.TestCase):
    def test_demo_pages_and_static_assets_are_same_origin(self):
        with TestClient(create_app(ChatStore("unused"))) as client:
            for url, expected in [("/", "Чат с поддержкой"), ("/manager", "Очередь обращений")]:
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.text)
                self.assertIn("/demo/demo.js", response.text)
                self.assertIn("/demo/demo.css", response.text)

            self.assertEqual(client.get("/demo/demo.js").status_code, 200)
            self.assertEqual(client.get("/demo/demo.css").status_code, 200)

    def test_liveness_and_unavailable_database(self):
        with TestClient(create_app(ChatStore("host=127.0.0.1 port=1"))) as client:
            self.assertEqual(client.get("/health/live").json(), {"status": "alive"})
            ready = client.get("/health/ready")
            self.assertEqual(ready.status_code, 503)
            self.assertEqual(ready.json()["database"], "unavailable")
            self.assertEqual(ready.json()["catalog"], "unconfigured")
            self.assertEqual(ready.json()["provider"], "deterministic")


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires PostgreSQL")
class StandDatabaseTests(unittest.TestCase):
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
        self.chat = self.store.create_chat()

    @staticmethod
    def drop_schema(database_url, schema):
        with connect(database_url, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.chat.chat_token}"}

    def submit(self):
        return self.store.submit(self.chat.chat_id, self.chat.chat_token, uuid4().hex, "Частный текст")

    def retry(self, turn_id, headers=None):
        return self.client.post(
            f"/chats/{self.chat.chat_id}/turns/{turn_id}/retry",
            headers=self.headers if headers is None else headers,
        )

    def ready(self, **config):
        with TestClient(create_app(self.store, **config)) as client:
            return client.get("/health/ready")

    def test_readiness_checks_schema_and_catalog_without_network_provider_probe(self):
        self.assertEqual(
            self.ready().json(),
            {"status": "ready", "database": "ready", "catalog": "unconfigured", "provider": "deterministic"},
        )
        with tempfile.TemporaryDirectory() as folder:
            feed = Path(folder) / "feed.xml"
            index = Path(folder) / "catalog.sqlite3"
            ready = self.ready(catalog_index=index, provider_status="configured")
            self.assertEqual(ready.status_code, 503)
            self.assertEqual(ready.json()["catalog"], "unavailable")
            self.assertEqual(ready.json()["provider"], "configured")
            feed.write_text(
                '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
                '<offer id="one" available="true"><name>Demo</name></offer>'
                '</offers></shop></yml_catalog>',
                encoding="utf-8",
            )
            build_index(feed, index)
            ready = self.ready(catalog_index=index, provider_status="configured")
            self.assertEqual(ready.status_code, 200)
            self.assertEqual(ready.json()["catalog"], "ready")

        with self.store._connect() as db:
            db.execute("DROP TABLE chat_turns")
        self.assertEqual(self.ready().json()["database"], "unavailable")

    def test_existing_turns_survive_the_retry_schema_upgrade(self):
        turn_id = self.submit()
        self.assertTrue(self.store.finish(self.store.claim(), error="processing_failed"))
        with self.store._connect() as db:
            db.execute("ALTER TABLE chat_turns DROP COLUMN retry_attempt_base")

        self.assertEqual(self.ready().status_code, 503)
        self.store.initialize()
        self.store.initialize()

        self.assertEqual(self.ready().status_code, 200)
        self.assertEqual(self.retry(turn_id).status_code, 202)
        self.assertEqual(self.store.claim().attempts, 2)

    def test_submission_log_has_turn_id_and_duration_without_chat_content(self):
        private_text = "Текст только для поддержки"
        with self.assertLogs("softline_backend.api", level="INFO") as captured:
            response = self.client.post(
                f"/chats/{self.chat.chat_id}/messages",
                headers=self.headers,
                json={"client_message_id": "client-secret", "text": private_text},
            )
        self.assertEqual(response.status_code, 202)
        log = captured.output[0]
        self.assertIn(f"turn_id={response.json()['turn_id']}", log)
        self.assertIn("duration_ms=", log)
        for private in [private_text, self.chat.chat_token, "client-secret"]:
            self.assertNotIn(private, log)

    def test_retry_preserves_turn_and_order_and_fences_previous_lease(self):
        first, second = self.submit(), self.submit()
        original = self.store.claim()
        self.assertEqual(original.turn_id, first)
        self.assertEqual(self.retry(first).status_code, 409)
        self.assertTrue(self.store.finish(original, error="processing_failed"))
        self.assertEqual(self.retry(first, {}).status_code, 401)
        self.assertEqual(self.retry(first, {"Authorization": "Bearer wrong"}).status_code, 404)
        self.assertEqual(self.retry(uuid4()).status_code, 404)
        accepted = self.retry(first)
        self.assertEqual((accepted.status_code, accepted.json()), (202, {"turn_id": str(first)}))
        retried = self.store.claim()
        self.assertEqual(retried.turn_id, first)
        self.assertGreater(retried.attempts, original.attempts)
        self.assertFalse(self.store.finish(original, error="processing_failed"))
        self.assertIsNone(self.store.claim())
        result = TurnResult(outcome="answer", text="Результат")
        self.assertTrue(self.store.finish(retried, result=result))
        self.assertEqual(self.store.claim().turn_id, second)
        self.assertEqual([message.role for message in self.store.history(self.chat.chat_id, self.chat.chat_token)],
                         ["user", "assistant", "user"])

    def test_retry_replenishes_exhausted_lease_attempts(self):
        first = self.submit()
        stale = [self.store.claim(lease_seconds=0) for _ in range(3)]
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.retry(first).status_code, 202)
        current = self.store.claim()
        self.assertEqual(current.turn_id, first)
        self.assertTrue(all(not self.store.finish(turn, error="processing_failed") for turn in stale))
        self.assertTrue(self.store.finish(current, error="processing_failed"))

    def test_retry_conflicts_after_newer_turn_starts_or_finishes(self):
        first, second = self.submit(), self.submit()
        self.assertTrue(self.store.finish(self.store.claim(), error="processing_failed"))
        later = self.store.claim()
        self.assertEqual(later.turn_id, second)
        self.assertEqual(self.retry(first).status_code, 409)
        self.assertTrue(self.store.finish(later, error="processing_failed"))
        self.assertEqual(self.retry(first).status_code, 409)

    def test_claim_and_retry_race_cannot_publish_newer_turn_first(self):
        for _ in range(12):
            first, second = self.submit(), self.submit()
            self.assertTrue(self.store.finish(self.store.claim(), error="processing_failed"))
            gate = Barrier(2)

            def claim():
                gate.wait(timeout=5)
                return self.store.claim()

            def retry():
                gate.wait(timeout=5)
                return self.retry(first)

            with ThreadPoolExecutor(max_workers=2) as workers:
                claim_result = workers.submit(claim)
                retry_result = workers.submit(retry)
                claimed = claim_result.result(timeout=10)
                accepted = retry_result.result(timeout=10)

            if accepted.status_code == 202:
                claimed = claimed or self.store.claim()
                self.assertEqual(claimed.turn_id, first)
                self.assertTrue(self.store.finish(claimed, error="processing_failed"))
                claimed = self.store.claim()
            else:
                self.assertEqual(accepted.status_code, 409)

            self.assertEqual(claimed.turn_id, second)
            self.assertTrue(self.store.finish(claimed, error="processing_failed"))
