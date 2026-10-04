"""Bounded payment-context inheritance never admits full lease cash or PIT."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.parsing.annual_report_parser import _lease, LEASE_LABELS, LEASE_CONTINUATION_LABEL
from scripts.parsing.generic_extractor import PDFCache, Page, ParsedPDF, Word
from scripts.pilots import build_annual_lease_continuation_regression as regression
from scripts.screening.contracts import canonical_bytes, content_hash, load_request

ROOT = regression.ROOT
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-lease-continuation-regression-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-lease-continuation-fix-2026-10-04-v2/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-lease-continuation-fix-2026-10-04-v2/evidence-index.json"
SOURCE = {"security_id": "sh.600001", "issuer": "测试股份有限公司", "fiscal_year": 2024,
          "version": "original", "pdf_sha256": "a" * 64}


def w(text, y, x=30, right=270):
    return Word(text, (x, y, right, y + 10))


def fixture():
    def page(n, words):
        return Page(n, 600, 842, 0, "\n".join(x.text for x in words), tuple(words), (0, 0, 600, 842), (0, 0, 600, 842))
    first = page(1, [w("七、合并财务报表项目注释", 70), w("支付的其他与筹资活动有关的现金", 700),
                     w("√适用", 730), w("□不适用", 730, 290, 345), w("1/3", 798)])
    second = page(2, [w("单位：元", 75), w("项目", 100, right=65), w("本期发生额", 100, 330, 410),
        w("上期发生额", 100, 470, 550), w("支付手续费", 125), w("1.23", 125, 330, 410),
        w(LEASE_CONTINUATION_LABEL, 150), w("10.00", 150, 330, 410), w("5.00", 150, 470, 550),
        w("合计", 180), w("11.23", 180, 330, 410), w("5.00", 180, 470, 550),
        w("60、现金流量表补充资料", 240), w("2/3", 798)])
    third = page(3, [w("十八、母公司财务报表主要项目注释", 100)])
    return ParsedPDF("a" * 64, "synthetic", "b" * 64, (first, second, third))


def alter(pdf, n, transform):
    pages = list(pdf.pages)
    words = tuple(transform(list(pages[n - 1].words)))
    pages[n - 1] = replace(pages[n - 1], words=words, text="\n".join(x.text for x in words))
    return replace(pdf, pages=tuple(pages))


def seal(report):
    report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
    return report


class BoundedContinuationParserTests(unittest.TestCase):
    def observe(self, pdf=None):
        return _lease(fixture() if pdf is None else pdf, SOURCE)

    def unknown(self, pdf):
        self.assertIsNone(self.observe(pdf)["observed_value_cny"])

    def test_adjacent_context_has_both_source_pages_and_geometry(self):
        value = self.observe()
        self.assertEqual((value["observed_value_cny"], value["comparative_not_target_value_cny"]), ("10.00", "5.00"))
        row = value["candidates"][0]
        self.assertEqual(row["classification_evidence"]["physical_page"], 1)
        self.assertEqual(row["binding"]["physical_page"], 2)
        self.assertEqual(row["binding"]["document_sha256"], SOURCE["pdf_sha256"])
        self.assertEqual([p["physical_page"] for p in row["continuation_evidence"]["page_geometry"]], [1, 2])
        for key in ("unit_and_header_inherited", "label_or_amount_joined", "complete_lease_cash_certified", "public_availability_verified"):
            self.assertIs(row["continuation_evidence"][key], False)
        self.assertIsNone(value["full_lease_cash_not_already_deducted"])
        self.assertFalse(row["binding"]["pit_admitted"])

    def test_existing_same_page_whitelist_not_expanded(self):
        self.assertEqual(LEASE_LABELS, ("偿还租赁负债支付的金额", "租赁支付的现金", "支付租赁款", "长期租赁付款", "支付租赁负债"))

    def test_source_hash_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "source identity mismatch"):
            _lease(fixture(), {**SOURCE, "pdf_sha256": "c" * 64})

    def test_nonadjacent_or_reordered_physical_pages_not_linked(self):
        pdf = fixture()
        for index, number in ((0, 0), (0, 5), (1, 3)):
            pages = list(pdf.pages)
            pages[index] = replace(pages[index], number=number)
            self.unknown(replace(pdf, pages=tuple(pages)))

    def test_only_one_previous_page_not_two_back(self):
        pdf = fixture()
        empty = replace(pdf.pages[0], number=2, words=(), text="")
        self.unknown(replace(pdf, pages=(pdf.pages[0], empty, replace(pdf.pages[1], number=3), replace(pdf.pages[2], number=4))))

    def test_rotation_dimensions_crop_or_missing_metadata_rejected(self):
        pdf = fixture()
        for n in (0, 1):
            for change in ({"rotation": 90}, {"width": 601.5}, {"height": 852}, {"cropbox": None},
                           {"mediabox": None}, {"cropbox": (5, 0, 595, 842)},
                           {"cropbox": (5, 0, 605, 842), "mediabox": (5, 0, 605, 842)}):
                pages = list(pdf.pages)
                pages[n] = replace(pages[n], **change)
                self.unknown(replace(pdf, pages=tuple(pages)))

    def test_non_foot_heading_not_inherited(self):
        self.unknown(alter(fixture(), 1, lambda ws: [replace(x, box=(30, 500, 270, 510)) if "筹资活动" in x.text else x for x in ws]))

    def test_operating_investing_receiving_or_missing_heading_rejected(self):
        for text in ("支付的其他与经营活动有关的现金", "支付的其他与投资活动有关的现金", "收到的其他与筹资活动有关的现金", "与筹资活动有关的现金"):
            self.unknown(alter(fixture(), 1, lambda ws: [replace(x, text=text) if "筹资活动" in x.text else x for x in ws]))

    def test_duplicate_foot_heading_rejected(self):
        self.unknown(alter(fixture(), 1, lambda ws: ws + [w("支付的其他与筹资活动有关的现金", 710)]))

    def test_intervening_paragraph_or_new_table_not_deleted(self):
        for text in ("说明：其他事项", "61、其他附注", "项目", "单位：元"):
            self.unknown(alter(fixture(), 1, lambda ws: ws + [w(text, 760)]))

    def test_previous_heading_or_applicability_clipped_rejected(self):
        for text in ("支付的其他与筹资活动有关的现金", "√适用"):
            self.unknown(alter(fixture(), 1, lambda ws: [replace(x, box=(30, x.box[1], 610, x.box[3])) if x.text == text else x for x in ws]))

    def test_current_page_preface_or_competing_cash_context_rejected(self):
        for text in ("未知的新事项", "支付的其他与经营活动有关的现金", "支付的其他与筹资活动有关的现金", "60、其他附注"):
            self.unknown(alter(fixture(), 2, lambda ws: ws + [w(text, 65)]))

    def test_intervening_context_after_header_rejected(self):
        self.unknown(alter(fixture(), 2, lambda ws: ws + [w("收到的其他与筹资活动有关的现金", 140)]))

    def test_wrong_or_missing_unit_not_borrowed(self):
        for text in ("单位：千元", "单位：美元", "单位：未知"):
            self.unknown(alter(fixture(), 2, lambda ws: [replace(x, text=text) if x.text == "单位：元" else x for x in ws]))
        pdf = alter(fixture(), 1, lambda ws: ws + [w("单位：元", 650)])
        self.unknown(alter(pdf, 2, lambda ws: [x for x in ws if x.text != "单位：元"]))

    def test_multiple_unit_candidates_rejected(self):
        self.unknown(alter(fixture(), 2, lambda ws: ws + [w("单位：元", 65)]))

    def test_supported_unit_conversion_and_negative_source_retained(self):
        pdf = alter(fixture(), 2, lambda ws: [replace(x, text="单位：万元") if x.text == "单位：元" else replace(x, text="-10.00") if x.text == "10.00" else x for x in ws])
        self.assertEqual(self.observe(pdf)["observed_value_cny"], "-100000.00")

    def test_wrong_year_swapped_or_unknown_period_columns_rejected(self):
        for text in ("2023年度", "2024年度", "上期发生额", "本年累计"):
            self.unknown(alter(fixture(), 2, lambda ws: [replace(x, text=text) if x.text == "本期发生额" else x for x in ws]))

    def test_extra_amount_column_not_discarded(self):
        self.unknown(alter(fixture(), 2, lambda ws: ws + [w("2022年度", 100, 180, 240)]))

    def test_first_invalid_or_duplicate_header_not_bypassed(self):
        for y in (65, 140, 210):
            self.unknown(alter(fixture(), 2, lambda ws: ws + [w("项目", y, right=65)]))

    def test_missing_or_early_or_duplicate_next_note_rejected(self):
        self.unknown(alter(fixture(), 2, lambda ws: [x for x in ws if not x.text.startswith("60、")]))
        self.unknown(alter(fixture(), 2, lambda ws: ws + [w("59、其他新附注", 130)]))
        self.unknown(alter(fixture(), 2, lambda ws: ws + [w("61、另项附注", 240)]))

    def test_mother_company_and_duplicate_scope_not_linked(self):
        self.unknown(alter(fixture(), 1, lambda ws: ws + [w("十八、母公司财务报表主要项目注释", 680)]))
        self.unknown(alter(fixture(), 1, lambda ws: ws + [w("七、合并财务报表项目注释", 80)]))

    def test_heading_before_explicit_consolidated_scope_rejected(self):
        pdf = alter(fixture(), 1, lambda ws: [x for x in ws if "合并财务" not in x.text])
        self.unknown(alter(pdf, 2, lambda ws: ws + [w("七、合并财务报表项目注释", 65)]))

    def test_duplicate_split_or_partial_label_not_joined(self):
        self.unknown(alter(fixture(), 2, lambda ws: ws + [w(LEASE_CONTINUATION_LABEL, 170)]))
        for text in ("偿还租赁负债本金和利息", "偿还租赁负债款", "租赁負债", "如" + LEASE_CONTINUATION_LABEL):
            self.unknown(alter(fixture(), 2, lambda ws: [replace(x, text=text) if x.text == LEASE_CONTINUATION_LABEL else x for x in ws] + [w("所支付的现金", 162)]))

    def test_other_supported_payment_label_in_same_table_not_selected_or_added(self):
        for label in LEASE_LABELS:
            self.unknown(alter(fixture(), 2, lambda ws: ws + [w(label, 165)]))

    def test_clipped_or_amount_overlapping_label_rejected(self):
        for right in (610, 330):
            self.unknown(alter(fixture(), 2, lambda ws: [replace(x, box=(30, 150, right, 160)) if x.text == LEASE_CONTINUATION_LABEL else x for x in ws]))

    def test_amount_boundary_and_multiple_native_tokens_remain_unknown(self):
        pdf = alter(fixture(), 2, lambda ws: [replace(x, box=(430, 150, 445, 160)) if x.text == "10.00" else x for x in ws])
        value = self.observe(pdf)
        self.assertEqual(value["state"], "COLUMN_EDGE_AMBIGUOUS")
        self.assertIsNone(value["observed_value_cny"])
        self.unknown(alter(fixture(), 2, lambda ws: ws + [w("10.00", 150, 300, 320)]))

    def test_blank_dash_not_zero_or_comparative_backfill(self):
        for text in (None, "—", "-"):
            pdf = alter(fixture(), 2, lambda ws: [replace(x, text=text) if x.text == "10.00" else x
                                               for x in ws if x.text != "10.00" or text is not None])
            value = self.observe(pdf)
            self.assertIsNone(value["observed_value_cny"])
            self.assertEqual(value["comparative_not_target_value_cny"], "5.00")

    def test_comparative_blank_kept_with_current_numeric(self):
        value = self.observe(alter(fixture(), 2, lambda ws: [x for x in ws if x.text != "5.00" or x.y != 155]))
        self.assertEqual(value["observed_value_cny"], "10.00")
        self.assertIsNone(value["comparative_not_target_value_cny"])
        self.assertEqual(value["candidates"][0]["comparative"]["state"], "BLANK_NOT_ZERO")

    def test_unparseable_amount_not_repaired(self):
        for text in ("+10.00", "1e2", "NaN", "(10.00)"):
            self.unknown(alter(fixture(), 2, lambda ws: [replace(x, text=text) if x.text == "10.00" else x for x in ws]))

    def test_same_page_long_label_not_added_as_general_alias(self):
        pdf = alter(fixture(), 2, lambda ws: ws + [w("支付的其他与筹资活动有关的现金", 65)])
        self.unknown(pdf)

    def test_existing_short_labels_not_enabled_cross_page(self):
        for label in LEASE_LABELS:
            self.unknown(alter(fixture(), 2, lambda ws: [replace(x, text=label) if x.text == LEASE_CONTINUATION_LABEL else x for x in ws]))


class ContinuationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = SCOPE.read_bytes()
        cls.plan = json.loads(cls.raw)
        with patch("requests.sessions.Session.request", side_effect=AssertionError("offline")):
            cls.report = regression.build_regression(cls.raw)
        cls.index = regression.public_index(cls.report)
        cls.rows = {r["source"]["security_id"]: r for r in cls.report["observations"]}

    def test_fourteen_sources_only_yutong_component_changes(self):
        self.assertEqual(self.report["counts"], {"issuers": 11, "PDF_versions": 14, "component_changed_PDFs": 1,
            "component_observed_PDFs": 9, "evaluated_unknown_PDFs": 1, "currency_blocked_PDFs": 4})
        self.assertEqual([r["source"]["security_id"] for r in self.report["observations"] if r["component_changed"]], ["sh.600066"])
        self.assertEqual(self.rows["sh.600066"]["current_component"]["observed_value_cny"], "14990744.76")

    def test_current_yutong_source_words_and_pages_match_PDF(self):
        row = self.rows["sh.600066"]
        source = row["source"]
        pdf = PDFCache().parse((ROOT / source["pdf_path"]).read_bytes(), source["pdf_sha256"])
        c = row["current_component"]["candidates"][0]
        self.assertEqual((c["classification_evidence"]["physical_page"], c["binding"]["physical_page"]), (125, 126))
        native = {(x.text, x.box) for x in pdf.pages[125].words}
        self.assertIn((c["source_label"], tuple(c["binding"]["label_box"])), native)
        for col in ("current", "comparative"):
            for text, box in zip(c[col]["raw_text"], c[col]["boxes"]):
                self.assertIn((text, tuple(box)), native)
        for p in pdf.pages[124:126]:
            self.assertEqual(p.cropbox, p.mediabox)

    def test_other_thirteen_lease_components_unchanged(self):
        for row in self.report["observations"]:
            if row["source"]["security_id"] != "sh.600066":
                self.assertEqual(row["current_component"], row["baseline_component"])
        self.assertIsNone(self.rows["sh.600887"]["current_component"]["observed_value_cny"])
        self.assertIsNone(self.rows["sh.600585"]["currency"])

    def test_all_non_lease_values_and_boundaries_unchanged(self):
        old = json.loads((ROOT / self.plan["baseline_private_report"]["path"]).read_bytes())
        previous = {regression.source_key(r["source"]): r for r in old["observations"]}
        for row in self.report["observations"]:
            self.assertEqual(row["non_lease_bundle_content_hash"], previous[regression.source_key(row["source"])]["non_lease_bundle_content_hash"])

    def test_all_six_parent_refs_bytes_preserved(self):
        for name in regression.REFS:
            ref = self.plan[name]
            self.assertEqual(hashlib.sha256((ROOT / ref["path"]).read_bytes()).hexdigest(), ref["sha256"])

    def test_old_development_bytes_are_not_rewritten_as_final_v2(self):
        directory = ROOT / "storage/pilots/annual-lease-continuation-fix-2026-10-04-v1"
        self.assertEqual(hashlib.sha256((directory / "diagnostic-only.json").read_bytes()).hexdigest(),
                         "9635f0414b1ea2b91a702ecf452845ff3f2d35a5eb8069fc916e3aa35996f13a")
        self.assertEqual(hashlib.sha256((directory / "development-parser.py").read_bytes()).hexdigest(),
                         "ba8d19fb20c65f98108928c0aed33258c1ddd596c7fc3c48896b1a9477473736")

    def test_full_lease_FCF_PIT_and_screening_never_promoted(self):
        for row in self.report["observations"]:
            self.assertIsNone(row["FCF_conservative"])
            self.assertIsNone(row["full_lease_cash"])
            self.assertIsNone(row["current_component"]["pit_value"])
            self.assertFalse(row["current_component"]["is_complete_lease_cash"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_canonical_artifacts_match_fresh_execution(self):
        self.assertEqual(PRIVATE.read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual(PUBLIC.read_bytes(), canonical_bytes(self.index) + b"\n")
        self.assertNotEqual(self.report["logical_content_hash"], self.index["logical_content_hash"])

    def test_public_index_omits_all_original_text_channels(self):
        raw = canonical_bytes(self.index)
        for key in (b'"text":', b'"words":', b'"raw_text":', b'"native_text":', b'"table_header":', b'"post_heading_native_words":'):
            self.assertNotIn(key, raw)
        self.assertNotIn("支付的其他与筹资活动有关的现金".encode("utf-8"), raw)

    def test_unexpected_raw_text_is_not_projected(self):
        report = deepcopy(self.report)
        report["entire_original_page"] = "private original text"
        self.assertNotIn(b"private original", canonical_bytes(regression.public_index(seal(report))))

    def test_coordinate_and_label_text_cannot_be_smuggled(self):
        for field, value in (("source_label", "arbitrary original paragraph"), ("box", ["text", 1, 2, 3])):
            report = deepcopy(self.report)
            row = next(r for r in report["observations"] if r["component_changed"])
            candidate = row["current_component"]["candidates"][0]
            if field == "box":
                candidate["binding"]["label_box"] = value
            else:
                candidate[field] = value
            with self.assertRaises(ValueError):
                regression.public_index(seal(report))

    def test_public_permissions_and_cash_promotion_rejected(self):
        for k, v in (("screening_input_exported", True), ("diagnostic_available_at", "2026-09-30"), ("pit_admitted_observation_count", False)):
            with self.assertRaises(ValueError):
                regression.public_index(seal({**deepcopy(self.report), k: v}))
        report = deepcopy(self.report)
        report["observations"][0]["current_component"]["full_lease_cash_not_already_deducted"] = "1"
        with self.assertRaises(ValueError):
            regression.public_index(seal(report))

    def test_partial_commit_bad_label_and_unknown_scope_keys_rejected(self):
        for k, v in (("implementation_base_commit", "9187e28"), ("continuation_label", "租赁负债"), ("extra", 1), ("as_of", "2026-02-30")):
            with self.assertRaises(ValueError):
                regression.read_plan(canonical_bytes({**deepcopy(self.plan), k: v}))

    def test_parent_or_parser_hash_drift_rejected(self):
        for name in regression.REFS:
            plan = deepcopy(self.plan)
            plan[name]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                regression.build_regression(canonical_bytes(plan))
        plan = deepcopy(self.plan)
        plan["expected_parser_code_sha256"]["scripts/parsing/annual_report_parser.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "implementation drift"):
            regression.build_regression(canonical_bytes(plan))

    def test_CLI_no_overwrite_and_check_no_write(self):
        args = ["--scope", str(SCOPE), "--output", str(PRIVATE), "--public-index", str(PUBLIC)]
        with patch.object(regression, "build_regression", return_value=self.report):
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                regression.main(args)
            self.assertIsNone(regression.main(args + ["--check"]))

    def test_private_output_outside_storage_rejected(self):
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            regression.main(["--scope", str(SCOPE), "--output", str(ROOT / "docs/data-pilots/full.json"), "--public-index", str(PUBLIC)])


if __name__ == "__main__":
    unittest.main()
