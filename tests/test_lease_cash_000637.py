"""Known financing cash is not the unresolved complete lease cash input."""

from __future__ import annotations

import copy
from decimal import Decimal, ROUND_DOWN, localcontext
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import fitz

from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import verify_lease_cash_000637 as pilot

ROOT = Path(__file__).resolve().parents[1]


def relabel(word, text):
    return (*word[:4], text, *word[5:])


class LeaseCashSourceReviewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = pilot.build_review(ROOT)
        doc = cls.report["source_documents"][0]
        raw = base.verified_bytes(ROOT, doc["path"], doc["sha256"])
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            cls.words = {page: pdf[page - 1].get_text("words") for page in (74, 101, 102, 183, 185)}

    def financing(self, notes=None, headers=None, main=None):
        return pilot.extract_financing_payment(self.words[183] if notes is None else notes,
                                              self.words[101] if headers is None else headers,
                                              self.words[102] if main is None else main)

    def test_two_versions_identify_financing_cash_not_full_lease_total(self):
        for bundle in self.report["version_bundles"]:
            component = bundle["financing_cash_component"]
            self.assertEqual(component["cash_payment"]["current_amount"], "13214300.68")
            self.assertEqual(component["cash_payment"]["prior_comparative_amount"], "14834290.95")
            self.assertEqual(component["cashflow_category"], "FINANCING")
            self.assertTrue(component["outside_OCF_and_Capex_in_source_presentation"])
            self.assertEqual(component["full_lease_cash_coverage"], "UNKNOWN")
            self.assertEqual(component["principal_interest_split"], "UNKNOWN")

    def test_note_components_reconcile_current_and_prior_to_main_statement(self):
        for key, expected in (("current_amount", "128214300.68"), ("prior_comparative_amount", "85086290.95")):
            check = self.financing()["reconciliation"][key]
            self.assertEqual(check["note_total"], expected)
            self.assertEqual(check["main_statement_total"], expected)
            self.assertEqual(Decimal(check["difference"]), 0)
            self.assertEqual(check["status"], "RECONCILED")

    def test_geometry_not_word_order_selects_current_prior_and_table(self):
        self.assertEqual(self.financing(), self.financing(notes=list(reversed(self.words[183])),
                                                       headers=list(reversed(self.words[101])),
                                                       main=list(reversed(self.words[102]))))
        self.assertEqual(pilot.extract_lease_expenses(self.words[185]),
                         pilot.extract_lease_expenses(list(reversed(self.words[185]))))

    def test_missing_financing_cash_is_not_comparative_or_zero(self):
        notes = [word for word in self.words[183] if word[4] != "13,214,300.68"]
        result = self.financing(notes=notes)
        self.assertIsNone(result["cash_payment"]["current_amount"])
        self.assertEqual(result["cash_payment"]["prior_comparative_amount"], "14834290.95")
        self.assertEqual(result["reconciliation"]["current_amount"]["status"], "UNKNOWN")

    def test_dash_unknown_cash_is_distinct_from_explicit_zero(self):
        notes = [relabel(word, "—") if word[4] == "13,214,300.68" else word for word in self.words[183]]
        self.assertIsNone(self.financing(notes=notes)["cash_payment"]["current_amount"])
        self.assertEqual(pilot.minority.parse_money_cell("0.00"), "0.00")

    def test_duplicate_payment_label_or_split_currency_fails(self):
        for label in (pilot.PAYMENT, "13,214,300.68"):
            target = next(word for word in self.words[183] if word[4] == label)
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.financing(notes=[*self.words[183], target])

    def test_unparseable_nonfinite_or_negative_payment_fails(self):
        for value in ("NaN", "Infinity", "-1.00"):
            notes = [relabel(word, value) if word[4] == "13,214,300.68" else word for word in self.words[183]]
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.financing(notes=notes)

    def test_note_total_or_main_statement_cent_drift_fails(self):
        notes = [relabel(word, "13,214,300.69") if word[4] == "13,214,300.68" else word for word in self.words[183]]
        with self.assertRaisesRegex(ValueError, "reconcile"):
            self.financing(notes=notes)
        main = [relabel(word, "128,214,300.69") if word[4] == "128,214,300.68" else word for word in self.words[102]]
        with self.assertRaisesRegex(ValueError, "differs"):
            self.financing(main=main)

    def test_payment_section_unit_or_year_columns_cannot_be_replaced(self):
        notes = [relabel(word, "其他分类") if word[4] == "（3）与筹资活动有关的现金" else word
                 for word in self.words[183]]
        with self.assertRaises(ValueError):
            self.financing(notes=notes)
        notes = [relabel(word, "单位：万元") if word[4] == "单位：元" else word for word in self.words[183]]
        with self.assertRaises(ValueError):
            self.financing(notes=notes)
        headers = [relabel(word, "2024" if word[4] == "2025" else "2025")
                   if word[4] in ("2025", "2024") else word for word in self.words[101]]
        with self.assertRaisesRegex(ValueError, "columns"):
            self.financing(headers=headers)

    def test_main_mother_company_row_cannot_replace_consolidated_cash(self):
        main = [word for word in self.words[102] if word[4] != pilot.MAIN_PAYMENT or word[1] > 400]
        with self.assertRaises(ValueError):
            self.financing(main=main)

    def test_note_scope_ignores_repeated_headers_but_duplicate_inside_fails(self):
        result = self.financing()
        self.assertEqual(result["cash_payment"]["current_amount"], "13214300.68")
        header = next(word for word in self.words[183] if word[4] == "本期发生额" and word[1] > 650)
        with self.assertRaises(ValueError):
            self.financing(notes=[*self.words[183], header])

    def test_variable_and_short_term_expenses_are_not_cash_observations(self):
        expenses = pilot.extract_lease_expenses(self.words[185])
        self.assertEqual(expenses["variable_lease_expense"]["current_amount"], "691333.32")
        self.assertEqual(expenses["variable_lease_expense"]["prior_comparative_amount"], "371190.47")
        self.assertEqual(expenses["short_term_lease_expense"]["current_amount"], "12645699.90")
        self.assertEqual(expenses["measurement_basis"], "EXPENSE_NOT_VERIFIED_CASH")
        self.assertEqual(expenses["cashflow_allocation"], "UNKNOWN")

    def test_short_term_comparative_clipped_is_not_empty_or_zero(self):
        row = pilot.extract_lease_expenses(self.words[185])["short_term_lease_expense"]
        self.assertIsNone(row["prior_comparative_amount"])
        self.assertEqual(row["prior_comparative_state"], "PAGE_EDGE_CLIPPED_NOT_OBSERVED")
        with self.assertRaisesRegex(ValueError, "clipped comparative layout"):
            pilot.extract_lease_expenses(self.words[185], page_width=800)

    def test_partial_comparative_currency_cannot_be_accepted_in_clipped_column(self):
        amount = next(word for word in self.words[185] if word[4] == "12,645,699.90")
        partial = (550, amount[1], 592, amount[3], "1.00", *amount[5:])
        with self.assertRaisesRegex(ValueError, "partial currency"):
            pilot.extract_lease_expenses([*self.words[185], partial])

    def test_lessor_income_is_not_added_or_netted_against_lessee_expense(self):
        words = [relabel(word, "99,999,999.99") if word[4] == "12,939,863.94" else word
                 for word in self.words[185]]
        self.assertEqual(pilot.extract_lease_expenses(words), pilot.extract_lease_expenses(self.words[185]))

    def test_contract_cash_interest_expense_are_not_a_complete_cash_total(self):
        table = pilot.extract_contract_summary(self.words[74])
        self.assertEqual(table["rent_paid_display"], "13565977.47")
        self.assertEqual(table["interest_expense_display"], "5869196.00")
        self.assertEqual(table["expense_display"], "2844651.25")
        self.assertTrue(table["not_added_to_financing_payment"])
        self.assertEqual(table["coverage"], "LISTED_CONTRACTS_NOT_PROVEN_CONSOLIDATED_CASH_UNIVERSE")

    def test_liability_is_preserved_as_excluded_stock_not_cash(self):
        for bundle in self.report["version_bundles"]:
            stock = bundle["liability_stock_excluded"]
            self.assertEqual(stock["current_amount"], "139414669.20")
            self.assertEqual(stock["basis"], "STOCK_NOT_CASH")
            self.assertTrue(stock["not_used_as_lease_cash"])
            self.assertIsNone(bundle["Lease_cash_not_already_deducted"])

    def test_reconciliation_uses_isolated_decimal_context(self):
        expected = self.financing()
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_DOWN
            self.assertEqual(self.financing(), expected)

    def test_full_lease_FCF_and_PIT_values_remain_unknown(self):
        for key in ("Lease_cash_not_already_deducted", "Lease_cash_pit", "FCF_conservative", "FCF", "diagnostic_available_at"):
            self.assertIsNone(self.report[key])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["production_reader_ready"])

    def test_full_amount_zero_fill_or_authority_tampering_fails_after_rehash(self):
        for key, value in (("Lease_cash_not_already_deducted", "13214300.68"), ("Lease_cash_not_already_deducted", "0.00"),
                           ("FCF_conservative", "1.00"), ("official_selection", True), ("diagnostic_available_at", "2026-04-30")):
            altered = copy.deepcopy(self.report)
            altered[key] = value
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                pilot.validate_review(altered)

    def test_component_classification_or_coverage_promotion_fails_after_rehash(self):
        for key, value in (("cashflow_category", "OPERATING"), ("full_lease_cash_coverage", "COMPLETE"),
                           ("pit_value", "13214300.68"), ("principal_interest_split", "KNOWN")):
            altered = copy.deepcopy(self.report)
            altered["version_bundles"][0]["financing_cash_component"][key] = value
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.validate_review(altered)

    def test_stock_expense_summary_or_clipped_zero_promotion_fails(self):
        for change in (lambda b: b["liability_stock_excluded"].update(not_used_as_lease_cash=False),
                       lambda b: b["expense_observations_not_cash"].update(measurement_basis="CASH"),
                       lambda b: b["contract_summary_not_full_coverage"].update(coverage="COMPLETE"),
                       lambda b: b["expense_observations_not_cash"]["short_term_lease_expense"].update(prior_comparative_amount="0.00")):
            altered = copy.deepcopy(self.report)
            change(altered["version_bundles"][0])
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.assertRaises(ValueError):
                pilot.validate_review(altered)

    def test_cross_version_pdf_or_physical_page_binding_changes_fail(self):
        for change in (lambda b: b.update(document_sha256="other"), lambda b: b.update(version="other"),
                       lambda b: b["financing_cash_component"].update(evidence_refs=["physical-page:184"])):
            altered = copy.deepcopy(self.report)
            change(altered["version_bundles"][0])
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.assertRaises(ValueError):
                pilot.validate_review(altered)

    def test_forbidden_rank_orders_or_FCF_window_and_removed_gaps_fail(self):
        for key in ("ranking", "orders", "F1"):
            altered = copy.deepcopy(self.report)
            altered[key] = []
            altered["logical_content_hash"] = base.logical_content_hash(altered)
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.validate_review(altered)
        altered = copy.deepcopy(self.report)
        altered["remaining_unknowns"] = []
        altered["logical_content_hash"] = base.logical_content_hash(altered)
        with self.assertRaises(ValueError):
            pilot.validate_review(altered)

    def test_source_hashes_and_every_prior_supplement_unchanged(self):
        for key in ("cashflow_supplement", "parent_report", "equity_supplement", "minority_supplement"):
            ref = self.report["manifest"][key]
            raw = base.verified_bytes(ROOT, ref["path"], ref["sha256"])
            self.assertEqual(base.logical_content_hash(base._json(raw)), ref["logical_content_hash"])
        for doc in self.report["source_documents"]:
            self.assertTrue(base.verified_bytes(ROOT, doc["path"], doc["sha256"]))
            self.assertEqual(doc["physical_page_count"], 209)
            self.assertFalse(doc["pit_admitted"])

    def test_two_rebuilds_reload_and_frozen_outputs_match(self):
        report = pilot.build_review(ROOT)
        self.assertEqual(report, pilot.build_review(ROOT))
        output = ROOT / pilot.DEFAULT_OUTPUT
        self.assertEqual((output / "diagnostic-only.json").read_bytes(), base.canonical_bytes(report) + b"\n")
        self.assertEqual((output / "diagnostic-only.md").read_bytes(), pilot.render_markdown(report).encode("utf-8"))
        self.assertEqual(pilot.render_markdown(report), pilot.render_markdown(base._json(base.canonical_bytes(report))))

    def test_offline_cli_does_not_call_network_readers_or_full_rules(self):
        with patch("socket.socket", side_effect=AssertionError("network")), \
             patch("turtle_quant.pit.parquet_financial_statements.ParquetFinancialStatementsReader.__init__",
                   side_effect=AssertionError("Reader")), \
             patch("turtle_quant.premise.general_fcf.evaluate_general_fcf", side_effect=AssertionError("premise")), \
             patch("turtle_quant.valuation.absolute.derive_attribution", side_effect=AssertionError("valuation")):
            self.assertEqual(pilot.build_review(ROOT), self.report)
        result = subprocess.run([sys.executable, "-I", "-X", "utf8", str(ROOT / pilot.TOOL), "--check"],
                                cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))

    def test_output_and_render_directories_are_never_overwritten(self):
        with TemporaryDirectory() as folder:
            with patch.object(pilot, "build_review", return_value=self.report), \
                 patch("sys.argv", ["pilot", "--output-dir", folder]), self.assertRaises(FileExistsError):
                pilot.main()
            with self.assertRaises(FileExistsError):
                pilot.build_review(ROOT, render_dir=Path(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_scope_source_page_value_or_version_changes_fail(self):
        original = base._json
        for modify in (lambda s: s.update(period_end="2024-12-31"),
                       lambda s: s["documents"][0].update(announcement_id="other"),
                       lambda s: s["physical_pages"].update(cashflow_note_payment=184),
                       lambda s: s["expected_per_version"].update(financing_lease_cash_current_cny="139414669.20")):
            def changed(raw):
                value = original(raw)
                if value.get("schema_version") == "lease_cash_source_review_scope_v1":
                    modify(value)
                return value
            with patch.object(base, "_json", side_effect=changed), self.assertRaises(ValueError):
                pilot.build_review(ROOT)
