"""Bounded Chinese annual title admission and unchanged table safety guards.

Mutated native text/geometry below is synthetic, not replacement source evidence.
Old refusal remains replayable; new observations are never historical PIT inputs.
"""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle
from scripts.parsing.annual_report_parser import _annual_identity, _lines, parse_annual
from scripts.parsing.field_binder import compact, union_box
from scripts.parsing.generic_extractor import PDFCache, Word
from scripts.pilots.replay_frozen_annual_rejection import replay_frozen_rejection
from scripts.screening.contracts import canonical_bytes, load_request


class AnnualTitleIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600585-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.pdf = PDFCache().parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])
        cls.report = build_bundle(cls.scope_raw)
        cls.bundle = cls.report["bundles"][0]
        cls.period = "报告期：2024年1月1日至2024年12月31日之期间"
        cls.old_raw = (ROOT / "docs/data-pilots/annual-holdout-600585-2026-10-03-v1/rejection.json").read_bytes()
        cls.arabic_source = json.loads((ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-000637-inputs.json").read_bytes())["sources"][0]
        cls.arabic_pdf = PDFCache().parse((ROOT / cls.arabic_source["pdf_path"]).read_bytes(), cls.arabic_source["pdf_sha256"])

    def line(self, pdf, number, old, new, *, duplicate=False, rotation=None):
        pages = list(pdf.pages)
        page = pages[number - 1]
        group = next(g for g in _lines(page.words) if compact("".join(w.text for w in g)) == old)
        words = [w for w in page.words if w not in group]
        if new is not None:
            words.append(Word(new, tuple(union_box(group))))
            if duplicate:
                box = union_box(group)
                words.append(Word(new, (box[0], box[1] + 32, box[2], box[3] + 32)))
        text = "\n".join("".join(w.text for w in g) for g in _lines(words))
        pages[number - 1] = replace(page, words=tuple(words), text=text,
                                    rotation=page.rotation if rotation is None else rotation)
        return replace(pdf, pages=tuple(pages))

    def title(self, text):
        return self.line(self.pdf, 1, "二〇二四年度报告", text)

    def test_real_chinese_title_binds_native_identity_and_period(self):
        evidence = self.bundle["document_identity_evidence"]
        self.assertEqual(evidence["kind"], "CHINESE_ANNUAL_TITLE_WITH_EXPLICIT_FULL_YEAR_PERIOD")
        self.assertEqual(evidence["document_sha256"], self.source["pdf_sha256"])
        self.assertEqual(evidence["issuer_text"], self.source["issuer"])
        self.assertEqual((evidence["physical_page"], evidence["period_physical_page"]), (1, 6))
        self.assertEqual(evidence["title_text"], "二〇二四年度报告")
        self.assertEqual(evidence["period_text"], self.period)
        self.assertEqual((evidence["period_start"], evidence["period_end"]), ("2024-01-01", "2024-12-31"))
        self.assertFalse(evidence["public_availability_verified"])
        for key in ("issuer_box", "title_box", "share_code_box", "period_box"):
            self.assertEqual(len(evidence[key]), 4)

    def test_year_is_derived_not_an_issuer_or_single_year_branch(self):
        pdf = self.title("二〇二五年度报告")
        pdf = self.line(pdf, 6, self.period, "报告期：2025年1月1日至2025年12月31日之期间")
        evidence = _annual_identity(pdf, {**self.source, "fiscal_year": 2025})
        self.assertEqual(evidence["declared_fiscal_year"], 2025)

    def test_legacy_arabic_title_still_admitted(self):
        self.assertIsNone(_annual_identity(self.arabic_pdf, self.arabic_source))
        self.assertIsNone(_annual_identity(self.title("2024年年度报告"), self.source))

    def test_wrong_chinese_year_rejected(self):
        with self.assertRaisesRegex(ValueError, "cover annual title"):
            _annual_identity(self.title("二〇二三年度报告"), self.source)

    def test_wrong_arabic_year_rejected(self):
        with self.assertRaisesRegex(ValueError, "cover annual title"):
            _annual_identity(self.title("2023年年度报告"), self.source)

    def test_other_title_syntax_not_added(self):
        for text in ("二零二四年度报告", "二〇二四年年度报告", "2024年度报告",
                     "二〇二四年度报告摘要", "二〇二四半年度报告", "二〇二四年度报告（修订版）"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                _annual_identity(self.title(text), self.source)

    def test_chinese_title_not_read_from_catalogue_or_later_body(self):
        pdf = self.title(None)
        pages = list(pdf.pages)
        pages[9] = replace(pages[9], text=pages[9].text + "\n二〇二四年度报告")
        with self.assertRaises(ValueError):
            _annual_identity(replace(pdf, pages=tuple(pages)), self.source)

    def test_arabic_text_elsewhere_cannot_bypass_chinese_period_guard(self):
        pdf = self.line(self.pdf, 6, self.period, None)
        pages = list(pdf.pages)
        pages[9] = replace(pages[9], text=pages[9].text + "\n2024年年度报告")
        with self.assertRaises(ValueError):
            _annual_identity(replace(pdf, pages=tuple(pages)), self.source)

    def test_wrong_issuer_or_security_identity_rejected(self):
        for change in ({"issuer": "其他发行人股份有限公司"}, {"security_id": "sh.600999"}, {"fiscal_year": 2023}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                _annual_identity(self.pdf, {**self.source, **change})

    def test_other_issuer_name_in_body_cannot_replace_cover_subject(self):
        pdf = self.line(self.pdf, 1, compact(self.source["issuer"]), "其他发行人股份有限公司")
        with self.assertRaises(ValueError):
            _annual_identity(pdf, self.source)

    def test_wrong_A_code_not_rescued_by_right_code_in_body(self):
        pdf = self.line(self.pdf, 1, "（A股：600585H股：00914）", "（A股：600999H股：00914）")
        with self.assertRaises(ValueError):
            _annual_identity(pdf, self.source)

    def test_H_code_or_naked_digits_not_A_share_evidence(self):
        for label in ("（H股：600585）", "600585", "（A股：1600585H股：00914）"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                _annual_identity(self.line(self.pdf, 1, "（A股：600585H股：00914）", label), self.source)

    def test_wrong_full_year_period_rejected(self):
        with self.assertRaisesRegex(ValueError, "reporting period"):
            _annual_identity(self.line(self.pdf, 6, self.period, "报告期：2023年1月1日至2023年12月31日"), self.source)

    def test_cross_year_short_or_partial_period_not_full_year(self):
        for period in ("报告期：2023年1月1日至2024年12月31日", "报告期：2024年1月1日至2024年6月30日",
                       "报告期：2024年1月1日", "报告期：2024年1-12月", "报告期：2024年2月1日至2024年12月31日"):
            with self.subTest(period=period), self.assertRaises(ValueError):
                _annual_identity(self.line(self.pdf, 6, self.period, period), self.source)

    def test_unsupported_or_missing_period_not_inferred_from_title(self):
        for period in (None, "比较期间：2024年1月1日至2024年12月31日", "报告期：未知"):
            with self.subTest(period=period), self.assertRaises(ValueError):
                _annual_identity(self.line(self.pdf, 6, self.period, period), self.source)

    def test_duplicate_period_definition_rejected_even_same_year(self):
        pdf = self.line(self.pdf, 6, self.period, self.period, duplicate=True)
        with self.assertRaises(ValueError):
            _annual_identity(pdf, self.source)

    def test_duplicate_chinese_cover_title_rejected(self):
        pdf = self.line(self.pdf, 1, "二〇二四年度报告", "二〇二四年度报告", duplicate=True)
        with self.assertRaises(ValueError):
            _annual_identity(pdf, self.source)

    def test_duplicate_cover_issuer_or_share_code_rejected(self):
        for label in (compact(self.source["issuer"]), "（A股：600585H股：00914）"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                _annual_identity(self.line(self.pdf, 1, label, label, duplicate=True), self.source)

    def test_clipped_or_rotated_cover_or_period_not_positive_evidence(self):
        for number, old in ((1, "二〇二四年度报告"), (6, self.period)):
            pdf = self.line(self.pdf, number, old, old, rotation=90)
            with self.subTest(number=number), self.assertRaises(ValueError):
                _annual_identity(pdf, self.source)
        pdf = self.title("二〇二四年度报告")
        pages = list(pdf.pages)
        pages[0] = replace(pages[0], width=200)
        with self.assertRaises(ValueError):
            _annual_identity(replace(pdf, pages=tuple(pages)), self.source)

    def test_explicit_wrong_period_also_vetoes_legacy_arabic_title(self):
        pdf = self.title("2024年年度报告")
        pdf = self.line(pdf, 6, self.period, "报告期：2023年1月1日至2023年12月31日")
        with self.assertRaisesRegex(ValueError, "reporting period"):
            _annual_identity(pdf, self.source)

    def test_report_period_outside_front_identity_window_not_used(self):
        pdf = self.line(self.pdf, 6, self.period, None)
        pages = list(pdf.pages)
        words = pages[5].words + (Word(self.period, (70, 500, 480, 516)),)
        pages[10] = replace(pages[10], words=words, text=self.period)
        with self.assertRaises(ValueError):
            _annual_identity(replace(pdf, pages=tuple(pages)), self.source)

    def test_same_original_PDF_hash_is_still_required(self):
        with self.assertRaisesRegex(ValueError, "source identity"):
            parse_annual(self.pdf, {**self.source, "pdf_sha256": "0" * 64})

    def test_identity_fix_does_not_fix_currency_or_inject_amounts(self):
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual({v["state"] for v in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})
        self.assertTrue(all(f["observed_value_cny"] is None for f in self.bundle["fields"].values()))
        self.assertEqual(self.bundle["balance_sheet_row_inventory"], [])
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertEqual(self.bundle["audit_text_observation"]["state"], "UNKNOWN")

    def test_unsupported_thousand_unit_remains_unknown(self):
        pdf = self.line(self.arabic_pdf, 93, "单位：元", "单位：千元")
        bundle = parse_annual(pdf, self.arabic_source)
        self.assertEqual(bundle["table_states"]["balance"]["state"], "HEADER_UNIT_YEAR_OR_COLUMNS_UNKNOWN")
        self.assertIsNone(bundle["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_supported_ten_thousand_unit_still_normalizes_not_assumes_yuan(self):
        pdf = self.line(self.arabic_pdf, 93, "单位：元", "单位：万元")
        bundle = parse_annual(pdf, self.arabic_source)
        self.assertEqual(bundle["fields"]["attributable_equity_end"]["observed_value_cny"], "5046233624900.00")
        self.assertEqual(bundle["table_states"]["balance"]["header"]["unit_multiplier"], 10000)

    def test_conflicting_continuation_unit_not_combined_with_original_header(self):
        pages = list(self.arabic_pdf.pages)
        page = pages[94]
        pages[94] = replace(page, words=page.words + (Word("单位：万元", (80, 70, 180, 80)),))
        bundle = parse_annual(replace(self.arabic_pdf, pages=tuple(pages)), self.arabic_source)
        self.assertIsNone(bundle["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_wrong_main_table_year_still_unknown(self):
        page = self.arabic_pdf.pages[100]
        groups = _lines(page.words)
        label = next(compact("".join(w.text for w in g)) for g in groups if "项目" in compact("".join(w.text for w in g)))
        pdf = self.line(self.arabic_pdf, 101, label, label.replace("2025", "2024"))
        bundle = parse_annual(pdf, self.arabic_source)
        self.assertIsNone(bundle["fields"]["operating_cash_flow"]["observed_value_cny"])

    def test_parent_statement_boundary_still_required(self):
        page = self.arabic_pdf.pages[94]
        words = tuple(replace(w, text="未知表") if "母公司资产负债表" in w.text else w for w in page.words)
        pages = list(self.arabic_pdf.pages)
        pages[94] = replace(page, words=words)
        bundle = parse_annual(replace(self.arabic_pdf, pages=tuple(pages)), self.arabic_source)
        self.assertIsNone(bundle["fields"]["attributable_equity_end"]["observed_value_cny"])
        self.assertEqual(bundle["table_states"]["balance"]["state"], "CONSOLIDATED_BOUNDARY_UNKNOWN")

    def test_old_rejection_keeps_bytes_and_executes_old_code(self):
        result = replay_frozen_rejection(
            ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600585-plan.json", self.scope_path,
            ROOT / "docs/data-pilots/annual-holdout-600585-2026-10-03-v1/rejection.json")
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["rejection_sha256"], hashlib.sha256(self.old_raw).hexdigest())
        self.assertFalse(result["normal_bundle_created"])

    def test_cold_warm_results_deterministic_with_fresh_logical_identity(self):
        cache = PDFCache()
        first, second = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))
        self.assertNotEqual(first["logical_content_hash"], json.loads(self.old_raw)["logical_content_hash"])

    def test_zero_pit_and_no_screening_export(self):
        self.assertEqual(self.report["timing_policy"], "UNKNOWN_UNLESS_VERIFIED")
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["screening_input_exported"])
        self.assertFalse(self.report["production_reader_ready"])
        self.assertFalse(self.report["real_pit_run_authorized"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))


if __name__ == "__main__":
    unittest.main()
