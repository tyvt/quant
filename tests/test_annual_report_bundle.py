"""Real fixed PDFs plus synthetic geometry regressions; no historical PIT admission."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import localcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.extract_annual_report_bundle import ROOT, build_bundle, markdown, read_scope, verified_bytes
from scripts.parsing.annual_report_parser import parse_annual
from scripts.parsing.field_binder import cell, money
from scripts.parsing.generic_extractor import PDFCache, Page, Word
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


SCOPE_PATH = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-000637-inputs.json"


class AnnualBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_scope = SCOPE_PATH.read_bytes()
        cls.scope = read_scope(cls.raw_scope)
        cls.cache = PDFCache()
        cls.report = build_bundle(cls.raw_scope, cache=cls.cache)
        cls.source = cls.scope["sources"][0]
        cls.raw = (ROOT / cls.source["pdf_path"]).read_bytes()
        cls.pdf = cls.cache.parse(cls.raw, cls.source["pdf_sha256"])

    def changed_page(self, number, transform, **changes):
        pages = list(self.pdf.pages)
        pages[number - 1] = replace(pages[number - 1], words=tuple(transform(list(pages[number - 1].words))), **changes)
        return replace(self.pdf, pages=tuple(pages))

    def parse(self, pdf):
        return parse_annual(pdf, self.source)

    def test_group_extracts_all_requested_primary_fields_same_pass(self):
        expected = {"attributable_equity_end": "504623362.49", "minority_interest_end": "94585884.15",
                    "total_equity_end": "599209246.64", "parent_net_profit": "-141682789.73",
                    "total_net_profit": "-160400022.58", "capex": "62173312.84"}
        for bundle in self.report["bundles"]:
            for key, amount in expected.items():
                self.assertEqual(bundle["fields"][key]["observed_value_cny"], amount)
                self.assertEqual(bundle["fields"][key]["state"], "OBSERVED_NUMERIC")
            expected_ocf = "42986260.08" if bundle["source"]["version"].startswith("original") else "-79583416.97"
            self.assertEqual(bundle["fields"]["operating_cash_flow"]["observed_value_cny"], expected_ocf)

    def test_frozen_equity_cashflow_and_lease_regressions(self):
        equity = json.loads((ROOT / self.scope["reference_reports"][0]["path"]).read_bytes())
        cash = json.loads((ROOT / self.scope["reference_reports"][1]["path"]).read_bytes())
        for bundle in self.report["bundles"]:
            version = bundle["source"]["version"]
            old_e = next(row for row in equity["observations"] if row["version"] == version)
            old_n = next(row for row in equity["existing_N_dependencies"] if row["version"] == version)
            old_cash = next(row for row in cash["version_bundles"] if row["version"] == version)
            for key, old in (("attributable_equity_end", old_e), ("minority_interest_end", old_n),
                             ("operating_cash_flow", old_cash["OCF"]), ("capex", old_cash["Capex"])):
                self.assertEqual(bundle["fields"][key]["observed_value_cny"], old["observed_value"])
                self.assertEqual(bundle["fields"][key]["candidates"][0]["binding"]["document_sha256"], old["document_sha256"])
            self.assertEqual(bundle["lease_financing_component"]["observed_value_cny"], "13214300.68")

    def test_field_physical_page_header_and_version_bindings(self):
        pages = {"attributable_equity_end": (95, 93), "minority_interest_end": (95, 93),
                 "parent_net_profit": (98, 97), "operating_cash_flow": (101, 101), "capex": (101, 101)}
        for bundle in self.report["bundles"]:
            for field, (physical, header_page) in pages.items():
                binding = bundle["fields"][field]["candidates"][0]["binding"]
                self.assertEqual(binding["physical_page"], physical)
                self.assertEqual(binding["table_header"]["physical_page"], header_page)
                self.assertEqual(binding["source_version"], bundle["source"]["version"])
                self.assertEqual(binding["period_end"], "2025-12-31")
                self.assertEqual(binding["statement_scope"], "CONSOLIDATED")

    def test_same_pdf_reconciliations_without_filling_gaps(self):
        for bundle in self.report["bundles"]:
            self.assertEqual(len(bundle["reconciliations"]), 4)
            self.assertEqual({row["state"] for row in bundle["reconciliations"]}, {"RECONCILED"})
            self.assertEqual({row["difference_cny"] for row in bundle["reconciliations"]}, {"0.00"})

    def test_balance_inventory_retains_blank_treasury_not_zero(self):
        for bundle in self.report["bundles"]:
            rows = bundle["balance_sheet_row_inventory"]
            self.assertEqual(len(rows), 104)
            treasury = next(row for row in rows if row["source_label"] == "减：库存股")
            self.assertIsNone(treasury["current"]["value_cny"])
            self.assertEqual(treasury["current"]["state"], "BLANK_NOT_ZERO")
            self.assertFalse(bundle["full_balance_sheet_semantics_certified"])

    def test_parent_table_never_used_for_E_or_OCF(self):
        bundle = self.parse(self.pdf)
        self.assertNotEqual(bundle["fields"]["attributable_equity_end"]["observed_value_cny"], "927177837.86")
        self.assertNotEqual(bundle["fields"]["operating_cash_flow"]["observed_value_cny"], "-277287069.37")
        self.assertEqual(bundle["table_states"]["balance"]["end_boundary"]["physical_page"], 95)

    def test_capex_not_subtotal_or_asset_disposal_receipt(self):
        bundle = self.parse(self.pdf)
        capex = bundle["fields"]["capex"]
        self.assertEqual(capex["candidates"][0]["source_label"], "购建固定资产、无形资产和其他长期资产支付的现金")
        self.assertNotEqual(capex["observed_value_cny"], "570875.00")
        self.assertEqual(len(capex["candidates"][0]["binding"]["label_text"]), 2)

    def test_original_and_amended_not_chosen_as_latest_pit(self):
        self.assertEqual(len(self.report["bundles"]), 2)
        for bundle in self.report["bundles"]:
            self.assertIsNone(bundle["diagnostic_available_at"])
            self.assertEqual(bundle["pit_admitted_observation_count"], 0)
            self.assertEqual(bundle["version_identity_state"], "MATCHED_FROZEN_REFERENCES")

    def test_complete_lease_never_filled_with_identified_part(self):
        for bundle in self.report["bundles"]:
            lease = bundle["lease_financing_component"]
            self.assertFalse(lease["is_complete_lease_cash"])
            self.assertIsNone(lease["full_lease_cash_not_already_deducted"])
            self.assertIsNone(bundle["dependency_preview_only"]["lease_cash_not_already_deducted"])

    def test_audit_text_not_amended_full_audit_or_hard_gate(self):
        for bundle in self.report["bundles"]:
            audit = bundle["audit_text_observation"]
            self.assertEqual(audit["raw_opinion_type"], "标准的无保留意见")
            self.assertIsNone(audit["latest_audit_unmodified_pit"])
            self.assertEqual(audit["amended_whole_statement_audit_status"], "UNKNOWN")
            self.assertEqual(audit["candidates"][0]["binding"]["physical_page"], 88)

    def test_no_real_screening_input_export_or_valuation(self):
        self.assertFalse(self.report["screening_input_exported"])
        self.assertFalse(self.report["real_pit_run_authorized"])
        self.assertFalse(self.report["production_reader_ready"])
        for bundle in self.report["bundles"]:
            preview = bundle["dependency_preview_only"]
            self.assertIsNone(preview["available_at"])
            self.assertFalse(preview["admitted_to_hard_gates"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_cold_warm_pdf_cache_same_report_bytes(self):
        cache = PDFCache()
        first = build_bundle(self.raw_scope, cache=cache)
        second = build_bundle(self.raw_scope, cache=cache)
        self.assertEqual(cache.parsed_documents, 2)
        self.assertEqual(cache.cache_hits, 2)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))

    def test_pdf_cache_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.pdf.pages[0].text = "modified"

    def test_pdf_hash_mismatch_rejected_before_cache_use(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.cache.parse(self.raw + b"changed", self.source["pdf_sha256"])

    def test_cache_new_pdf_bytes_parse_separately(self):
        cache = PDFCache()
        first = cache.parse(self.raw, self.source["pdf_sha256"])
        amended = self.scope["sources"][1]
        second = cache.parse((ROOT / amended["pdf_path"]).read_bytes(), amended["pdf_sha256"])
        self.assertNotEqual(first.sha256, second.sha256)
        self.assertEqual(cache.parsed_documents, 2)

    def test_extractor_code_drift_requires_restart(self):
        cache = PDFCache()
        with patch("scripts.parsing.generic_extractor.Path.read_bytes", return_value=b"changed-code"):
            with self.assertRaisesRegex(ValueError, "changed during session"):
                cache.parse(self.raw, self.source["pdf_sha256"])

    def test_money_units_sign_commas_and_precision(self):
        self.assertEqual(money("-1,234.50", 10000), "-12345000.00")
        self.assertEqual(money("0.00", 1), "0.00")
        self.assertIsNone(money("—", 1))
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(money("123456789012345678901234567890.12", 10000),
                             "1234567890123456789012345678901200.00")

    def test_partial_unparseable_or_nonfinite_money_not_accepted(self):
        for value in ("12,34", "1.2.3", "NaN", "Infinity", "(100)", "123万元"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value, 1)

    def test_clipped_rotated_and_column_edge_cells_unknown(self):
        page = Page(1, 600, 800, 0, "", ())
        cases = ((Word("123.00", (580, 90, 630, 110)), page),
                 (Word("123.00", (300, 90, 360, 110)), replace(page, rotation=90)),
                 (Word("123.00", (390, 90, 430, 110)), page))
        for word, selected in cases:
            with self.subTest(word=word):
                observed = cell(selected, (word,), 100, 220, 400, 1)
                self.assertTrue(all(value["value_cny"] is None for value in observed.values()))

    def test_duplicate_numeric_cell_unknown_not_combined(self):
        page = Page(1, 600, 800, 0, "", ())
        words = (Word("12", (300, 90, 320, 110)), Word("34", (330, 90, 350, 110)))
        result = cell(page, words, 100, 220, 400, 1)
        self.assertEqual(result["current"]["state"], "AMBIGUOUS_CELL")
        self.assertIsNone(result["current"]["value_cny"])

    def test_blank_and_explicit_zero_different(self):
        page = Page(1, 600, 800, 0, "", ())
        blank = cell(page, (), 100, 220, 400, 1)
        zero = cell(page, (Word("0.00", (300, 90, 360, 110)),), 100, 220, 400, 1)
        self.assertIsNone(blank["current"]["value_cny"])
        self.assertEqual(zero["current"]["value_cny"], "0.00")

    def test_unknown_unit_not_assumed_yuan(self):
        pdf = self.changed_page(93, lambda words: [replace(word, text="单位：未知") if word.text == "单位：元" else word for word in words])
        bundle = self.parse(pdf)
        self.assertIsNone(bundle["fields"]["attributable_equity_end"]["observed_value_cny"])
        self.assertEqual(bundle["table_states"]["balance"]["state"], "HEADER_UNIT_YEAR_OR_COLUMNS_UNKNOWN")

    def test_missing_currency_keeps_all_numeric_fields_unknown(self):
        pages = tuple(replace(page, text="") if page.number == 117 else page for page in self.pdf.pages)
        bundle = self.parse(replace(self.pdf, pages=pages))
        self.assertIsNone(bundle["currency"])
        self.assertTrue(all(field["observed_value_cny"] is None for field in bundle["fields"].values()))

    def test_unit_normalization_is_bound_to_header(self):
        pdf = self.changed_page(93, lambda words: [replace(word, text="单位：万元") if word.text == "单位：元" else word for word in words])
        bundle = self.parse(pdf)
        self.assertEqual(bundle["fields"]["attributable_equity_end"]["observed_value_cny"], "5046233624900.00")
        self.assertEqual(bundle["fields"]["attributable_equity_end"]["candidates"][0]["binding"]["table_header"]["unit_multiplier"], 10000)

    def test_rotated_or_changed_continuation_not_silently_bound(self):
        for changes in ({"rotation": 90}, {"width": self.pdf.pages[94].width + 50}):
            pdf = self.changed_page(95, lambda words: words, **changes)
            self.assertIsNone(self.parse(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_missing_consolidated_boundary_unknown(self):
        pdf = self.changed_page(95, lambda words: [replace(word, text="未知表") if "母公司资产负债表" in word.text else word for word in words])
        bundle = self.parse(pdf)
        self.assertIsNone(bundle["fields"]["attributable_equity_end"]["observed_value_cny"])
        self.assertEqual(bundle["table_states"]["balance"]["state"], "CONSOLIDATED_BOUNDARY_UNKNOWN")

    def test_missing_E_not_back_calculated_from_N_and_total(self):
        pdf = self.changed_page(95, lambda words: [word for word in words if word.text != "504,623,362.49"])
        bundle = self.parse(pdf)
        self.assertIsNone(bundle["fields"]["attributable_equity_end"]["observed_value_cny"])
        self.assertEqual(bundle["reconciliations"][0]["state"], "UNKNOWN")

    def test_reconciliation_mismatch_hard_failure(self):
        pdf = self.changed_page(95, lambda words: [replace(word, text="504,623,362.50") if word.text == "504,623,362.49" else word for word in words])
        with self.assertRaisesRegex(ValueError, "reconciliation failed"):
            self.parse(pdf)

    def test_ambiguous_field_label_unknown_even_identical_source(self):
        def duplicate(words):
            original = next(word for word in words if word.text == "归属于母公司所有者权益合计")
            box = original.box
            return words + [replace(original, box=(box[0], box[1] - 5, box[2], box[3] - 5))]
        bundle = self.parse(self.changed_page(95, duplicate))
        self.assertEqual(bundle["fields"]["attributable_equity_end"]["state"], "AMBIGUOUS_LABEL")
        self.assertIsNone(bundle["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_missing_lease_row_not_full_zero(self):
        pdf = self.changed_page(183, lambda words: [word for word in words if word.text != "偿还租赁负债支付的金额"])
        bundle = self.parse(pdf)
        self.assertIsNone(bundle["lease_financing_component"]["observed_value_cny"])
        self.assertFalse(bundle["lease_financing_component"]["is_complete_lease_cash"])

    def test_wrong_issuer_year_security_or_pdf_identity_rejected(self):
        for changes in ({"issuer": "其他公司"}, {"fiscal_year": 2024}, {"security_id": "sz.000999"},
                        {"pdf_sha256": "0" * 64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_annual(self.pdf, {**self.source, **changes})

    def test_scope_duplicate_keys_ids_url_and_unknown_config_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            read_scope(b'{"schema":"a","schema":"b"}')
        for change in ("duplicate", "url", "unknown", "type"):
            payload = deepcopy(self.scope)
            if change == "duplicate":
                payload["sources"].append(payload["sources"][0])
            elif change == "url":
                payload["sources"][0]["url"] = payload["sources"][1]["url"]
            elif change == "unknown":
                payload["ready"] = True
            else:
                payload["sources"][0]["fiscal_year"] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                read_scope(canonical_bytes(payload))

    def test_wrong_frozen_version_and_page_count_hard_failure(self):
        for key, value in (("version", "other-version"), ("page_count", 208)):
            payload = deepcopy(self.scope)
            payload["sources"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_bundle(canonical_bytes(payload), cache=self.cache)

    def test_reference_hash_failure_and_unsafe_path(self):
        payload = deepcopy(self.scope)
        payload["reference_reports"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            build_bundle(canonical_bytes(payload), cache=self.cache)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            verified_bytes(ROOT, "../RULE_SPEC.md", "0" * 64)

    def test_rule_identity_drift_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "RULE_SPEC.md").write_bytes(b"different-rule")
            with self.assertRaisesRegex(ValueError, "baseline drift"):
                build_bundle(self.raw_scope, root=Path(directory))

    def test_report_hash_all_fields_and_canonical_markdown(self):
        report = deepcopy(self.report)
        recorded = report.pop("logical_content_hash")
        self.assertEqual(recorded, content_hash(report))
        report["bundles"][0]["fields"]["capex"]["state"] = "UNKNOWN"
        self.assertNotEqual(recorded, content_hash(report))
        self.assertEqual(markdown(self.report), markdown(json.loads(canonical_bytes(self.report))))

    def test_cli_check_never_overwrites_and_rejects_existing_directory(self):
        script = ROOT / "scripts/extract_annual_report_bundle.py"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report"
            command = [sys.executable, "-X", "utf8", str(script), "--scope", str(SCOPE_PATH), "--output", str(target)]
            created = subprocess.run(command, capture_output=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            expected = (target / "diagnostic-only.json").read_bytes()
            checked = subprocess.run(command + ["--check"], capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            denied = subprocess.run(command, capture_output=True)
            self.assertEqual(denied.returncode, 2)
            self.assertEqual((target / "diagnostic-only.json").read_bytes(), expected)

    def test_no_source_amounts_or_issuer_specific_pages_in_parser(self):
        source = (ROOT / "scripts/parsing/annual_report_parser.py").read_text(encoding="utf-8")
        for literal in ("000637", "504623362", "94585884", "79583416", "physical-page:95"):
            self.assertNotIn(literal, source)

    def test_independent_2024_holdout_versions_without_page_constants(self):
        ref = json.loads((ROOT / "docs/data-pilots/financial-2024-000637-2026-10-02/diagnostic-only.json").read_bytes())
        cache = PDFCache()
        for doc in ref["source_documents"]:
            source = {**self.source, "fiscal_year": 2024, "version": doc["role"],
                      "announcement_id": doc["announcement_id"], "url": doc["url"],
                      "pdf_path": doc["path"], "pdf_sha256": doc["sha256"], "page_count": doc["page_count"]}
            bundle = parse_annual(cache.parse((ROOT / doc["path"]).read_bytes(), doc["sha256"]), source)
            expected_ocf = "9077909.18" if doc["role"].startswith("original") else "-185115131.48"
            for field, expected in (("attributable_equity_end", "645132659.65"),
                                    ("minority_interest_end", "112947471.32"),
                                    ("operating_cash_flow", expected_ocf), ("capex", "79764639.75")):
                self.assertEqual(bundle["fields"][field]["observed_value_cny"], expected)
            self.assertEqual(bundle["lease_financing_component"]["observed_value_cny"], "14834290.95")
            self.assertNotEqual(bundle["fields"]["attributable_equity_end"]["candidates"][0]["binding"]["physical_page"], 95)

    def test_note_reference_sentence_not_used_as_section_title(self):
        from scripts.parsing.annual_report_parser import _title
        self.assertNotEqual(_title("万元。如合并财务报表项目注释"), "合并财务报表项目注释")
        self.assertEqual(_title("七、合并财务报表项目注释"), "合并财务报表项目注释")


if __name__ == "__main__":
    unittest.main()
