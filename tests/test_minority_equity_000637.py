"""Close one observed-value gap, not its historical PIT or valuation coverage."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import verify_minority_equity_000637 as pilot


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / pilot.DEFAULT_OUTPUT
HEADER = "茂名石化实华股份有限公司\n1、合并资产负债表\n2025 年12 月31 日\n单位：元"


def word(text, x, y, width=60):
    return (x, y, x + width, y + 10, text, 0, 0, 0)


class MinorityEquitySingleFieldTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((OUTPUT / "diagnostic-only.json").read_bytes())

    def setUp(self):
        self.header_words = [word("期末余额", 274, 200, 36), word("期初余额", 434, 200, 36)]
        self.field_words = [word("少数股东权益", 65, 430),
                            word("94,585,884.15", 308, 430),
                            word("112,947,471.32", 464, 430),
                            word("2、母公司资产负债表", 56, 496, 100)]

    def extract(self, header=HEADER, header_words=None, continuation="合并报表续页", field_words=None):
        return pilot.extract_row(header, header_words or self.header_words, continuation,
                                 self.field_words if field_words is None else field_words)

    def rebuild(self):
        try:
            return pilot.build_supplement(ROOT)
        except (FileNotFoundError, ImportError) as exc:
            self.skipTest(f"optional local PDF dependency/capture absent: {exc}")

    def test_two_fixed_versions_close_only_the_named_source_field(self):
        report = self.report
        self.assertEqual(report["security_id"], "sz.000637")
        self.assertEqual(report["as_of"], "2026-09-30")
        self.assertEqual(report["period_end"], "2025-12-31")
        self.assertEqual(report["gap_resolution"]["target"], "FCF.missing_dependencies.minority_interest")
        self.assertEqual(len(report["observations"]), 2)
        self.assertEqual({item["observed_value"] for item in report["observations"]}, {"94585884.15"})
        self.assertEqual(report["gap_resolution"]["source_observation_after"], "KNOWN_FOR_TWO_FIXED_VERSIONS")

    def test_source_value_does_not_become_pit_alpha_or_fcf(self):
        self.assertEqual(self.report["gap_resolution"]["historical_pit_after"], "UNKNOWN")
        self.assertIsNone(self.report["gap_resolution"]["diagnostic_available_at"])
        self.assertEqual(self.report["gap_resolution"]["pit_admitted_observation_count"], 0)
        for item in self.report["observations"]:
            self.assertIsNone(item["pit_value"])
            self.assertEqual(item["historical_pit_status"], "UNKNOWN")
        self.assertIsNone(self.report["alpha"])
        self.assertIsNone(self.report["FCF"])
        self.assertEqual(self.report["rule_execution"], "NOT_EXECUTED_SOURCE_FIELD_CHECK_ONLY")
        self.assertFalse(self.report["production_reader_ready"])
        self.assertFalse(self.report["real_pit_strategy_run"])
        self.assertFalse(self.report["official_selection"])
        self.assertTrue(self.report["diagnostic_only"])

    def test_column_geometry_not_text_order_selects_closing_value(self):
        parsed = self.extract()
        self.assertEqual(parsed["closing_amount_cny"], "94585884.15")
        self.assertEqual(parsed["opening_comparative_amount_cny"], "112947471.32")
        self.assertEqual(parsed, self.extract(field_words=list(reversed(self.field_words))))

    def test_missing_closing_cell_is_unknown_not_opening_value_or_zero(self):
        parsed = self.extract(field_words=[item for item in self.field_words if item[4] != "94,585,884.15"])
        self.assertIsNone(parsed["closing_amount_cny"])
        self.assertEqual(parsed["closing_state"], "UNKNOWN")
        self.assertEqual(parsed["opening_comparative_amount_cny"], "112947471.32")

    def test_dash_blank_and_known_zero_are_distinct(self):
        for value in (None, "", " ", "-", "—", "–"):
            with self.subTest(value=value):
                self.assertIsNone(pilot.parse_money_cell(value))
        self.assertEqual(pilot.parse_money_cell("0.00"), "0.00")
        changed = copy.deepcopy(self.field_words)
        changed[1] = word("0.00", 308, 430)
        parsed = self.extract(field_words=changed)
        self.assertEqual(parsed["closing_amount_cny"], "0.00")
        self.assertEqual(parsed["closing_state"], "EXPLICIT_NUMERIC")

    def test_invalid_or_nonfinite_currency_text_is_rejected(self):
        for value in ("NaN", "Infinity", "1,234.5", "1,23.00", "94,585,884.15万元"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pilot.parse_money_cell(value)

    def test_issuer_scope_period_and_unit_drift_are_rejected(self):
        for old, new in (("茂名石化实华股份有限公司", "其他发行人"),
                         ("合并资产负债表", "母公司资产负债表"),
                         ("2025 年12 月31 日", "2024 年12 月31 日"),
                         ("单位：元", "单位：万元")):
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, "header mismatch"):
                self.extract(header=HEADER.replace(old, new))

    def test_column_order_and_duplicate_headers_are_rejected(self):
        headers = [word("期末余额", 434, 200, 36), word("期初余额", 274, 200, 36)]
        with self.assertRaisesRegex(ValueError, "column order"):
            self.extract(header_words=headers)
        with self.assertRaisesRegex(ValueError, "ambiguous label"):
            self.extract(header_words=self.header_words + [self.header_words[0]])

    def test_duplicate_target_rows_or_cell_tokens_are_ambiguous(self):
        for extra, message in ((word("少数股东权益", 65, 450), "ambiguous label"),
                               (word("1.00", 310, 430), "ambiguous currency cell")):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, message):
                self.extract(field_words=self.field_words + [extra])

    def test_row_below_parent_table_or_earlier_parent_transition_is_rejected(self):
        changed = copy.deepcopy(self.field_words)
        changed[3] = word("2、母公司资产负债表", 56, 400, 100)
        with self.assertRaisesRegex(ValueError, "outside consolidated"):
            self.extract(field_words=changed)
        with self.assertRaisesRegex(ValueError, "ends before target"):
            self.extract(continuation="2、母公司资产负债表")

    def test_physical_pages_and_catalogue_times_are_bound_but_not_availability(self):
        for doc in self.report["source_documents"]:
            self.assertEqual(doc["evidence_pages"], [93, 94, 95])
            self.assertEqual(doc["physical_page_count"], 209)
            self.assertIsNone(doc["diagnostic_available_at"])
            self.assertFalse(doc["pit_admitted"])
        for item, doc in zip(self.report["observations"], self.report["source_documents"]):
            self.assertEqual(item["evidence_refs"], [base._ref(doc, page) for page in (93, 94, 95)])
        self.assertEqual([doc["url_archive_date"] for doc in self.report["source_documents"]],
                         ["2026-04-29", "2026-08-06"])

    def test_manual_review_is_not_ocr_or_independent_verification(self):
        review = self.report["visual_review"]
        self.assertEqual(review["pages_per_version"], [93, 95])
        self.assertIn("manual_visual_check", review["method"])
        self.assertFalse(review["independent_third_party_review"])
        self.assertFalse(review["render_is_source_evidence"])

    def test_parent_report_hash_and_all_frozen_reports_remain_valid(self):
        parent = self.report["manifest"]["parent_report"]
        raw = base.verified_bytes(ROOT, parent["path"], parent["sha256"])
        parsed = base._json(raw)
        self.assertEqual(parsed["logical_content_hash"], parent["logical_content_hash"])
        self.assertTrue(self.report["parent_report_unchanged"])
        self.assertIn("minority_interest", next(gap for gap in parsed["necessary_input_gaps"]
                                               if gap["field"] == "FCF")["missing_dependencies"])

    def test_two_rebuilds_and_json_reload_match_frozen_output(self):
        first, second = self.rebuild(), self.rebuild()
        self.assertEqual(first, second)
        self.assertEqual(first, self.report)
        self.assertEqual(base.logical_content_hash(first), self.report["logical_content_hash"])
        self.assertEqual((OUTPUT / "diagnostic-only.json").read_bytes(), base.canonical_bytes(first) + b"\n")
        self.assertEqual((OUTPUT / "diagnostic-only.md").read_bytes(),
                         pilot.render_markdown(self.report).encode("utf-8"))

    def test_source_scope_or_comparative_as_closing_tampering_hard_fails(self):
        original_parser = base._json

        def change(raw):
            value = original_parser(raw)
            if value.get("schema_version") == "single_field_evidence_supplement_scope_v1":
                value["documents"][0]["expected_closing_amount_cny"] = "112947471.32"
            return value

        with patch.object(base, "_json", side_effect=change), self.assertRaisesRegex(ValueError, "PDF cells"):
            pilot.build_supplement(ROOT)

        def change_security(raw):
            value = original_parser(raw)
            if value.get("schema_version") == "single_field_evidence_supplement_scope_v1":
                value["security_id"] = "sz.002570"
            return value

        with patch.object(base, "_json", side_effect=change_security), self.assertRaisesRegex(ValueError, "scope mismatch"):
            pilot.build_supplement(ROOT)

    def test_no_readers_premise_or_valuation_run_is_required_to_verify_source_field(self):
        with patch("turtle_quant.pit.parquet_financial_statements.ParquetFinancialStatementsReader.__init__",
                   side_effect=AssertionError("production Reader invoked")), \
             patch("turtle_quant.premise.general_fcf.evaluate_general_fcf",
                   side_effect=AssertionError("premise invoked")), \
             patch("turtle_quant.valuation.absolute.derive_attribution",
                   side_effect=AssertionError("valuation invoked")):
            self.assertEqual(len(self.rebuild()["observations"]), 2)

    def test_existing_output_or_render_directory_is_not_overwritten(self):
        with TemporaryDirectory() as task_dir:
            existing = Path(task_dir) / "existing"
            existing.mkdir()
            marker = existing / "marker.txt"
            marker.write_bytes(b"unchanged")
            with patch.object(pilot, "build_supplement", return_value=self.report), \
                 patch("sys.argv", ["pilot", "--output-dir", str(existing)]), self.assertRaises(FileExistsError):
                pilot.main()
            self.assertEqual(marker.read_bytes(), b"unchanged")
            try:
                with self.assertRaises(FileExistsError):
                    pilot.build_supplement(ROOT, render_dir=existing)
            except (FileNotFoundError, ImportError) as exc:
                self.skipTest(str(exc))

    def test_logical_identity_changes_with_value_timing_or_source_but_not_hash_itself(self):
        original = self.report["logical_content_hash"]
        for section, key, value in (("gap_resolution", "amount_cny_per_version", "0.00"),
                                    ("gap_resolution", "diagnostic_available_at", "2026-08-07")):
            changed = copy.deepcopy(self.report)
            changed[section][key] = value
            self.assertNotEqual(base.logical_content_hash(changed), original)
        changed = {**self.report, "logical_content_hash": "0" * 64}
        self.assertEqual(base.logical_content_hash(changed), original)

    def test_known_row_does_not_claim_audit_or_whole_statement_identity(self):
        self.assertEqual(self.report["gap_resolution"]["version_difference_cny"], "0.00")
        self.assertIn("不证明整份报表", self.report["gap_resolution"]["does_not_prove"])
        for field in ("available_at", "full_amended_audit_status", "complete_revision_chain"):
            self.assertIn(field, self.report["remaining_unknowns"])

    def test_all_used_source_bytes_and_page_counts_verified_if_local(self):
        report = self.rebuild()
        for source in report["source_documents"] + report["manifest"]["catalogue_sources"]:
            self.assertTrue(base.verified_bytes(ROOT, source["path"], source["sha256"]))
