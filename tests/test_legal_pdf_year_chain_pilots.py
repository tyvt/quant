"""Audit-only checks: one issuer/year per PDF route, never production readiness."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from unittest import TestCase

from turtle_quant.pit.parquet_buybacks import ParquetBuybackReader
from turtle_quant.pit.parquet_financial_statements import ParquetFinancialStatementsReader
from turtle_quant.pit.parquet_strategy_inputs import ParquetSharesReader


ROOT = Path(__file__).resolve().parents[1]
PILOTS = ROOT / "docs/data-pilots"
NAMES = {
    "shares": "2026-10-01-shares-year-chain-000858.json",
    "financial_statements": "2026-10-01-financial-year-chain-000637.json",
    "buybacks": "2026-10-01-buyback-plan-chain-600519.json",
}


class LegalPdfYearChainPilotTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = {
            domain: json.loads((PILOTS / filename).read_text(encoding="utf-8"))
            for domain, filename in NAMES.items()
        }

    def test_all_pilots_are_explicitly_non_production(self) -> None:
        for domain, probe in self.probes.items():
            with self.subTest(domain=domain):
                self.assertEqual(probe["schema_version"], "legal_pdf_year_chain_probe_v1")
                self.assertEqual(probe["domain"], domain)
                self.assertEqual(probe["purpose"], "technical_legal_pdf_chain_probe_only")
                self.assertFalse(probe["research_eligible"])
                self.assertFalse(probe["snapshot_published"])
                self.assertFalse(probe["production_reader_ready"])
                self.assertIsNone(probe["exact_available_at_utc"])
                self.assertTrue(probe["blockers"])

    def test_catalogue_response_identity_if_local(self) -> None:
        for domain, probe in self.probes.items():
            with self.subTest(domain=domain):
                catalogue = probe["catalogue"]
                self.assertEqual(catalogue["reported_total"], catalogue["returned_count"])
                self.assertEqual(catalogue["reported_total"], catalogue["unique_adjunct_urls"])
                paths = [
                    ROOT / catalogue["local_dir"] / f"cninfo-catalogue-page-{n}.json"
                    for n in range(1, len(catalogue["page_sha256_in_order"]) + 1)
                ]
                if not all(path.exists() for path in paths):
                    continue  # Raw pilot captures are deliberately outside version control.
                rows = []
                for path, digest in zip(paths, catalogue["page_sha256_in_order"]):
                    raw = path.read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                    response = json.loads(raw)
                    self.assertEqual(response["totalAnnouncement"], catalogue["reported_total"])
                    rows.extend(response["announcements"])
                urls = {row["adjunctUrl"] for row in rows}
                self.assertEqual(len(rows), catalogue["returned_count"])
                self.assertEqual(len(urls), catalogue["unique_adjunct_urls"])
                for document in probe["documents"]:
                    self.assertIn(
                        document["source_url"].removeprefix("https://static.cninfo.com.cn/"),
                        urls,
                    )

    def test_original_pdf_hashes_and_evidence_pages_if_local(self) -> None:
        for domain, probe in self.probes.items():
            for doc in probe["documents"]:
                with self.subTest(domain=domain, role=doc["role"]):
                    if "local_path" in doc:
                        path = ROOT / doc["local_path"]
                    else:
                        path = ROOT / probe["catalogue"]["local_dir"] / doc["file"]
                    if not path.exists():
                        continue  # Raw pilot captures are deliberately outside version control.
                    raw = path.read_bytes()
                    self.assertTrue(raw.startswith(b"%PDF-"))
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), doc["sha256"])
                    for page in doc.get("evidence_pages", []):
                        self.assertGreater(page, 0)
                        if "pages" in doc:
                            self.assertLessEqual(page, doc["pages"])

    def test_share_endpoints_do_not_become_daily_pit_values(self) -> None:
        probe = self.probes["shares"]
        self.assertFalse(probe["daily_s_coverage_complete"])
        bridge = probe["observed_share_bridge"]
        endpoints = (
            "2024_opening", "2024_closing", "2025h1_opening",
            "2025h1_closing", "2025_opening", "2025_closing",
        )
        self.assertEqual({int(bridge[key]) for key in endpoints}, {3_881_608_005})
        self.assertEqual(bridge["2025_annual_buyback_implementation"], "NOT_APPLICABLE_REPORTED")
        self.assertNotEqual(bridge["2025_treasury_balance"], "0")
        roles = {doc["role"] for doc in probe["documents"]}
        self.assertIn("2025annual", roles)
        self.assertIn("2026_future_buyback_plan_not_2025_event", roles)

    def test_financial_revision_has_unverified_later_version_and_audit(self) -> None:
        probe = self.probes["financial_statements"]
        prior = json.loads((ROOT / probe["prior_four_way_value_probe"]).read_text(encoding="utf-8"))
        revision = probe["observed_revision"]
        previous = prior["observed_revision"]
        self.assertFalse(probe["complete_revision_chain_verified"])
        self.assertEqual(revision["original_value"], previous["original_value"])
        self.assertEqual(revision["amended_value"], previous["amended_value"])
        self.assertEqual(
            Decimal(revision["amended_value"]) - Decimal(revision["original_value"]),
            Decimal(revision["delta"]),
        )
        by_role = {doc["role"]: doc for doc in probe["documents"]}
        special = by_role["auditor_special_review_image_only"]
        self.assertEqual(special["special_review_scope_verified"], "bill_discount_business_adjustment_only")
        self.assertFalse(special["amended_full_statements_audit_opinion_verified"])
        later = by_role["later_financial_bundle_partially_reconciled"]
        self.assertEqual(later["checked_audit_report_date"], "2026-04-27")
        self.assertEqual(later["checked_operating_cash_flow_cny"], revision["original_value"])
        self.assertNotEqual(later["checked_operating_cash_flow_cny"], revision["amended_value"])
        self.assertFalse(later["whole_bundle_version_relation_verified"])

    def test_buyback_cumulative_differences_do_not_create_execution_days(self) -> None:
        probe = self.probes["buybacks"]
        self.assertFalse(probe["all_actual_execution_days_known"])
        first = probe["verified_execution_day"]
        self.assertEqual(first["executed_on"], "2025-01-02")
        self.assertIsNone(probe["actual_last_execution_day"])
        self.assertEqual(probe["reported_plan_completion_on"], "2025-08-29")
        shares = int(first["shares"])
        amount = Decimal(first["amount_cny"])
        previous_date = date.fromisoformat(first["executed_on"])
        for checkpoint in probe["cumulative_checkpoints"]:
            with self.subTest(through=checkpoint["through"]):
                cutoff = date.fromisoformat(checkpoint["through"])
                self.assertGreater(cutoff, previous_date)
                self.assertGreater(int(checkpoint["shares"]), shares)
                self.assertEqual(
                    Decimal(checkpoint["amount_cny"]) - amount,
                    Decimal(checkpoint["delta_amount_cny"]),
                )
                self.assertGreater(Decimal(checkpoint["delta_amount_cny"]), 0)
                shares, amount, previous_date = (
                    int(checkpoint["shares"]),
                    Decimal(checkpoint["amount_cny"]),
                    cutoff,
                )
        self.assertEqual(shares, 3_927_585)
        self.assertEqual(amount, Decimal("5999985966.95"))
        self.assertEqual(1_256_197_800 - 1_252_887_715, 3_310_085)

    def test_pilots_do_not_unlock_production_readers(self) -> None:
        snapshot_root = ROOT / "storage/snapshots"
        with self.assertRaisesRegex(NotImplementedError, "not ready"):
            ParquetSharesReader(snapshot_root).shares_on("sz.000858", as_of=date(2025, 12, 31))
        with self.assertRaisesRegex(NotImplementedError, "not ready"):
            ParquetFinancialStatementsReader(snapshot_root).get_financial_record(
                "sz.000637", date(2025, 12, 31), as_of=date(2026, 8, 7)
            )
        with self.assertRaisesRegex(NotImplementedError, "not ready"):
            ParquetBuybackReader(snapshot_root).buyback_events(
                "sh.600519", date(2025, 1, 1), date(2025, 12, 31), as_of=date(2026, 1, 1)
            )
