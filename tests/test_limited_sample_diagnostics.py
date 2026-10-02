"""Single-sample evidence arithmetic must not silently become PIT or selection."""

from __future__ import annotations

import copy
from decimal import Decimal, localcontext, ROUND_DOWN
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.pilots import build_limited_diagnostics as pilot


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / pilot.DEFAULT_OUTPUT


class LimitedSampleDiagnosticTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reports = {
            sample: json.loads((OUTPUT / f"{sample}-diagnostic-only.json").read_bytes())
            for sample in pilot.SAMPLE_SECURITIES
        }

    def rebuild(self):
        try:
            return pilot.build_reports(ROOT)
        except (FileNotFoundError, ImportError) as exc:
            self.skipTest(f"optional local pilot capture/dependency absent: {exc}")

    def test_single_security_as_of_and_output_scope_are_frozen(self) -> None:
        for sample, report in self.reports.items():
            with self.subTest(sample=sample):
                self.assertEqual(report["security_id"], pilot.SAMPLE_SECURITIES[sample])
                self.assertEqual(report["as_of"], "2026-09-30")
                self.assertEqual(report["review_date"], "2026-10-02")
                self.assertTrue(report["output_scope"])
                self.assertEqual(report["manifest"]["rule_version"], "v1.3.2")
                self.assertEqual(report["manifest"]["rule_identity"]["sha256"],
                                 "db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812")

    def test_nonselection_flags_and_disclaimers_in_every_output(self) -> None:
        for sample, report in self.reports.items():
            with self.subTest(sample=sample):
                pilot.validate_report(report)
                self.assertTrue(report["diagnostic_only"])
                self.assertFalse(report["official_selection"])
                self.assertFalse(report["production_reader_ready"])
                self.assertFalse(report["real_pit_strategy_run"])
                rendered = pilot.render_markdown(report)
                for text in ("本报告不宣称", "时点假设", "官方 Top-N", "投资建议", "UNKNOWN"):
                    self.assertIn(text, rendered)
                self.assertEqual((OUTPUT / f"{sample}-diagnostic-only.md").read_bytes(),
                                 rendered.encode("utf-8"))

    def test_every_real_observation_is_distinct_from_unadmitted_pit_value(self) -> None:
        for report in self.reports.values():
            self.assertEqual(report["timing_assumptions"]["admitted_pit_observation_count"], 0)
            self.assertIsNone(report["timing_assumptions"]["available_at"])
            for item in report["source_observations"]:
                self.assertEqual(item["pit_status"], "UNKNOWN")
                self.assertIsNone(item["pit_value"])
                self.assertTrue(item["unknown_reason"])
                self.assertTrue(item["evidence_refs"])
            for gap in report["necessary_input_gaps"]:
                self.assertEqual(gap["status"], "UNKNOWN")
                self.assertIsNone(gap["value"])
                self.assertTrue(gap["missing_dependencies"])

    def test_catalogue_clock_does_not_become_available_at_even_when_nonmidnight(self) -> None:
        clocks = []
        for report in self.reports.values():
            for doc in report["source_documents"]:
                clocks.append(doc["catalogue_announcement_time_beijing"])
                self.assertIsNone(doc["diagnostic_available_at"])
                self.assertIsNone(doc["exact_available_at_utc"])
                self.assertEqual(doc["historical_availability_status"], "UNKNOWN")
                self.assertFalse(doc["pit_admitted"])
                self.assertTrue(doc["catalogue_source"]["sha256"])
        self.assertTrue(any("T00:00:00" not in clock for clock in clocks))
        self.assertTrue(any("T00:00:00" in clock for clock in clocks))

    def test_every_field_ref_binds_to_verified_physical_page(self) -> None:
        for report in self.reports.values():
            permitted = {
                f'pdf:sha256:{doc["sha256"]}:physical-page:{page}'
                for doc in report["source_documents"] for page in doc["evidence_pages"]
            }
            for item in report["source_observations"]:
                self.assertTrue(set(item["evidence_refs"]).issubset(permitted))
            for doc in report["source_documents"]:
                self.assertTrue(all(1 <= page <= doc["physical_page_count"]
                                    for page in doc["evidence_pages"]))
                self.assertIn(doc["announcement_id"], doc["url"])

    def test_endpoints_do_not_prove_daily_s_or_zero_treasury(self) -> None:
        report = self.reports["shares-000858"]
        observed = {item["field"]: item for item in report["source_observations"]}
        self.assertEqual(observed["issued_shares_opening"]["observed_value"], "3881608005")
        self.assertEqual(observed["issued_shares_closing"]["observed_value"], "3881608005")
        self.assertIsNone(observed["treasury_shares"]["observed_value"])
        self.assertEqual(observed["treasury_shares"]["source_state"], "BLANK_NOT_ZERO")
        analysis = report["observed_arithmetic_not_pit_rule_outputs"]
        self.assertEqual(analysis["endpoint_difference_shares"], "0")
        self.assertIsNone(analysis["daily_share_series"])
        self.assertIsNone(analysis["treasury_shares"])
        self.assertEqual(analysis["policy_execution"]["status"], "UNKNOWN")
        self.assertIsNone(analysis["policy_input"])

    def test_reported_buyback_not_applicable_is_not_a_verified_zero(self) -> None:
        items = self.reports["shares-000858"]["source_observations"]
        item = next(item for item in items if item["field"] == "reported_buyback_implementation")
        self.assertEqual(item["observed_value"], "NOT_APPLICABLE_REPORTED")
        self.assertIsNone(item["pit_value"])
        self.assertIn("非库存股零证明", item["label"])

    def test_first_execution_and_all_interval_differences_reconcile_exactly(self) -> None:
        report = self.reports["buybacks-600519"]
        analysis = report["observed_arithmetic_not_pit_rule_outputs"]
        self.assertEqual(analysis["plan_id"], "sh.600519:2024-09-21:capital-reduction")
        self.assertEqual(analysis["first_execution_day"], "2025-01-02")
        self.assertEqual(analysis["first_execution_amount_cny"], "299919221.00")
        interval_sum = sum((Decimal(item["difference_cny"]) for item in analysis["intervals"]), Decimal(0))
        self.assertEqual(interval_sum, Decimal("5700066745.95"))
        self.assertEqual(interval_sum + Decimal(analysis["first_execution_amount_cny"]),
                         Decimal(analysis["final_cumulative_amount_cny"]))
        self.assertEqual(len(analysis["intervals"]), 10)

    def test_interval_amounts_never_generate_daily_allocations_or_last_trade_date(self) -> None:
        analysis = self.reports["buybacks-600519"]["observed_arithmetic_not_pit_rule_outputs"]
        for item in analysis["intervals"]:
            self.assertEqual(item["daily_allocation_status"], "UNKNOWN")
            self.assertIsNone(item["executed_on"])
            self.assertIsNone(item["daily_amounts"])
        self.assertEqual(analysis["reported_completion_on"], "2025-08-29")
        self.assertIsNone(analysis["actual_last_execution_day"])
        self.assertIsNone(analysis["verified_cancellation_effective_on"])
        self.assertIn("不直接计入", analysis["first_amount_semantics"])

    def test_september_original_values_do_not_overwrite_august_amendment(self) -> None:
        analysis = self.reports["cashflow-000637"]["observed_arithmetic_not_pit_rule_outputs"]
        item = next(item for item in analysis["comparisons"] if item["field"] == "operating_net")
        self.assertEqual(item["original"], "42986260.08")
        self.assertEqual(item["amended"], "-79583416.97")
        self.assertEqual(item["september"], item["original"])
        self.assertEqual(item["amendment_delta"], "-122569677.05")
        self.assertEqual(len(analysis["comparisons"]), 12)
        self.assertIsNone(analysis["latest_visible_version"])

    def test_ocf_minus_capex_is_explicitly_not_attributable_fcf(self) -> None:
        analysis = self.reports["cashflow-000637"]["observed_arithmetic_not_pit_rule_outputs"]
        values = analysis["ocf_minus_capex_subtotals_not_fcf"]
        self.assertEqual([item["ocf_minus_capex_cny"] for item in values],
                         ["-19187052.76", "-141756729.81"])
        for item in values:
            self.assertEqual(item["fcf_status"], "UNKNOWN")
            self.assertIsNone(item["fcf_value"])
        self.assertIn("不是 FCF", analysis["subtotal_semantics"])

    def test_gross_profit_same_but_revenue_basis_and_margin_change(self) -> None:
        analysis = self.reports["financial-002570"]["observed_arithmetic_not_pit_rule_outputs"]
        versions = analysis["version_arithmetic"]
        self.assertEqual({item["gross_profit_cny"] for item in versions}, {"1151183585.35"})
        self.assertEqual(analysis["first_revenue_delta_cny"], "-145452723.30")
        self.assertEqual(analysis["first_cost_delta_cny"], "-145452723.30")
        self.assertEqual(analysis["gross_profit_difference_cny"], "0.00")
        self.assertNotEqual(versions[0]["gross_margin_pct"], versions[1]["gross_margin_pct"])
        self.assertTrue(all(item["sum_cny"] == "0.00" for item in analysis["reclassifications"]))

    def test_blank_precorrection_liability_stays_null(self) -> None:
        items = [item for item in self.reports["financial-002570"]["source_observations"]
                 if item["field"] == "other_noncurrent_liabilities"]
        self.assertEqual([item["observed_value"] for item in items], [None, None, "18000000.00"])
        self.assertTrue(all(item["source_state"] == "BLANK_NOT_ZERO" for item in items[:2]))
        self.assertTrue(all(item["pit_value"] is None for item in items))

    def test_special_assurance_does_not_close_year_scope_or_whole_audit_gap(self) -> None:
        analysis = self.reports["financial-002570"]["observed_arithmetic_not_pit_rule_outputs"]
        self.assertEqual(analysis["amended_whole_statement_audit_status"], "UNKNOWN")
        self.assertEqual(analysis["second_special_report_period"], "UNKNOWN_YEAR_SCOPE_CONFLICT")
        self.assertTrue(analysis["audit_evidence_refs"])
        self.assertIn("不阻止本报告原文对照", analysis["audit_warning"])

    def test_premise_receives_no_fake_dated_annuals_or_defaults_and_valuation_not_called(self) -> None:
        for sample in ("cashflow-000637", "financial-002570"):
            evaluation = self.reports[sample]["observed_arithmetic_not_pit_rule_outputs"]["premise_execution"]
            self.assertEqual(len(evaluation["hard_gates"]), 6)
            self.assertTrue(all(item["status"] == "UNKNOWN" for item in evaluation["hard_gates"]))
            self.assertIsNone(evaluation["quality_score"])
            self.assertEqual(evaluation["score_coverage"], "0")
            self.assertEqual(evaluation["admitted_inputs"]["annual_observations"], [])
            self.assertIsNone(evaluation["admitted_inputs"]["industry_profile"])
            self.assertIsNone(evaluation["admitted_inputs"]["cash"])
            self.assertEqual(evaluation["valuation_execution"], "NOT_EXECUTED_UNKNOWN_DEPENDENCIES")

    def test_usage_scope_does_not_claim_public_availability_grants_unlimited_licence(self) -> None:
        for report in self.reports.values():
            self.assertTrue(report["usage_scope"]["source_terms_compliance_required"])
            self.assertFalse(report["usage_scope"]["bulk_use_or_redistribution_permission_verified"])
            self.assertIn("公开可获取不等于任意授权", report["usage_scope"]["note"])

    def test_content_hash_covers_scope_unknowns_values_and_code_but_not_itself(self) -> None:
        report = self.reports["cashflow-000637"]
        self.assertEqual(pilot.logical_content_hash(report), report["logical_content_hash"])
        for path, replacement in (
            (("as_of",), "2026-09-29"),
            (("source_observations", 0, "observed_value"), "0"),
            (("timing_assumptions", "policy"), "NEXT_DAY_ASSUMED"),
            (("manifest", "code_sources", 0, "sha256"), "0" * 64),
        ):
            changed = copy.deepcopy(report)
            parent = changed
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = replacement
            self.assertNotEqual(pilot.logical_content_hash(changed), report["logical_content_hash"])
        changed = {**report, "logical_content_hash": "0" * 64}
        self.assertEqual(pilot.logical_content_hash(changed), report["logical_content_hash"])

    def test_forbidden_output_keys_are_rejected_even_with_recomputed_hash(self) -> None:
        for key in ("ranking", "rank", "top_n", "target_weights", "orders", "holdings",
                    "nav", "composite_score", "candidate", "tier"):
            changed = copy.deepcopy(self.reports["shares-000858"])
            changed["observed_arithmetic_not_pit_rule_outputs"][key] = []
            changed["logical_content_hash"] = pilot.logical_content_hash(changed)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "forbidden"):
                pilot.validate_report(changed)

    def test_numeric_unknown_or_unverified_pit_injection_is_rejected(self) -> None:
        for section, field in (("source_observations", "pit_value"),
                               ("necessary_input_gaps", "value")):
            changed = copy.deepcopy(self.reports["shares-000858"])
            changed[section][0][field] = "0"
            changed["logical_content_hash"] = pilot.logical_content_hash(changed)
            with self.subTest(section=section), self.assertRaises(ValueError):
                pilot.validate_report(changed)

    def test_authority_or_report_security_drift_is_rejected(self) -> None:
        for field, value in (("official_selection", True), ("diagnostic_only", False),
                             ("production_reader_ready", True), ("real_pit_strategy_run", True),
                             ("security_id", "sz.000637")):
            changed = {**self.reports["shares-000858"], field: value}
            changed["logical_content_hash"] = pilot.logical_content_hash(changed)
            with self.subTest(field=field), self.assertRaises(ValueError):
                pilot.validate_report(changed)

    def test_duplicate_json_keys_and_nonfinite_numbers_hard_fail(self) -> None:
        for raw in (b'{"as_of":"a","as_of":"b"}', b'{"value":NaN}', b'{"value":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                pilot._json(raw)

    def test_missing_source_hash_drift_and_workspace_escape_hard_fail(self) -> None:
        with TemporaryDirectory() as task_dir:
            root = Path(task_dir)
            source = root / "evidence.json"
            source.write_bytes(b"{}")
            digest = hashlib.sha256(b"{}").hexdigest()
            self.assertEqual(pilot.verified_bytes(root, "evidence.json", digest), b"{}")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                pilot.verified_bytes(root, "evidence.json", "0" * 64)
            with self.assertRaises(FileNotFoundError):
                pilot.verified_bytes(root, "missing.json", digest)
            with self.assertRaisesRegex(ValueError, "escapes workspace"):
                pilot.verified_bytes(root, "../outside.json", digest)

    def test_field_page_not_in_verified_document_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "page not bound"):
            pilot._ref({"sha256": "0" * 64, "evidence_pages": [1]}, 2)

    def test_write_refuses_existing_directory_and_preserves_existing_bytes(self) -> None:
        with TemporaryDirectory() as task_dir:
            output = Path(task_dir) / "existing"
            output.mkdir()
            marker = output / "existing.txt"
            marker.write_bytes(b"unchanged")
            with self.assertRaises(FileExistsError):
                pilot.write_reports(list(self.reports.values()), output)
            self.assertEqual(marker.read_bytes(), b"unchanged")

    def test_two_generations_have_identical_json_markdown_and_logical_hashes(self) -> None:
        first, second = self.rebuild(), self.rebuild()
        self.assertEqual(first, second)
        with TemporaryDirectory() as task_dir:
            left, right = Path(task_dir) / "first", Path(task_dir) / "second"
            pilot.write_reports(first, left)
            pilot.write_reports(second, right)
            self.assertEqual({path.name: path.read_bytes() for path in left.iterdir()},
                             {path.name: path.read_bytes() for path in right.iterdir()})
        self.assertEqual({item["sample_id"]: item for item in first}, self.reports)

    def test_ambient_decimal_precision_cannot_change_arithmetic(self) -> None:
        expected = self.rebuild()
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_DOWN
            actual = self.rebuild()
            self.assertEqual(context.prec, 6)
        self.assertEqual(expected, actual)

    def test_source_scope_refuses_cross_security_and_new_timing_policy(self) -> None:
        original_parser = pilot._json

        def change(raw):
            value = original_parser(raw)
            if value.get("schema_version") == "limited_sample_diagnostic_scope_v1":
                value["timing_policy"] = "ASSUME_NEXT_TRADING_DAY"
            return value

        with patch.object(pilot, "_json", side_effect=change), self.assertRaisesRegex(ValueError, "timing policy"):
            pilot.build_reports(ROOT)

        def change_issuer(raw):
            value = original_parser(raw)
            if value.get("security_id") == "sz.000858":
                value["security_id"] = "sz.000637"
            return value

        with patch.object(pilot, "_json", side_effect=change_issuer), self.assertRaisesRegex(ValueError, "cross-security"):
            pilot.build_reports(ROOT)

    def test_production_readers_and_valuation_are_never_called(self) -> None:
        with patch("turtle_quant.pit.parquet_strategy_inputs.ParquetSharesReader.__init__",
                   side_effect=AssertionError("production shares called")), \
             patch("turtle_quant.pit.parquet_buybacks.ParquetBuybackReader.__init__",
                   side_effect=AssertionError("production buybacks called")), \
             patch("turtle_quant.pit.parquet_financial_statements.ParquetFinancialStatementsReader.__init__",
                   side_effect=AssertionError("production finance called")), \
             patch("turtle_quant.valuation.absolute.derive_attribution",
                   side_effect=AssertionError("dummy attribution called")), \
             patch("turtle_quant.valuation.absolute.calculate_absolute_valuation",
                   side_effect=AssertionError("dummy valuation called")):
            self.assertEqual(len(self.rebuild()), 4)

    def test_all_local_pdf_and_catalogue_bytes_are_verified_not_just_manifest_claims(self) -> None:
        reports = self.rebuild()
        self.assertEqual(sum(len(item["source_documents"]) for item in reports), 24)
        self.assertEqual(sum(len(item["source_observations"]) for item in reports), 81)
        for report in reports:
            for source in report["source_documents"] + report["manifest"]["catalogue_sources"]:
                raw = pilot.verified_bytes(ROOT, source["path"], source["sha256"])
                self.assertTrue(raw)
