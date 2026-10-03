"""Second issuer: fixed source observations, not a newly admitted PIT fixture."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from unittest.mock import patch
import unittest

from scripts.extract_annual_report_bundle import (
    ROOT, LOADED_CODE_SHA256, build_bundle, markdown, read_scope, verified_bytes,
)
from scripts.parsing.annual_report_parser import parse_annual
from scripts.parsing.generic_extractor import PDFCache, Word
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class AnnualGeneralizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_scope = (ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-002570-inputs.json").read_bytes()
        cls.scope = read_scope(cls.raw_scope)
        cls.cache = PDFCache()
        cls.report = build_bundle(cls.raw_scope, cache=cls.cache)
        cls.source = cls.scope["sources"][0]
        cls.pdf = cls.cache.parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])
        cls.ref_path = cls.scope["reference_reports"][0]["path"]
        cls.reference = json.loads((ROOT / cls.ref_path).read_bytes())

    def modified(self, number, transform=lambda words: words, **changes):
        pages = list(self.pdf.pages)
        pages[number - 1] = replace(pages[number - 1], words=tuple(transform(list(pages[number - 1].words))), **changes)
        return replace(self.pdf, pages=tuple(pages))

    def parsed(self, pdf):
        return parse_annual(pdf, self.source)

    def test_three_versions_identify_seven_primary_values_and_lease_part(self):
        expected = {"attributable_equity_end": "1538639572.79", "minority_interest_end": "52472020.06",
                    "total_equity_end": "1591111592.85", "parent_net_profit": "-175996805.92",
                    "total_net_profit": "-164623055.49", "operating_cash_flow": "377416659.60",
                    "capex": "132306278.54"}
        self.assertEqual(len(self.report["bundles"]), 3)
        for bundle in self.report["bundles"]:
            self.assertEqual({key: value["observed_value_cny"] for key, value in bundle["fields"].items()}, expected)
            self.assertEqual(bundle["lease_financing_component"]["observed_value_cny"], "2125354.99")

    def test_title_and_adjacent_header_bound_to_distinct_physical_pages(self):
        for bundle in self.report["bundles"]:
            header = bundle["table_states"]["balance"]["header"]
            self.assertEqual(header["title_physical_page"], 73)
            self.assertEqual(header["physical_page"], 74)
            self.assertEqual(bundle["fields"]["attributable_equity_end"]["candidates"][0]["binding"]["physical_page"], 76)

    def test_full_dates_preserve_same_year_january_not_previous_year_end(self):
        header = self.report["bundles"][0]["table_states"]["balance"]["header"]
        self.assertEqual(header["current_column"], "2022年12月31日")
        self.assertEqual(header["comparative_column"], "2022年1月1日")
        self.assertNotEqual(header["comparative_column"], "2021年12月31日")

    def test_scoped_currency_declaration_has_original_heading_and_geometry(self):
        for bundle in self.report["bundles"]:
            self.assertEqual(bundle["currency"], "CNY")
            evidence = bundle["currency_evidence"][0]
            self.assertEqual(evidence["physical_page"], 97)
            self.assertEqual(evidence["kind"], "SCOPED_CURRENCY_POLICY_DECLARATION")
            self.assertIn("记账本位币", evidence["heading_text"])
            self.assertIn("采用人民币为记账本位币。", evidence["declaration_text"])
            self.assertEqual(len(evidence["declaration_box"]), 4)

    def test_cold_and_warm_cache_parse_three_distinct_documents_only(self):
        cache = PDFCache()
        first = build_bundle(self.raw_scope, cache=cache)
        second = build_bundle(self.raw_scope, cache=cache)
        self.assertEqual(cache.parsed_documents, 3)
        self.assertEqual(cache.cache_hits, 3)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))

    def test_original_probe_reclassifications_match_balance_row_inventory(self):
        probe = json.loads((ROOT / "docs/data-pilots/2026-10-01-core-financial-recorrection-002570.json").read_bytes())
        definitions = {field["field"]: field["source_label"] for field in probe["field_definitions"]}
        for bundle in self.report["bundles"]:
            prior = next(row for row in probe["observed_versions"] if row["role"] == bundle["source"]["version"])
            for name, value in prior["fields"].items():
                if name in ("revenue", "operating_cost", "operating_cashflow_net"):
                    continue  # Not all income rows are exported by the grouped tool.
                candidates = [row for row in bundle["balance_sheet_row_inventory"] if row["source_label"] == definitions[name]]
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]["current"]["value_cny"], value)

    def test_blank_liability_not_inferred_as_zero_from_later_version(self):
        values = {}
        for bundle in self.report["bundles"]:
            row = next(row for row in bundle["balance_sheet_row_inventory"] if row["source_label"] == "其他非流动负债")
            values[bundle["source"]["version"]] = row["current"]["value_cny"]
        self.assertIsNone(values["original_annual"])
        self.assertIsNone(values["first_corrected_annual"])
        self.assertEqual(values["second_corrected_annual"], "18000000.00")

    def test_treasury_equity_amount_not_converted_to_shares(self):
        for bundle in self.report["bundles"]:
            row = next(row for row in bundle["balance_sheet_row_inventory"] if row["source_label"] == "减：库存股")
            self.assertEqual(row["current"]["value_cny"], "130990041.76")
            self.assertNotIn("shares", bundle["dependency_preview_only"])
            self.assertFalse(bundle["dependency_preview_only"]["admitted_to_hard_gates"])

    def test_audit_emphasis_retained_without_promoting_to_standard_or_gate(self):
        for bundle in self.report["bundles"]:
            audit = bundle["audit_text_observation"]
            self.assertEqual(audit["raw_opinion_type"], "带强调事项段的无保留意见")
            self.assertIsNone(audit["latest_audit_unmodified_pit"])
            self.assertEqual(audit["amended_whole_statement_audit_status"], "UNKNOWN")

    def test_nested_zero_admission_reference_accepted_explicitly(self):
        self.assertNotIn("pit_admitted_observation_count", self.reference)
        self.assertEqual(self.reference["timing_assumptions"]["admitted_pit_observation_count"], 0)
        self.assertEqual({row["version_identity_state"] for row in self.report["bundles"]}, {"MATCHED_FROZEN_REFERENCES"})

    def test_reference_missing_unknown_or_nonzero_admission_never_defaults_to_zero(self):
        variants = []
        for key, value in (("admitted_pit_observation_count", 1), ("admitted_pit_observation_count", False),
                           ("policy", "ASSUMED_NEXT_DAY"), ("available_at", "2023-05-01")):
            ref = deepcopy(self.reference)
            ref["timing_assumptions"][key] = value
            variants.append(ref)
        for key in ("admitted_pit_observation_count", "available_at"):
            ref = deepcopy(self.reference)
            ref["timing_assumptions"].pop(key)
            variants.append(ref)
        for key in ("production_reader_ready", "real_pit_strategy_run", "official_selection"):
            ref = deepcopy(self.reference)
            ref[key] = True
            variants.append(ref)
        for ref in variants:
            raw = canonical_bytes(ref)
            scope = deepcopy(self.scope)
            scope["reference_reports"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
            def mocked(root, path, expected):
                return raw if path == self.ref_path else verified_bytes(root, path, expected)
            with patch("scripts.extract_annual_report_bundle.verified_bytes", side_effect=mocked):
                with self.assertRaisesRegex(ValueError, "frozen source-only"):
                    build_bundle(canonical_bytes(scope), cache=self.cache)

    def test_currency_phrase_without_scoped_heading_not_admitted(self):
        pdf = self.modified(97, lambda words: [replace(word, text="其他政策") if "4、记账本位币" in word.text else word for word in words])
        self.assertIsNone(self.parsed(pdf)["currency"])

    def test_missing_currency_declaration_not_filled_from_yuan_units(self):
        pdf = self.modified(97, lambda words: [word for word in words if word.text != "采用人民币为记账本位币。"])
        bundle = self.parsed(pdf)
        self.assertIsNone(bundle["currency"])
        self.assertTrue(all(field["observed_value_cny"] is None for field in bundle["fields"].values()))

    def test_foreign_subsidiary_only_currency_declaration_not_issuer_evidence(self):
        pdf = self.modified(97, lambda words: [replace(word, text="境外子公司采用人民币为记账本位币。")
                                             if word.text == "采用人民币为记账本位币。" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["currency"])

    def test_rotated_currency_policy_unknown(self):
        self.assertIsNone(self.parsed(self.modified(97, rotation=90))["currency"])

    def test_wrong_closing_month_keeps_equity_unknown(self):
        pdf = self.modified(74, lambda words: [replace(word, text="年11") if word.text == "年12" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_wrong_opening_month_does_not_silently_use_two_matching_years(self):
        pdf = self.modified(74, lambda words: [replace(word, text="年2") if word.text == "年1" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_third_numeric_column_is_not_relabelled_as_two_columns(self):
        pdf = self.modified(74, lambda words: words + [Word("2020年12月31日", (540, 99.654, 590, 109.75))])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_header_not_searched_beyond_immediate_next_page(self):
        pdf = self.modified(74, lambda words: [word for word in words if word.text != "项目"])
        pages = list(pdf.pages)
        header_word = next(word for word in self.pdf.pages[73].words if word.text == "项目")
        pages[74] = replace(pages[74], words=pages[74].words + (header_word,))
        self.assertIsNone(self.parsed(replace(pdf, pages=tuple(pages)))["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_rotated_table_title_page_is_unknown_even_next_page_is_upright(self):
        bundle = self.parsed(self.modified(73, rotation=90))
        self.assertEqual(bundle["table_states"]["balance"]["state"], "TABLE_TITLE_GEOMETRY_UNKNOWN")

    def test_capex_not_net_investment_or_investing_subtotal(self):
        capex = self.report["bundles"][0]["fields"]["capex"]
        self.assertEqual(capex["observed_value_cny"], "132306278.54")
        self.assertNotEqual(capex["observed_value_cny"], "135275985.29")
        self.assertEqual(capex["candidates"][0]["source_label"], "购建固定资产、无形资产和其他长期资产支付的现金")

    def test_lease_payment_classification_is_bound_to_nearest_note_heading(self):
        for bundle in self.report["bundles"]:
            lease = bundle["lease_financing_component"]
            evidence = lease["candidates"][0]["classification_evidence"]
            self.assertEqual(evidence["classification"], "FINANCING_PAYMENT")
            self.assertIn("支付的其他与筹资活动有关的现金", evidence["text"])
            self.assertFalse(lease["is_complete_lease_cash"])

    def test_lease_under_receipt_heading_not_financing_payment_observation(self):
        pdf = self.modified(153, lambda words: [replace(word, text=word.text.replace("支付的其他与筹资", "收到的其他与筹资")) for word in words])
        self.assertIsNone(self.parsed(pdf)["lease_financing_component"]["observed_value_cny"])

    def test_lease_under_operating_heading_not_filled_as_financing_part(self):
        pdf = self.modified(153, lambda words: [replace(word, text=word.text.replace("支付的其他与筹资", "支付的其他与经营")) for word in words])
        self.assertIsNone(self.parsed(pdf)["lease_financing_component"]["observed_value_cny"])

    def test_lease_expense_alias_not_cash_payment(self):
        pdf = self.modified(153, lambda words: [replace(word, text="租赁费用") if word.text == "租赁支付的现金" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["lease_financing_component"]["observed_value_cny"])

    def test_ambiguous_lease_labels_not_first_match_wins(self):
        def duplicate(words):
            selected = next(word for word in words if word.text == "租赁支付的现金")
            x0, y0, x1, y1 = selected.box
            return words + [replace(selected, box=(x0, y0 - 5, x1, y1 - 5))]
        lease = self.parsed(self.modified(153, duplicate))["lease_financing_component"]
        self.assertEqual(lease["state"], "AMBIGUOUS_LABEL")
        self.assertIsNone(lease["observed_value_cny"])

    def test_version_security_and_page_binding_are_not_company_template(self):
        for bundle in self.report["bundles"]:
            source = bundle["source"]
            for field in bundle["fields"].values():
                row = field["candidates"][0]["binding"]
                self.assertEqual(row["document_sha256"], source["pdf_sha256"])
                self.assertEqual(row["source_version"], source["version"])
                self.assertEqual(row["security_id"], "sz.002570")
                self.assertEqual(row["fiscal_year"], 2022)
                self.assertIsNone(row["diagnostic_available_at"])

    def test_three_versions_remain_observations_not_pit_input_or_ranking(self):
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["screening_input_exported"])
        for bundle in self.report["bundles"]:
            self.assertIsNone(bundle["dependency_preview_only"]["available_at"])
            self.assertIsNone(bundle["dependency_preview_only"]["lease_cash_not_already_deducted"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_code_drift_cannot_label_loaded_parser_as_new_implementation(self):
        changed = {**LOADED_CODE_SHA256, "scripts/parsing/annual_report_parser.py": "0" * 64}
        with patch("scripts.extract_annual_report_bundle._code_hashes", return_value=changed):
            with self.assertRaisesRegex(ValueError, "changed during session"):
                build_bundle(self.raw_scope, cache=self.cache)

    def test_wrong_security_id_000662_is_not_beingmate(self):
        with self.assertRaisesRegex(ValueError, "security identity"):
            parse_annual(self.pdf, {**self.source, "security_id": "sz.000662"})

    def test_canonical_report_hash_and_markdown_reloading_stable(self):
        report = deepcopy(self.report)
        digest = report.pop("logical_content_hash")
        self.assertEqual(digest, content_hash(report))
        self.assertEqual(markdown(self.report), markdown(json.loads(canonical_bytes(self.report))))


if __name__ == "__main__":
    unittest.main()
