"""Fixed-document E and source alpha do not become historical PIT inputs."""

from __future__ import annotations

import copy
from decimal import Decimal, ROUND_DOWN, localcontext
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import verify_attributable_equity_000637 as pilot
from scripts.pilots import verify_minority_equity_000637 as minority


ROOT = Path(__file__).resolve().parents[1]
HEADER = "茂名石化实华股份有限公司\n1、合并资产负债表\n2025 年12 月31 日\n单位：元"
ALPHA = "0.8421488241705548591131801230"


def word(text, x, y, width=60):
    return (x, y, x + width, y + 9, text, 0, 0, 0)


class AttributableEquitySourceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = pilot.build_supplement(ROOT)

    def setUp(self):
        self.header_words = [word("期末余额", 274, 200, 36), word("期初余额", 434, 200, 36)]
        self.field_words = [word(pilot.E_LABEL, 56, 420, 117),
                            word("504,623,362.49", 304, 420), word("645,132,659.65", 464, 420),
                            word("少数股东权益", 65, 432),
                            word("94,585,884.15", 308, 432), word("112,947,471.32", 464, 432),
                            word("所有者权益合计", 56, 444),
                            word("599,209,246.64", 304, 444), word("758,080,130.97", 464, 444),
                            word("2、母公司资产负债表", 56, 496, 100)]

    def extract(self, *, header=HEADER, header_words=None, continuation="合并表续页", words=None):
        return pilot.extract_equity_bridge(header, self.header_words if header_words is None else header_words,
                                           continuation, self.field_words if words is None else words)

    def inputs(self):
        return copy.deepcopy(self.report["observations"][0]), copy.deepcopy(self.report["existing_N_dependencies"][0])

    def test_two_versions_bind_period_end_E_not_opening_or_total_equity(self):
        self.assertEqual(self.report["gap_resolution"]["target"], "FCF.missing_dependencies.attributable_equity")
        self.assertEqual({item["observed_value"] for item in self.report["observations"]}, {"504623362.49"})
        self.assertEqual({item["opening_comparative_not_target_value"] for item in self.report["observations"]},
                         {"645132659.65"})
        self.assertEqual(len(self.report["source_documents"]), 2)

    def test_column_geometry_not_word_order_selects_E(self):
        parsed = self.extract()
        self.assertEqual(parsed["E"]["closing_amount_cny"], "504623362.49")
        self.assertEqual(parsed, self.extract(words=list(reversed(self.field_words))))

    def test_missing_E_cell_stays_unknown_not_opening_value(self):
        words = [item for item in self.field_words if item[4] != "504,623,362.49"]
        parsed = self.extract(words=words)
        self.assertIsNone(parsed["E"]["closing_amount_cny"])
        self.assertEqual(parsed["E"]["closing_state"], "UNKNOWN")
        self.assertEqual(parsed["E"]["opening_comparative_amount_cny"], "645132659.65")
        self.assertEqual(parsed["total_equity_corroboration"]["closing_amount_cny"]["status"], "UNKNOWN")

    def test_dash_unknown_E_is_not_known_zero(self):
        words = [word("—", 304, 420) if item[4] == "504,623,362.49" else item for item in self.field_words]
        self.assertIsNone(self.extract(words=words)["E"]["closing_amount_cny"])
        self.assertIsNone(minority.parse_money_cell("—"))
        self.assertEqual(minority.parse_money_cell("0.00"), "0.00")

    def test_same_column_E_N_total_bridge_reconciles_in_both_columns(self):
        parsed = self.extract()
        for check in parsed["total_equity_corroboration"].values():
            self.assertEqual(check["status"], "RECONCILED")
            self.assertEqual(Decimal(check["difference_cny"]), 0)
        self.assertEqual(parsed["total_equity_corroboration"]["closing_amount_cny"]["reported_total_equity_cny"],
                         "599209246.64")

    def test_wrong_total_equity_does_not_silently_override_E(self):
        words = [word("599,209,246.65", 304, 444) if item[4] == "599,209,246.64" else item
                 for item in self.field_words]
        with self.assertRaisesRegex(ValueError, "differs from reported total"):
            self.extract(words=words)

    def test_duplicate_E_labels_or_split_numeric_cells_fail(self):
        for extra in (word(pilot.E_LABEL, 56, 422, 117), word("1.00", 304, 420)):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "ambiguous"):
                self.extract(words=self.field_words + [extra])

    def test_parent_table_boundary_or_early_transition_fails(self):
        words = [word("2、母公司资产负债表", 56, 400, 100) if item[4] == "2、母公司资产负债表" else item
                 for item in self.field_words]
        with self.assertRaisesRegex(ValueError, "outside consolidated"):
            self.extract(words=words)
        with self.assertRaisesRegex(ValueError, "ends before target"):
            self.extract(continuation="2、母公司资产负债表")

    def test_wrong_issuer_period_scope_unit_or_columns_fail(self):
        for old, new in (("茂名石化实华股份有限公司", "其他公司"), ("合并资产负债表", "母公司资产负债表"),
                         ("2025 年12 月31 日", "2024 年12 月31 日"), ("单位：元", "单位：万元")):
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, "header mismatch"):
                self.extract(header=HEADER.replace(old, new))
        with self.assertRaisesRegex(ValueError, "column order"):
            self.extract(header_words=list(reversed([
                word("期初余额", 274, 200, 36), word("期末余额", 434, 200, 36)])))

    def test_source_alpha_formula_uses_same_version_E_and_N(self):
        for result in self.report["source_alpha_arithmetic_not_pit"]:
            self.assertEqual(result["alpha_observed"], ALPHA)
            self.assertEqual(result["denominator_cny"], "599209246.64")
            self.assertEqual(result["status"], "SOURCE_ARITHMETIC_ONLY_NOT_PIT")
            self.assertIsNone(result["alpha_pit"])

    def test_each_join_key_rejects_cross_version_or_cross_pdf_mix(self):
        for key in pilot.JOIN_KEYS:
            e, n = self.inputs()
            n[key] = "different"
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity mismatch"):
                pilot.calculate_source_alpha(e, n)

    def test_missing_join_identity_is_not_proof_of_alignment(self):
        e, n = self.inputs()
        del e["document_sha256"]
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            pilot.calculate_source_alpha(e, n)

    def test_missing_E_or_N_does_not_fill_zero_or_compute_alpha(self):
        for target in ("E", "N"):
            e, n = self.inputs()
            (e if target == "E" else n)["observed_value"] = None
            parsed = pilot.calculate_source_alpha(e, n)
            self.assertIsNone(parsed["alpha_observed"])
            self.assertEqual(parsed["status"], "UNKNOWN")

    def test_nonpositive_E_preserves_source_but_cannot_form_alpha(self):
        for value in ("0.00", "-1.00"):
            e, n = self.inputs()
            e["observed_value"] = value
            parsed = pilot.calculate_source_alpha(e, n)
            self.assertEqual(parsed["E_observed_cny"], value)
            self.assertIsNone(parsed["alpha_observed"])

    def test_negative_N_max_zero_is_formula_not_a_missing_data_fill(self):
        for value in ("0.00", "-1.00"):
            e, n = self.inputs()
            n["observed_value"] = value
            parsed = pilot.calculate_source_alpha(e, n)
            self.assertEqual(parsed["alpha_observed"], "1")
            self.assertEqual(parsed["denominator_cny"], e["observed_value"])

    def test_nonfinite_or_boolean_equity_is_not_numeric_evidence(self):
        for value in ("NaN", "Infinity", True):
            e, n = self.inputs()
            e["observed_value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                pilot.calculate_source_alpha(e, n)

    def test_source_arithmetic_does_not_depend_on_callers_decimal_context(self):
        e, n = self.inputs()
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_DOWN
            self.assertEqual(pilot.calculate_source_alpha(e, n)["alpha_observed"], ALPHA)

    def test_pit_availability_and_FCF_remain_unknown(self):
        for field in ("E_pit", "N_pit", "alpha_pit", "FCF", "diagnostic_available_at"):
            self.assertIsNone(self.report[field])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["real_pit_strategy_run"])
        self.assertFalse(self.report["production_reader_ready"])
        for item in self.report["observations"]:
            self.assertIsNone(item["pit_value"])
            self.assertEqual(item["historical_pit_status"], "UNKNOWN")

    def test_report_authority_PIT_or_alpha_tampering_hard_fails(self):
        for key, value in (("official_selection", True), ("alpha_pit", ALPHA), ("FCF", "0.00")):
            altered = copy.deepcopy(self.report)
            altered[key] = value
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.validate_supplement(altered)
        altered = copy.deepcopy(self.report)
        altered["source_alpha_arithmetic_not_pit"][0]["alpha_observed"] = "1"
        altered["logical_content_hash"] = base.logical_content_hash(altered)
        with self.assertRaisesRegex(ValueError, "arithmetic"):
            pilot.validate_supplement(altered)

    def test_ranking_output_is_rejected_even_after_rehash(self):
        altered = copy.deepcopy(self.report)
        altered["ranking"] = []
        altered["logical_content_hash"] = base.logical_content_hash(altered)
        with self.assertRaisesRegex(ValueError, "forbidden"):
            pilot.validate_supplement(altered)

    def test_field_physical_page_binding_cannot_be_changed(self):
        altered = copy.deepcopy(self.report)
        altered["observations"][0]["evidence_refs"][0] = "physical-page:96"
        altered["logical_content_hash"] = base.logical_content_hash(altered)
        with self.assertRaisesRegex(ValueError, "physical page binding"):
            pilot.validate_supplement(altered)

    def test_parent_and_N_report_remain_byte_identical(self):
        for key in ("parent_report", "minority_supplement"):
            reference = self.report["manifest"][key]
            raw = base.verified_bytes(ROOT, reference["path"], reference["sha256"])
            self.assertEqual(base.logical_content_hash(base._json(raw)), reference["logical_content_hash"])
        self.assertTrue(self.report["parent_report_unchanged"])
        self.assertTrue(self.report["minority_supplement_unchanged"])

    def test_two_rebuilds_and_json_reload_match_frozen_output(self):
        first, second = pilot.build_supplement(ROOT), pilot.build_supplement(ROOT)
        self.assertEqual(first, second)
        output = ROOT / pilot.DEFAULT_OUTPUT
        self.assertEqual((output / "diagnostic-only.json").read_bytes(), base.canonical_bytes(first) + b"\n")
        self.assertEqual((output / "diagnostic-only.md").read_bytes(), pilot.render_markdown(first).encode("utf-8"))
        reloaded = base._json(base.canonical_bytes(first))
        self.assertEqual(pilot.render_markdown(first), pilot.render_markdown(reloaded))

    def test_fresh_offline_process_checks_output_and_never_calls_real_rules(self):
        with patch("socket.socket", side_effect=AssertionError("network")), \
             patch("turtle_quant.pit.parquet_financial_statements.ParquetFinancialStatementsReader.__init__",
                   side_effect=AssertionError("Reader")), \
             patch("turtle_quant.premise.general_fcf.evaluate_general_fcf", side_effect=AssertionError("premise")), \
             patch("turtle_quant.valuation.absolute.derive_attribution", side_effect=AssertionError("valuation")):
            self.assertEqual(pilot.build_supplement(ROOT), self.report)
        completed = subprocess.run([sys.executable, "-I", "-X", "utf8", str(ROOT / pilot.TOOL), "--check"],
                                   cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))

    def test_existing_output_or_render_path_is_not_overwritten(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            marker = output / "keep.txt"
            marker.write_bytes(b"keep")
            with patch.object(pilot, "build_supplement", return_value=self.report), \
                 patch("sys.argv", ["pilot", "--output-dir", str(output)]), self.assertRaises(FileExistsError):
                pilot.main()
            with self.assertRaises(FileExistsError):
                pilot.build_supplement(ROOT, render_dir=output)
            self.assertEqual(marker.read_bytes(), b"keep")

    def test_scope_tampering_comparative_value_or_version_fails(self):
        original = base._json
        for modify in (lambda scope: scope.update(unit="CNY_10000"),
                       lambda scope: scope["documents"][0].update(expected_closing_E_cny="645132659.65"),
                       lambda scope: scope["documents"][0].update(announcement_id="other")):
            def changed(raw):
                value = original(raw)
                if value.get("schema_version") == "attributable_equity_source_supplement_scope_v1":
                    modify(value)
                return value
            with patch.object(base, "_json", side_effect=changed), self.assertRaises(ValueError):
                pilot.build_supplement(ROOT)

    def test_real_source_bytes_and_page_counts_verified(self):
        for doc in self.report["source_documents"]:
            self.assertTrue(base.verified_bytes(ROOT, doc["path"], doc["sha256"]))
            self.assertEqual(doc["evidence_pages"], [93, 94, 95])
            self.assertEqual(doc["physical_page_count"], 209)
            self.assertIsNone(doc["diagnostic_available_at"])
            self.assertFalse(doc["pit_admitted"])
