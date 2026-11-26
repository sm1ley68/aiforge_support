import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from evals.run_softline import check_turn, usage_summary


class SoftlineEvalTests(unittest.TestCase):
    def test_acceptance_requires_expected_source_and_does_not_allow_extra_sku(self):
        turn = {
            "status": "succeeded",
            "outcome": "answer",
            "products": [{"offer_id": "123", "sku": "ACTUAL"}],
            "sources": [{"url": "https://example.com/unrelated"}],
            "text": "Подтверждённый факт",
        }
        step = {
            "outcomes": ["answer"],
            "skus": [],
            "source_urls": ["https://example.com/fact"],
            "text_contains": ["факт"],
        }
        self.assertEqual(len(check_turn(turn, step)), 2)

    def test_usage_ignores_other_turns_and_requires_complete_token_counts(self):
        turn_id = "10000000-0000-0000-0000-000000000001"
        other_id = "10000000-0000-0000-0000-000000000002"
        report = {"cases": [{"turns": [{"turn_id": turn_id}]}]}
        input_rate = Decimal("10")
        output_rate = Decimal("20")
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "worker.log"
            log.write_text(
                f"polza_extraction turn_id={turn_id} status=ok duration_ms=10 prompt_tokens=1000 completion_tokens=100\n"
                f"polza_extraction turn_id={other_id} status=ok duration_ms=10 prompt_tokens=4000 completion_tokens=100\n"
            )
            summary = usage_summary(log, report, input_rate, output_rate)
            self.assertEqual(summary["calls"], 1)
            self.assertEqual(Decimal(summary["estimated_cost_rub"]), Decimal("0.012"))
            with log.open("a") as file:
                file.write(
                    f"polza_extraction turn_id={turn_id} status=unavailable duration_ms=10 "
                    "prompt_tokens=None completion_tokens=None\n"
                )
            summary = usage_summary(log, report, input_rate, output_rate)
            self.assertEqual(summary["calls_without_token_counts"], 1)
            self.assertIsNone(summary["estimated_cost_rub"])
