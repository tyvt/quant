"""Bounded public evidence may close raw-file gaps, never authorize PIT research."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "docs/data-pilots/2026-10-01-annual-recorrection-chain-000662.json"
GAPS = ROOT / "docs/data-pilots/2026-10-01-public-evidence-gaps-followup.json"


class RecorrectionCatalogueCaptureTests(TestCase):
    def setUp(self) -> None:
        try:
            from scripts.pilots import capture_recorrection_000662
        except ImportError:
            self.skipTest("optional requests pilot dependency unavailable")
        self.capture_module = capture_recorrection_000662
        self.rows = [
            {"secCode": "000662", "orgId": "gssz0000662", "announcementId": identifier,
             "adjunctUrl": f"finalpage/{day}/{identifier}.PDF", "announcementTime": 1}
            for _, identifier, day in self.capture_module.TARGETS
        ]

    def _raw(self, rows, total=None):
        return json.dumps({"announcements": rows, "totalAnnouncement": len(rows) if total is None else total}).encode()

    def test_target_ids_require_complete_one_page_return_set(self) -> None:
        total, by_id = self.capture_module.select_rows(self._raw(self.rows))
        self.assertEqual(total, 6)
        self.assertEqual(set(by_id), {identifier for _, identifier, _ in self.capture_module.TARGETS})
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.capture_module.select_rows(self._raw(self.rows, 7))
        with self.assertRaisesRegex(ValueError, "required legal document"):
            self.capture_module.select_rows(self._raw(self.rows[:-1]))

    def test_catalogue_identity_duplicates_and_url_drift_hard_fail(self) -> None:
        for field, bad_value in (("secCode", "000637"), ("orgId", "other"), ("adjunctUrl", "https://third-party.invalid/report.PDF")):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = bad_value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.capture_module.select_rows(self._raw(rows))
        with self.assertRaisesRegex(ValueError, "duplicate announcement"):
            self.capture_module.select_rows(self._raw(self.rows + [self.rows[0]]))
        with self.assertRaisesRegex(ValueError, "duplicate catalogue JSON key"):
            self.capture_module.select_rows(b'{"announcements":[],"announcements":[]}')

    def test_existing_capture_is_not_overwritten_or_refetched(self) -> None:
        with TemporaryDirectory() as directory, patch.object(self.capture_module.requests, "post") as post:
            with self.assertRaises(FileExistsError):
                self.capture_module.capture(Path(directory))
            post.assert_not_called()


class RecorrectionEvidenceTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = json.loads(CHAIN.read_text(encoding="utf-8"))

    def test_three_raw_versions_do_not_become_complete_pit_chain(self) -> None:
        probe = self.probe
        self.assertTrue(probe["three_report_versions_fixed"])
        self.assertTrue(probe["two_correction_events_verified"])
        self.assertEqual(len(probe["observed_versions"]), 3)
        for flag in ("research_eligible", "snapshot_published", "production_reader_ready", "complete_revision_chain_verified", "withdrawal_or_platform_replacement_verified", "core_financial_recorrection_fixture_accepted"):
            self.assertFalse(probe[flag])
        self.assertIsNone(probe["exact_available_at_utc"])
        self.assertEqual([row["shareholder_count"] for row in probe["observed_versions"]], ["22917", "31891", "31891"])
        self.assertEqual([row["remuneration_unit_label"] for row in probe["observed_versions"]], ["TEN_THOUSAND_CNY", "TEN_THOUSAND_CNY", "CNY"])
        for row in probe["observed_versions"]:
            self.assertEqual(row["shareholder_count_unit"], "PERSONS")
            self.assertNotIn("shares_issued", row)

    def test_non_midnight_catalogue_time_does_not_fill_available_at(self) -> None:
        for document in self.probe["documents"]:
            observed = datetime.fromtimestamp(document["catalogue_time_raw_ms"] / 1000, timezone.utc)
            self.assertEqual(observed.isoformat(), document["catalogue_time_utc"])
            self.assertEqual((observed.hour, observed.minute), (22, 30))
            self.assertIsNone(document["exact_available_at_utc"])
            self.assertIsNone(document["associate_announcement"])
            self.assertIsNone(document["storage_time"])

    def test_raw_identity_and_physical_pages_match_when_local(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("optional PDF pilot dependency unavailable")
        catalogue = self.probe["catalogue"]
        path = ROOT / catalogue["local_path"]
        if path.is_file():
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), catalogue["sha256"])
            self.assertEqual(len(json.loads(raw)["announcements"]), 14)
        versions = {row["role"]: row for row in self.probe["observed_versions"]}
        for document in self.probe["documents"]:
            path = ROOT / document["local_path"]
            if not path.is_file():
                continue
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), document["sha256"])
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                self.assertEqual(len(pdf), document["pages"])
                if document["role"] not in versions:
                    continue
                version = versions[document["role"]]
                count_text = "".join(pdf[version["shareholder_count_page"] - 1].get_text().split())
                match = re.search(r"股东总数(\d[\d,]*)", count_text)
                self.assertIsNotNone(match)
                self.assertEqual(match[1].replace(",", ""), version["shareholder_count"])
                unit_text = "".join(pdf[version["remuneration_unit_page"] - 1].get_text().split())
                expected = "报酬总额(万元)(税前)" if version["remuneration_unit_label"] == "TEN_THOUSAND_CNY" else "报酬总额(元)(税前)"
                self.assertIn(expected, unit_text)
                audit_text = "".join(pdf[version["embedded_audit_page"] - 1].get_text().split())
                self.assertIn(version["embedded_audit_report_number"], audit_text)


class BoundedPublicGapEvidenceTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = json.loads(GAPS.read_text(encoding="utf-8"))

    def test_bounded_search_is_not_universal_pdf_impossibility(self) -> None:
        probe = self.probe
        self.assertFalse(probe["universal_public_pdf_impossibility_proven"])
        self.assertFalse(probe["research_eligible"])
        self.assertFalse(probe["production_reader_ready"])
        self.assertFalse(probe["snapshot_published"])
        self.assertFalse(probe["cross_issuer_pit_inputs_combined"])
        self.assertFalse(probe["external_evidence_requests_sent"])
        self.assertIsNone(probe["exact_available_at_utc"])
        findings = {row["domain"]: row for row in probe["findings"]}
        self.assertIsNone(findings["financial_statements"]["amended_full_statement_reaudit_stated"])
        self.assertIsNone(findings["financial_statements"]["explicit_no_reaudit_stated"])
        self.assertTrue(findings["financial_statements"]["reference_to_original_report_observed"])
        self.assertIsNone(findings["buybacks"]["actual_last_execution_day"])
        self.assertIsNone(findings["buybacks"]["registration_effective_on"])
        self.assertFalse(findings["shares"]["zero_treasury_attestation_verified"])

    def test_annual_cancellation_corroboration_does_not_create_daily_ledger(self) -> None:
        row = next(item for item in self.probe["findings"] if item["domain"] == "buybacks")
        self.assertEqual(int(row["issuer_reported_issued_shares_before"]) - int(row["issuer_reported_cancelled_shares"]), int(row["issuer_reported_issued_shares_after"]))
        self.assertFalse(row["all_actual_execution_days_known"])
        self.assertEqual(row["plan_id"], "sh.600519:2024-09-21:capital-reduction")

    def test_followup_pdf_hashes_match_when_local(self) -> None:
        for document in self.probe["documents"] + self.probe["existing_documents"]:
            path = ROOT / document.get("file", document.get("local_path"))
            if not path.is_file():
                continue
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"%PDF-"))
            self.assertEqual(hashlib.sha256(raw).hexdigest(), document["sha256"])
