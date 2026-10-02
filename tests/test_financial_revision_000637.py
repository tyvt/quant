"""Audit-only checks for one legal-PDF financial revision, not domain readiness."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import TestCase

from turtle_quant.pit.parquet_financial_statements import ParquetFinancialStatementsReader


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/data-pilots/2026-10-01-financial-revision-000637.json"


class FinancialRevisionProbeTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_not_research_eligible_and_revision_date_not_cover_date(self) -> None:
        self.assertEqual(self.probe["security_id"], "sz.000637")
        self.assertFalse(self.probe["research_eligible"])
        self.assertFalse(self.probe["snapshot_published"])
        self.assertFalse(self.probe["source_coverage_complete"])
        self.assertIsNone(self.probe["exact_available_at_utc"])
        by_role = {doc["role"]: doc for doc in self.probe["documents"]}
        self.assertEqual(len(by_role), 5)
        original = by_role["original_2025_annual_report"]
        amended = by_role["amended_2025_annual_report"]
        self.assertEqual(original["catalogue_date"], "2026-04-29")
        self.assertEqual(amended["catalogue_date"], "2026-08-06")
        self.assertEqual(original["pdf_cover_date"], amended["pdf_cover_date"])
        self.assertNotEqual(original["catalogue_date"], amended["catalogue_date"])
        for doc in self.probe["documents"]:
            with self.subTest(role=doc["role"]):
                marker = datetime.fromtimestamp(
                    doc["catalogue_announcement_time_raw_ms"] / 1000,
                    timezone(timedelta(hours=8)),
                )
                self.assertEqual(marker.date().isoformat(), doc["catalogue_date"])
                self.assertEqual(marker.time().isoformat(), "00:00:00")

    def test_operating_cash_flow_revision_is_exact_and_page_bound(self) -> None:
        item = self.probe["observed_revision"]
        self.assertEqual(item["statement"], "consolidated_cash_flow")
        self.assertEqual(item["period_end"], self.probe["period_end"])
        self.assertEqual(
            Decimal(item["amended_value"]) - Decimal(item["original_value"]),
            Decimal(item["delta"]),
        )
        self.assertGreater(Decimal(item["original_value"]), 0)
        self.assertLess(Decimal(item["amended_value"]), 0)
        by_hash = {doc["sha256"]: doc for doc in self.probe["documents"]}
        for key in (
            "original_evidence_ref",
            "correction_evidence_ref",
            "amended_report_evidence_ref",
            "corrected_statement_evidence_ref",
        ):
            digest, page = item[key].removeprefix("sha256:").split("#page=")
            self.assertIn(digest, by_hash)
            self.assertTrue(1 <= int(page) <= by_hash[digest]["pages"])

    def test_frozen_pdf_bytes_match_if_local(self) -> None:
        paths = [ROOT / doc["local_path"] for doc in self.probe["documents"]]
        if not all(path.exists() for path in paths):
            self.skipTest("raw legal PDFs are local pilot artifacts")
        for doc, path in zip(self.probe["documents"], paths):
            with self.subTest(role=doc["role"]):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"%PDF-"))
                self.assertEqual(len(raw), doc["bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), doc["sha256"])

    def test_financial_reader_still_fails_closed(self) -> None:
        reader = ParquetFinancialStatementsReader(ROOT / "storage/snapshots")
        with self.assertRaisesRegex(NotImplementedError, "not ready"):
            reader.get_financial_record(
                "sz.000637", date(2025, 12, 31), as_of=date(2026, 8, 7)
            )
