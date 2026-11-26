import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from softline_backend.catalog import build_index
from softline_backend.contracts import MessageView
from softline_backend.task_search import task_reply


def offer(sku, *, description="Защита почты и файлов", deployment="on-premise",
          users=100, currency="RUB", price=9000, origin="Россия", available="true"):
    return f"""
      <offer id="{sku}" available="{available}">
        <name>Demo {sku}</name><vendorCode>{sku}</vendorCode>
        <description>{description}</description>
        <param name="Развёртывание">{deployment}</param>
        <param name="Количество пользователей">{users}</param>
        <param name="Страна происхождения">{origin}</param>
        <currencyId>{currency}</currencyId><price>{price}</price>
        <url>https://example.com/offers/{sku}</url>
      </offer>"""


class TaskSearchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name)
        feed = folder / "feed.xml"
        positions = (
            offer("FIT") + offer("CLOUD", deployment="cloud")
            + offer("SMALL", users=25) + offer("USD", currency="USD")
            + offer("LIMIT-UNKNOWN", users="")
            + offer("FOREIGN", origin="Германия", price=8000)
            + offer("ORIGIN-UNKNOWN", origin="")
            + offer("NO-STOCK", available="false")
            + offer("FILES-ONLY", description="Защита файлов")
        )
        feed.write_text(
            '<yml_catalog date="2026-11-26T12:00:00+03:00"><shop><offers>'
            f"{positions}</offers></shop></yml_catalog>"
        )
        self.index = folder / "catalog.sqlite3"
        build_index(feed, self.index)

    @staticmethod
    def history(*messages):
        return [MessageView(turn_id=uuid4(), role="user", text=text) for text in messages]

    def test_followups_preserve_requirements_and_update_budget(self):
        history = self.history(
            "Подбери защиту почты и файлов на 50 сотрудников",
            "Только локально",
            "Бюджет до 10 000 рублей",
        )
        result = task_reply(self.index, "Покажи российский аналог", history)
        self.assertEqual(result.outcome, "answer")
        self.assertEqual([card.sku for card in result.products], ["FIT"])
        self.assertIn("50", result.text)
        self.assertEqual({fact.field for fact in result.products[0].verified_facts},
                         {"deployment", "user_limit", "origin"})

        changed = task_reply(
            self.index, "Бюджет снизился до 8 500 рублей",
            history + self.history("Покажи российский аналог"),
        )
        self.assertEqual(changed.outcome, "clarify")
        self.assertEqual(changed.products, [])

    def test_fresh_task_does_not_inherit_previous_task_constraints(self):
        history = self.history("Подбери защиту почты и файлов", "Бюджет до 1 рубля")
        new = task_reply(self.index, "Подбери защиту файлов", history)
        self.assertEqual(new.outcome, "answer")
        self.assertTrue(new.products)
        self.assertIsNone(task_reply(self.index, "Только локально", []))
