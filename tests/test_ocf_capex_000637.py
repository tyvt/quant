"""Source cashflow/equity binding cannot turn incomplete evidence into PIT FCF."""

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
from scripts.pilots import verify_attributable_equity_000637 as equity
from scripts.pilots import verify_ocf_capex_000637 as pilot

ROOT = Path(__file__).resolve().parents[1]
HEADER = "茂名石化实华股份有限公司2025 年年度报告全文\n5、合并现金流量表\n单位：元"
CONTINUED = "茂名石化实华股份有限公司2025 年年度报告全文\n三、筹资活动产生的现金流量：\n6、母公司现金流量表"


def word(text, x, y, width=60):
    return (x, y, x + width, y + 9, text, 0, 0, 0)


class OcfCapexSourceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = pilot.build_supplement(ROOT)

    def setUp(self):
        self.words = [word("5、合并现金流量表", 56, 100, 100),
                      word("2025", 274, 160, 20), word("年度", 296, 160, 18),
                      word("2024", 434, 160, 20), word("年度", 456, 160, 18),
                      word("一、经营活动产生的现金流量：", 56, 185, 135),
                      word("经营活动现金流入小计", 56, 300, 120),
                      word("3,527,194,370.04", 300, 300), word("4,134,489,117.69", 460, 300),
                      word("经营活动现金流出小计", 56, 450, 120),
                      word("3,484,208,109.96", 300, 450), word("4,125,411,208.51", 460, 450),
                      word(pilot.OCF_LABEL, 56, 470, 135),
                      word("42,986,260.08", 300, 470), word("9,077,909.18", 460, 470),
                      word("二、投资活动产生的现金流量：", 56, 490, 135),
                      word(pilot.CAPEX_PARTS[0], 65, 610, 135),
                      word(pilot.CAPEX_PARTS[1], 56, 622, 72),
                      word("62,173,312.84", 300, 616), word("79,764,639.75", 460, 616),
                      word("投资活动现金流出小计", 56, 690, 120),
                      word("62,173,312.84", 300, 690), word("79,764,639.75", 460, 690),
                      word("投资活动产生的现金流量净额", 56, 710, 135)]
        # A legitimate repeated heading inside the later mother-company table.
        self.continuation = [word("三、筹资活动产生的现金流量：", 56, 74, 135),
                             word("6、母公司现金流量表", 56, 340, 100),
                             word("三、筹资活动产生的现金流量：", 56, 740, 135)]

    def extract(self, words=None, text=HEADER, continuation=None, continued=CONTINUED):
        return pilot.extract_cashflow_bridge(text, self.words if words is None else words, continued,
                                             self.continuation if continuation is None else continuation)

    def inputs(self):
        bundle = copy.deepcopy(self.report["version_bundles"][0])
        return [bundle[key] for key in ("OCF", "Capex", "existing_E", "existing_N")]

    def test_real_two_versions_have_exact_current_and_comparative_cashflows(self):
        original, amended = self.report["version_bundles"]
        self.assertEqual(original["OCF"]["observed_value"], "42986260.08")
        self.assertEqual(amended["OCF"]["observed_value"], "-79583416.97")
        self.assertEqual(original["OCF"]["prior_comparative_not_target_value"], "9077909.18")
        self.assertEqual(amended["OCF"]["prior_comparative_not_target_value"], "-185115131.48")
        for bundle in (original, amended):
            self.assertEqual(bundle["Capex"]["observed_value"], "62173312.84")
            self.assertEqual(bundle["Capex"]["prior_comparative_not_target_value"], "79764639.75")

    def test_geometry_not_word_order_selects_two_annual_columns(self):
        parsed = self.extract()
        self.assertEqual(parsed, self.extract(words=list(reversed(self.words)),
                                              continuation=list(reversed(self.continuation))))
        self.assertEqual(parsed["capex_cash_paid"]["current_amount_cny"], "62173312.84")

    def test_capex_uses_payment_row_not_identical_investment_total(self):
        words = [word("1.00", item[0], item[1]) if item[1] == 690 and item[0] >= 300 else item
                 for item in self.words]
        self.assertEqual(self.extract(words)["capex_cash_paid"]["current_amount_cny"], "62173312.84")

    def test_disposal_receipts_do_not_reduce_gross_capex(self):
        words = self.words + [word("处置固定资产、无形资产和其他长", 65, 550, 135),
                              word("期资产收回的现金净额", 56, 562, 100),
                              word("570,875.00", 300, 556), word("4,421,310.00", 460, 556)]
        self.assertEqual(self.extract(words)["capex_cash_paid"]["current_amount_cny"], "62173312.84")

    def test_missing_current_cell_is_not_comparative_or_zero(self):
        for field, y in (("operating_cash_flow", 470), ("capex_cash_paid", 616)):
            words = [item for item in self.words if not (item[0] == 300 and item[1] == y)]
            row = self.extract(words)[field]
            self.assertIsNone(row["current_amount_cny"])
            self.assertEqual(row["current_state"], "UNKNOWN")
            self.assertIsNotNone(row["prior_comparative_amount_cny"])

    def test_dash_capex_is_unknown_but_explicit_zero_is_known(self):
        for raw, expected in (("—", None), ("0.00", "0.00")):
            words = [word(raw, 300, 616) if item[0] == 300 and item[1] == 616 else item for item in self.words]
            self.assertEqual(self.extract(words)["capex_cash_paid"]["current_amount_cny"], expected)

    def test_split_label_must_be_complete_unique_and_adjacent(self):
        for changed in ([item for item in self.words if item[4] != pilot.CAPEX_PARTS[1]],
                        self.words + [word(pilot.CAPEX_PARTS[1], 56, 623, 72)],
                        [word(pilot.CAPEX_PARTS[1], 56, 640, 72) if item[4] == pilot.CAPEX_PARTS[1] else item
                         for item in self.words]):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.extract(changed)

    def test_duplicate_currency_and_unparseable_amount_fail(self):
        with self.assertRaisesRegex(ValueError, "ambiguous cashflow"):
            self.extract(self.words + [word("1.00", 310, 470)])
        words = [word("NaN", 300, 616) if item[0] == 300 and item[1] == 616 else item for item in self.words]
        with self.assertRaisesRegex(ValueError, "unparseable"):
            self.extract(words)

    def test_annual_headers_cannot_be_reversed_missing_or_detached(self):
        cases = [[word("2024" if item[4] == "2025" else "2025", item[0], item[1], 20)
                  if item[4] in ("2025", "2024") else item for item in self.words],
                 [item for item in self.words if item[4] != "2025"],
                 [word("年度", 296, 170, 18) if item[4] == "年度" and item[0] == 296 else item
                  for item in self.words]]
        for words in cases:
            with self.subTest(words=words), self.assertRaises(ValueError):
                self.extract(words)

    def test_issuer_period_unit_and_parent_scope_drift_fail(self):
        for old, new in (("茂名石化实华股份有限公司", "另一家公司"), ("2025 年", "2024 年"),
                         ("单位：元", "单位：万元"), ("合并现金流量表", "母公司现金流量表")):
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.extract(text=HEADER.replace(old, new))
        with self.assertRaises(ValueError):
            self.extract(continued=CONTINUED.replace("2025 年", "2024 年"))

    def test_section_boundary_cannot_place_capex_in_operating_cashflow(self):
        words = [word("二、投资活动产生的现金流量：", 56, 650, 135)
                 if item[4] == "二、投资活动产生的现金流量：" else item for item in self.words]
        with self.assertRaisesRegex(ValueError, "section"):
            self.extract(words)

    def test_continuation_accepts_parent_heading_repeat_only_after_boundary(self):
        self.assertTrue(self.extract()["parent_cashflow_table_starts_on_next_page"])
        for words in ([item for item in self.continuation if item[1] != 74],
                      self.continuation + [word("三、筹资活动产生的现金流量：", 56, 90, 135)],
                      [word("6、母公司现金流量表", 56, 60, 100) if item[4] == "6、母公司现金流量表" else item
                       for item in self.continuation]):
            with self.subTest(words=words), self.assertRaises(ValueError):
                self.extract(continuation=words)

    def test_ocf_subtotals_reconcile_both_columns_and_wrong_amount_fails(self):
        for check in self.extract()["ocf_subtotal_corroboration"].values():
            self.assertEqual(check["status"], "RECONCILED")
            self.assertEqual(Decimal(check["difference_cny"]), 0)
        words = [word("42,986,260.09", 300, 470) if item[0] == 300 and item[1] == 470 else item
                 for item in self.words]
        with self.assertRaisesRegex(ValueError, "inflow minus outflow"):
            self.extract(words)

    def test_negative_ocf_and_ordinary_arithmetic_are_preserved(self):
        expected = ("-16158353.92113239932027895383", "-119380263.3277545425210896909")
        for bundle, value in zip(self.report["version_bundles"], expected):
            result = bundle["source_arithmetic_not_pit"]
            self.assertEqual(result["FCF_ordinary_source_arithmetic_cny"], value)
            self.assertEqual(result["alpha_observed"], "0.8421488241705548591131801230")
            self.assertEqual(result["status"], "SOURCE_ARITHMETIC_ONLY_NOT_PIT")

    def test_negative_capex_payment_cannot_be_abs_or_zero_filled(self):
        inputs = self.inputs()
        inputs[1]["observed_value"] = "-1.00"
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            pilot.calculate_source_ordinary(*inputs)
        words = [word("-1.00", 300, 616) if item[0] == 300 and item[1] == 616 else item for item in self.words]
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            self.extract(words)

    def test_each_cashflow_equity_join_key_mismatch_fails_even_for_equal_values(self):
        for field_index in (0, 1):
            for key in equity.JOIN_KEYS:
                inputs = self.inputs()
                inputs[field_index][key] = "different"
                with self.subTest(field=field_index, key=key), self.assertRaisesRegex(ValueError, "identity mismatch"):
                    pilot.calculate_source_ordinary(*inputs)

    def test_missing_cashflow_identity_or_partial_annual_period_fails(self):
        for key, value in (("document_sha256", None), ("period_start", "2025-07-01"), ("field", "investing_outflow")):
            inputs = self.inputs()
            inputs[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.calculate_source_ordinary(*inputs)

    def test_each_missing_ordinary_dependency_stays_unknown_not_zero(self):
        for index in range(4):
            inputs = self.inputs()
            inputs[index]["observed_value"] = None
            result = pilot.calculate_source_ordinary(*inputs)
            self.assertIsNone(result["FCF_ordinary_source_arithmetic_cny"])
            self.assertEqual(result["status"], "UNKNOWN")

    def test_nonfinite_or_boolean_cashflow_not_evidence(self):
        for index in (0, 1):
            for value in ("NaN", "Infinity", True):
                inputs = self.inputs()
                inputs[index]["observed_value"] = value
                with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                    pilot.calculate_source_ordinary(*inputs)

    def test_arithmetic_does_not_depend_on_ambient_decimal_context(self):
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_DOWN
            self.assertEqual(pilot.calculate_source_ordinary(*self.inputs()),
                             self.report["version_bundles"][0]["source_arithmetic_not_pit"])

    def test_lease_unknown_does_not_block_ordinary_or_unlock_conservative_pit(self):
        for key in (*pilot.PIT_FIELDS, "diagnostic_available_at"):
            self.assertIsNone(self.report[key])
        for bundle in self.report["version_bundles"]:
            result = bundle["source_arithmetic_not_pit"]
            self.assertIsNotNone(result["FCF_ordinary_source_arithmetic_cny"])
            for key in ("Lease_cash_not_already_deducted", "FCF_conservative", "FCF_ordinary_pit"):
                self.assertIsNone(result[key])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)

    def test_authority_PIT_or_lease_zero_tampering_fails_after_rehash(self):
        for key, value in (("official_selection", True), ("FCF_ordinary_pit", "1.00"),
                           ("Lease_cash_not_already_deducted", "0.00"), ("diagnostic_available_at", "2026-04-30")):
            altered = copy.deepcopy(self.report)
            altered[key] = value
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.validate_supplement(altered)

    def test_output_arithmetic_or_pdf_page_tampering_fails_after_rehash(self):
        for change in (lambda r: r["version_bundles"][0]["source_arithmetic_not_pit"].update(FCF_ordinary_source_arithmetic_cny="0"),
                       lambda r: r["version_bundles"][0]["Capex"].update(evidence_refs=["physical-page:102"]),
                       lambda r: r["version_bundles"][0]["extraction_checks"]["operating_cash_flow"].update(current_amount_cny="1")):
            altered = copy.deepcopy(self.report)
            change(altered)
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.assertRaises(ValueError):
                pilot.validate_supplement(altered)

    def test_nested_forbidden_ranking_or_FCF_window_output_fails(self):
        for key in ("ranking", "orders", "F1", "nav"):
            altered = copy.deepcopy(self.report)
            altered["version_bundles"][0][key] = []
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "forbidden"):
                pilot.validate_supplement(altered)

    def test_source_pdf_identity_and_parent_equity_reports_are_unchanged(self):
        for key in ("parent_report", "equity_supplement", "minority_supplement"):
            ref = self.report["manifest"][key]
            raw = base.verified_bytes(ROOT, ref["path"], ref["sha256"])
            self.assertEqual(base.logical_content_hash(base._json(raw)), ref["logical_content_hash"])
        for doc in self.report["source_documents"]:
            self.assertTrue(base.verified_bytes(ROOT, doc["path"], doc["sha256"]))
            self.assertEqual(doc["physical_page_count"], 209)
            self.assertEqual(doc["cashflow_pages"], [101, 102])
        self.assertEqual(self.report["gap_resolution"]["source_before"], "OCF_CAPEX_ALREADY_RECORDED_IN_PARENT")

    def test_two_rebuilds_json_reload_and_frozen_outputs_match(self):
        report = pilot.build_supplement(ROOT)
        self.assertEqual(report, pilot.build_supplement(ROOT))
        output = ROOT / pilot.DEFAULT_OUTPUT
        self.assertEqual((output / "diagnostic-only.json").read_bytes(), base.canonical_bytes(report) + b"\n")
        self.assertEqual((output / "diagnostic-only.md").read_bytes(), pilot.render_markdown(report).encode("utf-8"))
        self.assertEqual(pilot.render_markdown(report), pilot.render_markdown(base._json(base.canonical_bytes(report))))

    def test_offline_check_never_calls_readers_or_real_rules(self):
        with patch("socket.socket", side_effect=AssertionError("network")), \
             patch("turtle_quant.pit.parquet_financial_statements.ParquetFinancialStatementsReader.__init__",
                   side_effect=AssertionError("Reader")), \
             patch("turtle_quant.premise.general_fcf.evaluate_general_fcf", side_effect=AssertionError("premise")), \
             patch("turtle_quant.valuation.absolute.derive_attribution", side_effect=AssertionError("valuation")):
            self.assertEqual(pilot.build_supplement(ROOT), self.report)
        completed = subprocess.run([sys.executable, "-I", "-X", "utf8", str(ROOT / pilot.TOOL), "--check"],
                                   cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))

    def test_existing_output_or_render_directory_is_never_overwritten(self):
        with TemporaryDirectory() as folder:
            with patch.object(pilot, "build_supplement", return_value=self.report), \
                 patch("sys.argv", ["pilot", "--output-dir", folder]), self.assertRaises(FileExistsError):
                pilot.main()
            with self.assertRaises(FileExistsError):
                pilot.build_supplement(ROOT, render_dir=Path(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_scope_version_pages_and_expected_comparative_amount_tampering_fail(self):
        original = base._json
        for modify in (lambda s: s.update(unit="CNY_10000"),
                       lambda s: s["documents"][0].update(announcement_id="other"),
                       lambda s: s["documents"][0].update(field_page=102),
                       lambda s: s["documents"][0].update(expected_operating_cash_flow_cny="9077909.18"),
                       lambda s: s["documents"][0].update(expected_comparative_capex_cash_paid_cny="62173312.84")):
            def changed(raw):
                value = original(raw)
                if value.get("schema_version") == "ocf_capex_source_supplement_scope_v1":
                    modify(value)
                return value
            with patch.object(base, "_json", side_effect=changed), self.assertRaises(ValueError):
                pilot.build_supplement(ROOT)
