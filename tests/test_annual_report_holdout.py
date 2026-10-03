"""Unmodified parser's third issuer holdout; UNKNOWN is not missing source data.

The first result is frozen before body review. These assertions are a future
regression guard, not an independent test set after any future parser repair.
All network calls in tests are mocked; real source files must remain available.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.extract_annual_report_bundle import ROOT, build_bundle, markdown, read_scope
from scripts.parsing.annual_report_parser import _lines
from scripts.parsing.field_binder import compact
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import capture, select_source, verify_parser
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class AnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_path = ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600900-plan.json"
        cls.plan = json.loads(cls.plan_path.read_bytes())
        cls.scope_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600900-inputs.json").read_bytes()
        cls.scope = read_scope(cls.scope_raw)
        cls.source = cls.scope["sources"][0]
        cls.capture_path = ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600900-capture.json"
        cls.record = json.loads(cls.capture_path.read_bytes())
        cls.raw_dir = ROOT / Path(cls.source["pdf_path"]).parent
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.catalogue = json.loads(cls.catalogue_raw)
        cls.pdf_raw = (ROOT / cls.source["pdf_path"]).read_bytes()
        cls.cache = PDFCache()
        cls.report = build_bundle(cls.scope_raw, cache=cls.cache)
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = cls.cache.parse(cls.pdf_raw, cls.source["pdf_sha256"])
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-600900-2026-10-03-v1"

    def test_blind_protocol_freezes_parser_before_source_review(self):
        verify_parser(self.plan)
        self.assertFalse(self.plan["protocol"]["pdf_body_inspected_before_first_run"])
        self.assertFalse(self.plan["protocol"]["parser_edited_before_first_run"])
        self.assertFalse(self.plan["protocol"]["fixes_in_this_run"])
        self.assertEqual(self.report["manifest"]["code_sha256"], self.plan["parser_code_sha256"])

    def test_capture_scope_and_plan_exact_hash_chain(self):
        self.assertEqual(hashlib.sha256(self.plan_path.read_bytes()).hexdigest(), self.record["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.record["scope_sha256"])
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.capture_path.read_bytes(), (self.raw_dir / "capture.json").read_bytes())
        self.assertEqual(self.record["source"], self.source)
        self.assertEqual(hashlib.sha256((ROOT / "scripts/pilots/capture_annual_holdout.py").read_bytes()).hexdigest(),
                         self.record["capture_code_sha256"])

    def test_raw_catalogue_pdf_and_physical_page_count(self):
        for resource in self.record["resources"]:
            raw = (self.raw_dir / resource["name"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), resource["sha256"])
            self.assertEqual(len(raw), resource["bytes"])
        self.assertEqual(len(self.pdf.pages), 262)
        self.assertEqual(self.pdf.sha256, self.source["pdf_sha256"])

    def test_capture_never_promotes_catalogue_or_fetch_clock(self):
        self.assertFalse(self.record["pdf_body_read"])
        self.assertIsNone(self.record["exact_available_at_utc"])
        self.assertFalse(self.record["complete_revision_chain_verified"])
        self.assertFalse(self.record["snapshot_published"])
        self.assertFalse(self.record["production_reader_ready"])
        self.assertEqual(len(self.record["resources"]), 2)

    def test_frozen_result_reproduces_without_edits(self):
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), markdown(self.report))
        without_self_hash = {key: value for key, value in self.report.items() if key != "logical_content_hash"}
        self.assertEqual(self.report["logical_content_hash"], content_hash(without_self_hash))
        self.assertEqual(self.report["logical_content_hash"], "5fd5ca1be95d0294aca4a0ddb98d888d2e7643f9c6226e9bab32432f7178c9d0")

    def test_one_native_parse_cold_warm_deterministic(self):
        cache = PDFCache()
        first = build_bundle(self.scope_raw, cache=cache)
        second = build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(cache.parsed_documents, 1)
        self.assertEqual(cache.cache_hits, 1)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))

    def test_no_parent_reference_does_not_certify_original_latest_or_revision(self):
        self.assertEqual(self.scope["reference_reports"], [])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")
        self.assertEqual(self.source["version"], "declared_2024_annual_report")

    def test_seven_expected_primary_fields_are_unknown_not_zero(self):
        self.assertEqual(set(self.bundle["fields"]), set(self.plan["expected_field_names"]))
        for field in self.bundle["fields"].values():
            self.assertIsNone(field["observed_value_cny"])
            self.assertIsNone(field["comparative_not_target_value_cny"])
            self.assertEqual(field["state"], "NOT_IDENTIFIED")
            self.assertEqual(field["candidates"], [])

    def test_all_three_headers_fail_closed_without_parent_table_fallback(self):
        self.assertEqual(set(self.bundle["table_states"]), {"balance", "income", "cashflow"})
        for table in self.bundle["table_states"].values():
            self.assertEqual(table["state"], "HEADER_UNIT_YEAR_OR_COLUMNS_UNKNOWN")
            self.assertNotIn("header", table)
        self.assertEqual(self.bundle["balance_sheet_row_inventory"], [])
        self.assertTrue(all(check["state"] == "UNKNOWN" for check in self.bundle["reconciliations"]))

    def test_source_headers_really_have_note_column_and_two_year_amounts(self):
        for number in (88, 92, 95):
            headers = [group for group in _lines(self.pdf.pages[number - 1].words)
                       if any(compact(word.text) == "项目" for word in group)]
            self.assertEqual(len(headers), 1)
            text = compact("".join(word.text for word in headers[0]))
            self.assertIn("附注七", text)
            self.assertIn("2024", text)
            self.assertIn("2023", text)

    def test_native_source_contains_values_despite_failed_extraction(self):
        # Post-blind visual source review, NOT substituted into the frozen bundle.
        for number, tokens in {90: ("210,288,410,895.97", "11,667,482,817.79", "221,955,893,713.76"),
                               93: ("32,496,172,808.65", "32,930,199,395.19"),
                               96: ("59,648,468,284.22", "14,420,079,512.74")}.items():
            for token in tokens:
                self.assertIn(token, self.pdf.pages[number - 1].text)
        self.assertIn("母公司资产负债表", self.pdf.pages[89].text)
        self.assertIn("母公司利润表", "".join(page.text for page in self.pdf.pages[93:95]))

    def test_currency_policy_identified_independently_of_failed_headers(self):
        self.assertEqual(self.bundle["currency"], "CNY")
        self.assertEqual(self.bundle["currency_evidence_pages"], [107])
        self.assertEqual(self.bundle["currency_evidence"][0]["kind"], "SCOPED_CURRENCY_POLICY_DECLARATION")

    def test_narrative_audit_is_present_but_not_promoted_to_gate(self):
        page = self.pdf.pages[84]
        self.assertIn("大华审字[2025]0011006910", page.text)
        self.assertIn("一、审计意见", page.text)
        self.assertNotIn("审计意见类型", page.text)
        audit = self.bundle["audit_text_observation"]
        self.assertIsNone(audit["raw_opinion_type"])
        self.assertIsNone(audit["latest_audit_unmodified_pit"])
        self.assertIsNone(audit["going_concern_uncertainty_pit"])

    def test_unrecognized_lease_label_not_inferred_zero_or_complete(self):
        page = self.pdf.pages[199]
        self.assertIn("支付租赁款", page.text)
        self.assertIn("148,332,535.64", page.text)
        self.assertIn("支付的其他与筹资活动有关的现金", page.text)
        lease = self.bundle["lease_financing_component"]
        self.assertIsNone(lease["observed_value_cny"])
        self.assertFalse(lease["is_complete_lease_cash"])
        self.assertIsNone(lease["full_lease_cash_not_already_deducted"])

    def test_pit_and_real_screening_remain_unopened(self):
        self.assertEqual(self.report["timing_policy"], "UNKNOWN_UNLESS_VERIFIED")
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertTrue(self.report["diagnostic_only"])
        for flag in ("official_selection", "production_reader_ready", "real_pit_run_authorized", "screening_input_exported"):
            self.assertFalse(self.report[flag])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_catalogue_selected_exact_identity_not_summary(self):
        selected = select_source(self.catalogue_raw, self.plan)
        self.assertEqual(selected["announcementId"], "1223421172")
        self.assertNotIn("摘要", selected["announcementTitle"])

    def test_catalogue_rejects_duplicates_and_identity_drift(self):
        cases = []
        for key, value in (("secCode", "002570"), ("orgId", "other"),
                           ("announcementTitle", "长江电力2024年年度报告摘要"),
                           ("adjunctUrl", "finalpage/2025-04-30/1223421164.PDF"), ("announcementTime", False)):
            mutated = deepcopy(self.catalogue)
            row = next(row for row in mutated["announcements"] if row["announcementId"] == "1223421172")
            row[key] = value
            cases.append(mutated)
        duplicate = deepcopy(self.catalogue)
        duplicate["announcements"][0] = deepcopy(duplicate["announcements"][1])
        cases.append(duplicate)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                select_source(json.dumps(case).encode("utf-8"), self.plan)

    def test_catalogue_rejects_pagination_count_and_duplicate_json_key(self):
        for key, value in (("totalAnnouncement", False), ("totalRecordNum", 3),
                           ("totalpages", 1), ("hasMore", True)):
            case = {**self.catalogue, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_source(json.dumps(case).encode("utf-8"), self.plan)
        raw = self.catalogue_raw.replace(b'"hasMore":false', b'"hasMore":false,"hasMore":false')
        self.assertNotEqual(raw, self.catalogue_raw)
        with self.assertRaises(ValueError):
            select_source(raw, self.plan)

    def test_capture_refuses_existing_directory_without_network(self):
        request = Mock()
        with self.assertRaises(FileExistsError):
            capture(self.plan_path, self.raw_dir, request=request)
        request.assert_not_called()

    def test_capture_http_failure_preserves_response_no_retry_or_fallback(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "storage/pilots") as directory:
            output = Path(directory) / "failed-capture"
            for status in (302, 500):
                with self.subTest(status=status):
                    target = output / str(status)
                    request = Mock(return_value=SimpleNamespace(status_code=status, content=b"source unavailable"))
                    with self.assertRaisesRegex(ValueError, "no fallback"):
                        capture(self.plan_path, target, request=request)
                    self.assertEqual(request.call_count, 1)
                    self.assertFalse(request.call_args.kwargs["allow_redirects"])
                    self.assertEqual((target / "catalogue.json").read_bytes(), b"source unavailable")
                    self.assertFalse((target / "annual.pdf").exists())

    def test_capture_reads_metadata_only_with_exact_two_mock_requests(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "storage/pilots") as directory:
            output = Path(directory) / "capture"
            request = Mock(side_effect=[SimpleNamespace(status_code=200, content=self.catalogue_raw),
                                        SimpleNamespace(status_code=200, content=self.pdf_raw)])
            # An interface that deliberately provides no get_text/render methods.
            metadata_only = SimpleNamespace(needs_pass=False, page_count=262)
            with patch("scripts.pilots.capture_annual_holdout.fitz.open") as pdf_open:
                pdf_open.return_value.__enter__.return_value = metadata_only
                result = capture(self.plan_path, output, request=request)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[1].args[:2], ("GET", self.source["url"]))
            self.assertFalse(result["pdf_body_read"])
            self.assertEqual(result["source"]["pdf_sha256"], self.source["pdf_sha256"])
            self.assertEqual(result["source"]["page_count"], 262)

    def test_changed_parser_rejected_against_frozen_commit(self):
        case = deepcopy(self.plan)
        case["parser_code_sha256"]["scripts/parsing/annual_report_parser.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "parser drift"):
            verify_parser(case)


if __name__ == "__main__":
    unittest.main()
