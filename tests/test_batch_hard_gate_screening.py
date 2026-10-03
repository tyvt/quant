"""Synthetic-only batch regressions; no production Reader or network access."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_batch_screening import markdown, write_output
from scripts.screening.batch_runner import BatchRunner, ROOT, implementation_identity
from scripts.screening.contracts import (
    BatchRequest, DATA_KIND, SCHEMA, canonical_bytes, content_hash, load_request, plain,
)
from scripts.screening.demo import demo_request, fixture
from scripts.screening.hard_gates import GATE_ORDER
from turtle_quant.premise.general_fcf import evaluate_general_fcf
from turtle_quant.strategy.selection import evaluate_universe_security


def request(*records, ids=None):
    selected = ids if ids is not None else tuple(item.security_id for item in records)
    return BatchRequest(SCHEMA, DATA_KIND, date(2026, 5, 1), selected, records)


def financial_change(record, **changes):
    return replace(record, financial=replace(record.financial, **changes))


class BatchScreeningTests(unittest.TestCase):
    def setUp(self):
        self.record = fixture("sh.600001")

    def row(self, record=None):
        return BatchRunner().run(request(record or self.record)).report["rows"][0]

    def test_demo_three_queues_and_unlisted_input_kept(self):
        report = BatchRunner().run(demo_request()).report
        self.assertEqual(report["counts"], {"PASSED": 1, "STOPPED": 2, "NEEDS_EVIDENCE": 2})
        self.assertEqual(len(report["rows"]), 5)
        self.assertEqual(report["queues"]["NEEDS_EVIDENCE"], ["sh.600003", "sh.600005"])

    def test_pass_is_analysis_queue_not_official_candidate(self):
        row = self.row()
        self.assertEqual(row["premise_status"], "PASS")
        self.assertTrue(row["detailed_analysis_eligible"])
        self.assertFalse(row["known_failure"])
        report = BatchRunner().run(request(self.record)).report
        self.assertTrue(report["diagnostic_only"])
        self.assertFalse(report["official_selection"])
        self.assertFalse(report["real_pit_run_authorized"])
        self.assertEqual(report["whole_month_eligibility"], "NOT_EVALUATED")

    def test_batch_size_not_population_limit(self):
        records = tuple(fixture(f"sh.{600000 + index:06d}") for index in range(205))
        report = BatchRunner().run(request(*records), batch_size=7).report
        self.assertEqual(report["counts"]["PASSED"], 205)
        self.assertEqual(len(report["rows"]), 205)

    def test_duplicate_requested_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate requested"):
            request(self.record, ids=(self.record.security_id,) * 2)

    def test_duplicate_input_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate fixture"):
            request(self.record, self.record, ids=(self.record.security_id,))

    def test_extra_input_security_rejected(self):
        with self.assertRaisesRegex(ValueError, "bound"):
            request(self.record, ids=("sh.600002",))

    def test_canonical_security_id_required(self):
        with self.assertRaises(ValueError):
            request(ids=("600001",))

    def test_issuer_binding_rejected(self):
        other = replace(self.record, security_id="sh.600002")
        with self.assertRaisesRegex(ValueError, "binding mismatch"):
            request(other)

    def test_basic_as_of_binding_rejected(self):
        other = replace(self.record, basic=replace(self.record.basic, as_of=date(2026, 5, 2),
                                                  expected_liquidity_dates=tuple(
                                                      day + timedelta(days=1) for day in
                                                      self.record.basic.expected_liquidity_dates)))
        with self.assertRaisesRegex(ValueError, "binding mismatch"):
            request(other)

    def test_financial_as_of_binding_rejected(self):
        with self.assertRaisesRegex(ValueError, "financial as_of"):
            request(financial_change(self.record, as_of=date(2026, 5, 2)))

    def test_share_issuer_and_as_of_binding_rejected(self):
        for changes in ({"security_id": "sz.000001"}, {"as_of": date(2026, 5, 2)}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "share evidence"):
                basic = replace(self.record.basic, share_capital_evidence=replace(
                    self.record.basic.share_capital_evidence, **changes))
                request(replace(self.record, basic=basic))

    def test_profile_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "profile mismatch"):
            request(financial_change(self.record, industry_profile="BANK"))

    def test_conflicting_versions_rejected_even_when_basic_would_stop(self):
        rows = self.record.financial.annual_observations
        bad = rows + (replace(rows[0], operating_cash_flow=Decimal("21")),)
        other = financial_change(self.record, annual_observations=bad)
        other = replace(other, basic=replace(other.basic, market_value=Decimal("1")))
        with self.assertRaisesRegex(ValueError, "conflicting annual"):
            request(other)

    def test_known_basic_failure_skips_financial_engine(self):
        record = replace(self.record, basic=replace(self.record.basic, market_value=Decimal("1")))
        with patch("scripts.screening.batch_runner.hard_gates", side_effect=AssertionError("must skip")):
            row = self.row(record)
        self.assertEqual(row["work_queue"], "STOPPED")
        self.assertEqual(row["basic"]["status"], "REJECTED")
        self.assertEqual(row["enterprise_stage"], "NOT_RUN")
        self.assertEqual(row["enterprise_gates"], [])

    def test_basic_unknown_dominates_visible_low_market_value(self):
        record = replace(self.record, basic=replace(self.record.basic,
                         market_value=Decimal("1"), eligible_security_status=None))
        row = self.row(record)
        self.assertEqual(row["basic"]["status"], "NEEDS_REVIEW")
        self.assertEqual(row["work_queue"], "NEEDS_EVIDENCE")
        self.assertFalse(row["detailed_analysis_eligible"])

    def test_unknown_and_financial_failure_retained_together(self):
        rows = tuple(replace(item, lease_cash_not_already_deducted=None)
                     for item in self.record.financial.annual_observations)
        row = self.row(financial_change(self.record, annual_observations=rows,
                                       latest_audit_unmodified=False))
        self.assertEqual(row["work_queue"], "NEEDS_EVIDENCE")
        self.assertEqual(row["premise_status"], "NEEDS_REVIEW")
        self.assertIn("premise.statement_integrity", row["known_failed_gate_ids"])
        self.assertIn("premise.fcf_consistency", row["unknown_gate_ids"])
        self.assertTrue(row["stop_additional_deep_work"])
        self.assertEqual(len(row["enterprise_gates"]), 6)

    def test_known_financial_failure_stops(self):
        row = self.row(financial_change(self.record, latest_audit_unmodified=False))
        self.assertEqual(row["work_queue"], "STOPPED")
        self.assertEqual(row["premise_status"], "FAIL")
        self.assertTrue(row["known_failure"])

    def test_not_supported_is_not_financial_fail(self):
        record = replace(self.record, basic=replace(self.record.basic, industry_profile="BANK"),
                         financial=None)
        row = self.row(record)
        self.assertEqual(row["work_queue"], "STOPPED")
        self.assertEqual(row["basic"]["status"], "NOT_SUPPORTED")
        self.assertTrue(row["out_of_scope"])
        self.assertFalse(row["known_failure"])

    def test_multiclass_and_treasury_share_unknowns(self):
        for changes in ({"ordinary_share_classes": ("A", "B")}, {"treasury_shares": 1},
                        {"treasury_shares": None}):
            with self.subTest(changes=changes):
                basic = replace(self.record.basic, share_capital_evidence=replace(
                    self.record.basic.share_capital_evidence, **changes))
                row = self.row(replace(self.record, basic=basic))
                self.assertEqual(row["work_queue"], "NEEDS_EVIDENCE")
                self.assertIn("shares_unknown", row["basic"]["reasons"])

    def test_unsupported_does_not_mask_ambiguous_shares(self):
        share = replace(self.record.basic.share_capital_evidence, ordinary_share_classes=("A", "B"))
        basic = replace(self.record.basic, industry_profile="BANK", share_capital_evidence=share)
        row = self.row(replace(self.record, basic=basic, financial=None))
        self.assertEqual(row["work_queue"], "NEEDS_EVIDENCE")
        self.assertEqual(row["basic"]["status"], "NEEDS_REVIEW")

    def test_future_share_evidence_not_usable(self):
        share = replace(self.record.basic.share_capital_evidence, available_on=date(2026, 5, 2))
        basic = replace(self.record.basic, share_capital_evidence=share)
        self.assertEqual(self.row(replace(self.record, basic=basic))["work_queue"], "NEEDS_EVIDENCE")

    def test_exact_frozen_basic_thresholds(self):
        days = tuple(replace(item, amount=Decimal("20000000"), tradable=(index >= 10))
                     for index, item in enumerate(self.record.basic.liquidity_days))
        basic = replace(self.record.basic, market_value=Decimal("5000000000"),
                        listing_trading_days=504, liquidity_days=days)
        self.assertEqual(self.row(replace(self.record, basic=basic))["work_queue"], "PASSED")
        for changes in ({"market_value": Decimal("4999999999")}, {"listing_trading_days": 503},
                        {"liquidity_days": (replace(days[10], tradable=False),) + days[:10] + days[11:]}):
            with self.subTest(changes=changes):
                row = self.row(replace(self.record, basic=replace(basic, **changes)))
                self.assertEqual(row["basic"]["status"], "REJECTED")

    def test_missing_liquidity_day_does_not_use_remaining_days(self):
        basic = replace(self.record.basic, liquidity_days=self.record.basic.liquidity_days[:-1])
        row = self.row(replace(self.record, basic=basic))
        self.assertEqual(row["work_queue"], "NEEDS_EVIDENCE")
        self.assertIn("liquidity_window_incomplete", row["basic"]["reasons"])

    def test_liquidity_null_not_zero(self):
        for changes in ({"amount": None}, {"tradable": None}, {"evidence_ref": None}):
            with self.subTest(changes=changes):
                days = list(self.record.basic.liquidity_days)
                days[0] = replace(days[0], **changes)
                row = self.row(replace(self.record, basic=replace(self.record.basic, liquidity_days=tuple(days))))
                self.assertEqual(row["work_queue"], "NEEDS_EVIDENCE")

    def test_missing_financials_are_six_unknowns(self):
        row = self.row(replace(self.record, financial=None))
        self.assertEqual(row["work_queue"], "NEEDS_EVIDENCE")
        self.assertEqual([item["status"] for item in row["enterprise_gates"]], ["UNKNOWN"] * 6)

    def test_sixth_equity_year_required_no_substitution(self):
        financial = self.record.financial
        older = replace(financial.annual_observations[0], fiscal_year=2019, available_at=date(2020, 4, 30))
        rows = (older,) + financial.annual_observations[1:]
        row = self.row(financial_change(self.record, annual_observations=rows))
        self.assertIn("premise.roe_5y", row["unknown_gate_ids"])

    def test_future_financial_version_does_not_fill_window(self):
        rows = list(self.record.financial.annual_observations)
        rows[-1] = replace(rows[-1], available_at=date(2026, 5, 2))
        row = self.row(financial_change(self.record, annual_observations=tuple(rows)))
        self.assertIn("premise.fcf_consistency", row["unknown_gate_ids"])

    def test_untraceable_financials_cannot_pass(self):
        rows = tuple(replace(item, evidence_refs=()) for item in self.record.financial.annual_observations)
        self.assertEqual(self.row(financial_change(self.record, annual_observations=rows))["work_queue"],
                         "NEEDS_EVIDENCE")

    def test_exact_existing_engine_results_retained(self):
        row = self.row()
        existing = evaluate_general_fcf(self.record.financial)
        self.assertEqual(row["enterprise_gates"], [plain(existing.gate(key)) for key in GATE_ORDER])
        basic = plain(evaluate_universe_security(self.record.basic))
        for key in ("status", "reasons", "valid_trading_amount_days", "median_trading_amount"):
            self.assertEqual(row["basic"][key], basic[key])

    def test_no_score_ranking_or_trading_output(self):
        forbidden = {"quality_score", "rank", "ranked_candidates", "target_weights", "orders",
                     "positions", "nav", "gg", "coverage6", "annual_fcf_newest_to_oldest"}
        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(BatchRunner().run(demo_request()).report)

    def test_input_order_chunk_size_and_cache_do_not_change_identity(self):
        original = demo_request()
        reversed_input = replace(original, security_ids=tuple(reversed(original.security_ids)),
                                 inputs=tuple(reversed(original.inputs)))
        runner = BatchRunner()
        cold = runner.run(original, batch_size=2)
        warm = runner.run(reversed_input, batch_size=1)
        self.assertEqual(canonical_bytes(cold.report), canonical_bytes(warm.report))
        self.assertEqual(warm.cache_hits, 5)
        self.assertEqual(warm.evaluated_securities, 0)

    def test_annual_order_does_not_change_identity(self):
        runner = BatchRunner()
        first = runner.run(request(self.record)).report
        reversed_record = financial_change(self.record, annual_observations=tuple(
            reversed(self.record.financial.annual_observations)))
        self.assertEqual(first, runner.run(request(reversed_record)).report)

    def test_one_new_fact_invalidates_only_affected_security(self):
        runner = BatchRunner()
        first = runner.run(demo_request())
        records = list(demo_request().inputs)
        records[0] = financial_change(records[0], latest_audit_unmodified=False)
        second = runner.run(replace(demo_request(), inputs=tuple(records)))
        self.assertEqual(second.cache_hits, 4)
        self.assertEqual(second.evaluated_securities, 1)
        self.assertNotEqual(first.report["logical_content_hash"], second.report["logical_content_hash"])

    def test_shared_unknowns_grouped_into_backlog_without_dropping_ids(self):
        records = tuple(replace(fixture(f"sh.{600000 + index:06d}"), financial=None)
                        for index in range(3))
        report = BatchRunner().run(request(*records)).report
        self.assertEqual(len(report["evidence_backlog"]), 6)
        for gap in report["evidence_backlog"]:
            self.assertEqual(gap["gap"], "financial_inputs")
            self.assertEqual(gap["security_ids"], list(report["requested_security_ids"]))

    def test_stopped_and_passed_not_in_evidence_backlog(self):
        report = BatchRunner().run(demo_request()).report
        mentioned = {security for gap in report["evidence_backlog"] for security in gap["security_ids"]}
        self.assertEqual(mentioned, {"sh.600003", "sh.600005"})

    def test_as_of_invalidates_cache(self):
        runner = BatchRunner()
        runner.run(request(self.record))
        later = fixture(self.record.security_id, as_of=date(2026, 5, 2))
        later_request = replace(request(self.record), as_of=date(2026, 5, 2), inputs=(later,))
        self.assertEqual(runner.run(later_request).cache_hits, 0)

    def test_cache_not_poisoned_by_mutated_output(self):
        runner = BatchRunner()
        report = runner.run(request(self.record)).report
        expected = deepcopy(report)
        report["rows"][0]["enterprise_gates"][0]["status"] = "FAIL"
        self.assertEqual(runner.run(request(self.record)).report, expected)

    def test_logical_hash_covers_every_output_except_itself(self):
        report = BatchRunner().run(demo_request()).report
        reported = report.pop("logical_content_hash")
        self.assertEqual(reported, content_hash(report))
        report["rows"][0]["basic"]["evidence_refs"].append("new-ref")
        self.assertNotEqual(reported, content_hash(report))

    def test_decimal_global_context_does_not_change_output(self):
        expected = BatchRunner().run(request(self.record)).report
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(BatchRunner().run(request(self.record)).report, expected)

    def test_code_drift_during_session_rejected_not_relabelled(self):
        runner = BatchRunner()
        altered = deepcopy(implementation_identity())
        altered["source_sha256"]["scripts/screening/basic_filter.py"] = "0" * 64
        with patch("scripts.screening.batch_runner.implementation_identity", return_value=altered):
            with self.assertRaisesRegex(ValueError, "implementation changed"):
                runner.run(request(self.record))

    def test_rule_baseline_drift_hard_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "RULE_SPEC.md").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "baseline drift"):
                implementation_identity(root)

    def test_empty_request_is_diagnostic_not_official(self):
        report = BatchRunner().run(request()).report
        self.assertEqual(report["rows"], [])
        self.assertFalse(report["official_selection"])

    def test_batch_size_requires_positive_integer(self):
        runner = BatchRunner()
        for value in (0, -1, True, "2", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.run(request(), batch_size=value)

    def test_fixture_json_roundtrip(self):
        payload = demo_request().normalized()
        loaded = load_request(canonical_bytes(payload))
        self.assertEqual(loaded.normalized(), payload)

    def test_real_data_kind_and_unknown_schema_rejected(self):
        for changes in ({"data_kind": "REAL"}, {"schema": "other"}):
            payload = {**demo_request().normalized(), **changes}
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "SYNTHETIC_FIXTURE"):
                load_request(canonical_bytes(payload))

    def test_duplicate_json_key_float_and_nonfinite_rejected(self):
        for raw in (b'{"schema":"a","schema":"b"}', b'{"a":NaN}', b'{"a":1.1}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                load_request(raw)

    def test_unknown_config_and_alternate_weights_rejected(self):
        payload = demo_request().normalized()
        payload["max_results"] = 150
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            load_request(canonical_bytes(payload))
        payload.pop("max_results")
        payload["inputs"][0]["financial"]["quality_weights"] = {}
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            load_request(canonical_bytes(payload))

    def test_numeric_boolean_and_null_available_at_rejected(self):
        for field, value in (("latest_audit_unmodified", 1), ("latest_equity", True)):
            payload = demo_request().normalized()
            payload["inputs"][0]["financial"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                load_request(canonical_bytes(payload))
        payload = demo_request().normalized()
        payload["inputs"][0]["financial"]["annual_observations"][0]["available_at"] = None
        with self.assertRaisesRegex(ValueError, "ISO date"):
            load_request(canonical_bytes(payload))

    def test_bad_decimal_date_and_negative_capex_rejected(self):
        for value in ("NaN", "Infinity", " 1 ", 100):
            payload = demo_request().normalized()
            payload["inputs"][0]["basic"]["market_value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_request(canonical_bytes(payload))
        payload = demo_request().normalized()
        payload["as_of"] = "20260501"
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(payload))
        payload = demo_request().normalized()
        payload["inputs"][0]["financial"]["annual_observations"][0]["capex"] = "-1"
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(payload))

    def test_markdown_after_canonical_json_has_same_bytes(self):
        report = BatchRunner().run(demo_request()).report
        self.assertEqual(markdown(report), markdown(json.loads(canonical_bytes(report))))

    def test_output_never_overwrites_existing_report_or_input(self):
        report = BatchRunner().run(demo_request()).report
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report"
            write_output(output, report)
            before = (output / "diagnostic-only.json").read_bytes()
            with self.assertRaises(FileExistsError):
                write_output(output, report)
            self.assertEqual((output / "diagnostic-only.json").read_bytes(), before)

    def test_cli_demo_check_and_real_input_rejection(self):
        script = ROOT / "scripts/run_batch_screening.py"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report"
            command = [sys.executable, "-X", "utf8", str(script), "--demo", "--output", str(output)]
            generated = subprocess.run(command, capture_output=True)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            checked = subprocess.run(command + ["--check", "--batch-size", "1"], capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            denied = subprocess.run(command, capture_output=True)
            self.assertEqual(denied.returncode, 2)
            bad = Path(directory) / "real.json"
            payload = demo_request().normalized()
            payload["data_kind"] = "REAL"
            bad.write_bytes(canonical_bytes(payload))
            denied = subprocess.run([sys.executable, str(script), "--input", str(bad)], capture_output=True)
            self.assertEqual(denied.returncode, 2)
            self.assertIn(b"SYNTHETIC_FIXTURE", denied.stderr)


if __name__ == "__main__":
    unittest.main()
