"""Pilot evidence checks; a page screen never grants financial-domain readiness."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/data-pilots/2026-10-01-financial-year-chain-000637.json"


class FinancialYearChainProbeTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_later_application_material_does_not_close_revision_chain(self) -> None:
        probe = self.probe
        self.assertFalse(probe["research_eligible"])
        self.assertFalse(probe["snapshot_published"])
        self.assertFalse(probe["production_reader_ready"])
        self.assertFalse(probe["complete_revision_chain_verified"])
        self.assertIsNone(probe["exact_available_at_utc"])

        documents = {item["role"]: item for item in probe["documents"]}
        bundle = documents["later_financial_bundle_partially_reconciled"]
        prospectus = documents["same_day_prospectus_application"]
        correction = documents["correction_announcement"]
        self.assertFalse(bundle["numeric_identity_proven"])
        self.assertFalse(bundle["whole_bundle_version_relation_verified"])
        self.assertEqual(bundle["page_ranges"]["2026_half_year_cash_flows"], [131, 132])
        self.assertEqual(bundle["screening_threshold_empirical"], 0.04)
        self.assertEqual(prospectus["search_scope"], "extractable_text_only")
        self.assertFalse(prospectus["amended_full_statements_audit_opinion_verified"])
        self.assertFalse(prospectus["legal_replacement_relation_verified"])
        self.assertEqual(documents["2026_half_year_comparison_document"]["audit_status"], "unaudited")
        self.assertEqual(
            correction["correction_scope_stated"],
            "2023_to_2026q1_cash_flow_classification_only",
        )
        self.assertIn(26, correction["evidence_pages"])

        revision = probe["observed_revision"]
        self.assertEqual(
            Decimal(revision["amended_value"]) - Decimal(revision["original_value"]),
            Decimal(revision["delta"]),
        )

    def test_frozen_pdf_hashes_match_when_local(self) -> None:
        for document in self.probe["documents"]:
            path = ROOT / document["local_path"]
            if not path.exists():
                continue  # Pilot raw files may be absent from another checkout.
            with self.subTest(role=document["role"]):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"%PDF-"))
                self.assertEqual(hashlib.sha256(raw).hexdigest(), document["sha256"])

    def test_full_page_screen_exposes_ambiguous_nearest_neighbours(self) -> None:
        report = json.loads((ROOT / self.probe["complete_page_screen_report"]).read_text(encoding="utf-8"))
        self.assertEqual(report["original_pages"], 120)
        self.assertEqual(report["candidate_pages"], 136)
        self.assertEqual(len(report["page_matches"]), 120)
        self.assertEqual(len(report["candidate_text_inventory"]), 136)
        self.assertEqual(report["same_index_close_count"], 116)
        self.assertEqual(report["close_match_count"], 120)
        self.assertEqual(len(report["ambiguous_original_pages"]), 120)
        by_page = {row["original_page"]: row for row in report["page_matches"]}
        for page in (13, 14, 19, 20):
            self.assertEqual(by_page[page]["candidate_page"], 60)
            self.assertTrue(by_page[page]["ambiguous_close_match"])
            self.assertFalse(by_page[page]["same_index_passes_threshold"])
        for row in report["candidate_text_inventory"][124:]:
            self.assertEqual(row["extractable_text_characters"], 0)
        self.assertFalse(report["identity_proven"])
        self.assertFalse(report["numeric_identity_proven"])


class FinancialCashFlowCrosscheckTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = json.loads((ROOT / "docs/data-pilots/2026-10-01-financial-cashflow-crosscheck-000637.json").read_text(encoding="utf-8"))
        cls.items = {row["id"]: row for row in cls.probe["items"]}

    def test_reclassification_cancels_without_changing_total_cash(self) -> None:
        transfer = Decimal(self.probe["observed_transfer_cny"])
        for name in ("sales_cash_receipts", "operating_inflow", "operating_net"):
            row = self.items[name]
            self.assertEqual(Decimal(row["amended_value"]) - Decimal(row["original_value"]), -transfer)
        for name in ("financing_inflow", "financing_net"):
            row = self.items[name]
            self.assertEqual(Decimal(row["amended_value"]) - Decimal(row["original_value"]), transfer)
        for column in ("original_value", "amended_value", "september_value"):
            value = lambda name: Decimal(self.items[name][column])
            self.assertEqual(value("operating_inflow") - value("operating_outflow"), value("operating_net"))
            self.assertEqual(value("financing_inflow") - value("financing_outflow"), value("financing_net"))
            self.assertEqual(value("operating_net") + value("investing_net") + value("financing_net"), value("cash_net_increase"))
            self.assertEqual(value("cash_begin") + value("cash_net_increase"), value("cash_end"))

    def test_later_old_values_do_not_become_pit_or_full_statement_proof(self) -> None:
        self.assertEqual(len(self.items), 12)
        self.assertEqual(self.probe["statement_scope"], "CONSOLIDATED")
        self.assertIsNone(self.probe["exact_available_at_utc"])
        for flag in ("research_eligible", "snapshot_published", "production_reader_ready", "complete_revision_chain_verified", "full_statement_numeric_identity_proven", "amended_full_statements_audit_opinion_verified", "legal_replacement_relation_verified"):
            self.assertFalse(self.probe[flag])
        for row in self.items.values():
            self.assertEqual(row["september_value"], row["original_value"])
        self.assertNotEqual(self.items["operating_net"]["september_value"], self.items["operating_net"]["amended_value"])

    def test_selected_numbers_and_pdf_identities_are_present_when_local(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("optional PDF pilot dependencies unavailable")
        for document in self.probe["documents"]:
            path = ROOT / document["path"]
            if not path.is_file():
                continue
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), document["sha256"])
            if document["id"] == "september_bundle":
                continue  # Image-only source values require the recorded visual review.
            column = "amended_value" if document["id"] in ("amended_annual", "corrected_statements") else "original_value"
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                for row in self.items.values():
                    page = row["source_pages"][document["id"]]
                    tokens = re.findall(r"-?\d[\d,]*\.\d{2}", pdf[page - 1].get_text())
                    with self.subTest(document=document["id"], item=row["id"]):
                        self.assertIn(Decimal(row[column]), [Decimal(token.replace(",", "")) for token in tokens])


class PdfScreeningBoundaryTests(TestCase):
    def _dependencies(self):
        try:
            import fitz
            from scripts.pilots.compare_pdf_page_renders import compare
        except ImportError:
            self.skipTest("optional PDF pilot dependencies unavailable")
        return fitz, compare

    def test_full_page_inventory_is_bound_to_raw_pdf_hashes(self) -> None:
        fitz, compare = self._dependencies()
        with TemporaryDirectory() as directory:
            source = Path(directory) / "two-pages.pdf"
            with fitz.open() as document:
                document.new_page().insert_text((72, 72), "Page 1 amount 123.45")
                document.new_page().insert_text((72, 72), "Page 2 amount 678.90")
                document.save(source)
            result = compare(source, source, 0.04)
            self.assertEqual(result, compare(source, source, 0.04))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(result["original_sha256"], digest)
        self.assertEqual(result["candidate_sha256"], digest)
        self.assertEqual([row["original_page"] for row in result["page_matches"]], [1, 2])
        self.assertEqual(len(result["candidate_text_inventory"]), 2)
        self.assertTrue(all(row["same_index_extracted_numbers_equal"] for row in result["page_matches"]))
        self.assertFalse(result["numeric_identity_proven"])

    def test_empty_text_never_proves_extracted_number_equality(self) -> None:
        fitz, compare = self._dependencies()
        with TemporaryDirectory() as directory:
            source = Path(directory) / "blank.pdf"
            with fitz.open() as document:
                document.new_page()
                document.save(source)
            result = compare(source, source, 0.04)
        self.assertIsNone(result["page_matches"][0]["same_index_extracted_numbers_equal"])
        self.assertFalse(result["numeric_identity_proven"])
        self.assertFalse(result["identity_proven"])

    def test_repeated_candidate_pages_are_flagged_as_ambiguous(self) -> None:
        fitz, compare = self._dependencies()
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            candidate = Path(directory) / "repeated.pdf"
            with fitz.open() as document:
                document.new_page().insert_text((72, 72), "Repeated template")
                document.save(source)
            with fitz.open(source) as original, fitz.open() as repeated:
                repeated.insert_pdf(original)
                repeated.insert_pdf(original)
                repeated.save(candidate)
            result = compare(source, candidate, 0.04)
        self.assertEqual(result["page_matches"][0]["close_candidate_pages"], [1, 2])
        self.assertEqual(result["ambiguous_original_pages"], [1])
        self.assertFalse(result["identity_proven"])

    def test_threshold_decision_uses_unrounded_distance(self) -> None:
        fitz, compare = self._dependencies()
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            with fitz.open() as document:
                document.new_page()
                document.save(source)
            with patch("scripts.pilots.compare_pdf_page_renders._distance", return_value=0.0400004):
                result = compare(source, source, 0.04)
        self.assertEqual(result["page_matches"][0]["distance"], 0.04)
        self.assertFalse(result["page_matches"][0]["passes_threshold"])
        self.assertEqual(result["close_match_count"], 0)
        self.assertEqual(result["same_index_close_count"], 0)
        self.assertEqual(result["candidate_pages_without_close_original_match"], [1])

    def test_invalid_threshold_is_rejected_before_reading_pdfs(self) -> None:
        _, compare = self._dependencies()
        for threshold in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(threshold=threshold), self.assertRaisesRegex(ValueError, "threshold"):
                compare(Path("not-read.pdf"), Path("not-read-either.pdf"), threshold)

    def test_identical_render_is_still_not_identity_proof(self) -> None:
        try:
            import fitz
            from scripts.pilots.compare_pdf_page_renders import compare
        except ImportError:
            self.skipTest("optional PDF pilot dependencies unavailable")

        with TemporaryDirectory() as directory:
            source = Path(directory) / "one-page.pdf"
            document = fitz.open()
            document.new_page().insert_text((72, 72), "Pilot screening only")
            document.save(source)
            document.close()
            result = compare(source, source, threshold=0.04)

        self.assertEqual(result["same_index_close_count"], 1)
        self.assertFalse(result["identity_proven"])
        self.assertEqual(
            result["threshold_kind"], "empirical_screening_only_not_a_universal_standard"
        )
