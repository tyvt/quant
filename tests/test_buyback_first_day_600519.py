"""A single exact buyback day tightens, but never resolves, a cumulative interval."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "docs" / "data-pilots" / "2026-10-01-buyback-first-day-600519.json"
B3_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "buybacks"
    / "moutai-2024-plan-cumulative-observations-v1.json"
)
EXPECTED_PROBE_SHA256 = "16864d406c1df9835feeebafbd720e9e624b4f35366b1b9a8338433ebf9e4c0a"


class BuybackFirstDayProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe_bytes = PROBE.read_bytes()
        cls.probe = json.loads(cls.probe_bytes.decode("utf-8"))
        cls.sample = json.loads(B3_FIXTURE.read_text(encoding="utf-8"))["sample"]

    def test_probe_identity_and_raw_pdf_hash(self) -> None:
        self.assertEqual(hashlib.sha256(self.probe_bytes).hexdigest(), EXPECTED_PROBE_SHA256)
        self.assertEqual(self.probe["security_id"], self.sample["security_id"])
        self.assertEqual(self.probe["plan_id"], self.sample["plan_id"])
        raw_pdf = ROOT / self.probe["source"]["local_file"]
        if raw_pdf.exists():
            self.assertEqual(raw_pdf.stat().st_size, self.probe["source"]["bytes"])
            self.assertEqual(
                hashlib.sha256(raw_pdf.read_bytes()).hexdigest(),
                self.probe["source"]["sha256"],
            )

    def test_exact_day_plus_unlocated_remainder_equals_legal_checkpoint(self) -> None:
        first = self.probe["exact_first_execution"]
        remainder = self.probe["unlocated_remainder"]
        checkpoint = self.probe["later_cumulative_checkpoint"]
        legal = self.sample["legal_cumulative_observations"][0]

        self.assertEqual(checkpoint["through"], legal["cumulative_through"])
        self.assertEqual(checkpoint["shares"], int(legal["cumulative_shares"]))
        self.assertEqual(Decimal(checkpoint["amount_cny"]), Decimal(legal["cumulative_amount"]))
        self.assertEqual(first["shares"] + remainder["shares"], checkpoint["shares"])
        self.assertEqual(
            Decimal(first["amount_cny"]) + Decimal(remainder["amount_cny"]),
            Decimal(checkpoint["amount_cny"]),
        )
        self.assertEqual(remainder["interval_start_exclusive"], first["executed_on"])
        self.assertEqual(remainder["interval_end_inclusive"], checkpoint["through"])
        self.assertIsNone(remainder["exact_execution_date"])

    def test_availability_is_not_execution_and_does_not_unlock_research(self) -> None:
        source = self.probe["source"]
        execution = date.fromisoformat(self.probe["exact_first_execution"]["executed_on"])
        document = date.fromisoformat(source["document_date"])
        safe = date.fromisoformat(source["safe_available_on"])
        self.assertLess(execution, document)
        self.assertLess(document, safe)
        self.assertEqual(source["calendar_snapshot_id"], "snapshot-2abff764afcbfb52")
        self.assertIs(self.probe["source_coverage_complete"], False)
        self.assertIs(self.probe["snapshot_published"], False)
        self.assertIs(self.probe["research_eligible"], False)


if __name__ == "__main__":
    unittest.main()
