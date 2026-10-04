"""Cross-page evidence candidates are not inherited cash classifications."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import unittest
from unittest.mock import patch

from scripts.parsing.generic_extractor import Page, ParsedPDF, Word
from scripts.pilots import assess_annual_lease_continuation as continuation
from scripts.screening.contracts import canonical_bytes, content_hash, load_request

ROOT = continuation.ROOT
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-lease-continuation-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-lease-continuation-2026-10-04-v2/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-lease-continuation-2026-10-04-v2/evidence-index.json"
SOURCE = {"security_id": "sh.600001", "issuer": "测试股份有限公司", "fiscal_year": 2024,
          "version": "original", "pdf_sha256": "a" * 64}
CASE = {"security_id": "sh.600001", "fiscal_year": 2024, "version": "original", "physical_pages": [1, 2],
        "role": "CROSS_PAGE_TARGET"}


def word(text, y, x=30, end=270):
    return Word(text, (x, y, end, y + 10))


def page(number, words):
    return Page(number, 600, 842, 0, "\n".join(w.text for w in words), tuple(words))


def fixture():
    first = page(1, (word("七、合并财务报表项目注释", 70), word("支付的其他与筹资活动有关的现金", 700),
                     word("√适用", 730), word("□不适用", 730, 290, 345), word("1/3", 798)))
    second = page(2, (word("单位：元", 75), word("项目", 100, end=65), word("本期发生额", 100, 330, 410),
                      word("上期发生额", 100, 470, 550), word("支付分红手续费", 125), word("1.23", 125, 330, 410),
                      word("0.50", 125, 470, 550), word(continuation.TARGET_LABEL, 150), word("10.00", 150, 330, 410),
                      word("5.00", 150, 470, 550), word("归还少数股东出资款", 175), word("3.00", 175, 330, 410),
                      word("合计", 200), word("14.23", 200, 330, 410), word("5.50", 200, 470, 550),
                      word("60、现金流量表补充资料", 240), word("2/3", 798)))
    third = page(3, (word("十八、母公司财务报表主要项目注释", 100),))
    return ParsedPDF("a" * 64, "synthetic", "b" * 64, (first, second, third))


def alter(pdf, number, transform):
    pages = list(pdf.pages)
    current = pages[number - 1]
    words = tuple(transform(list(current.words)))
    pages[number - 1] = replace(current, words=words, text="\n".join(w.text for w in words))
    return replace(pdf, pages=tuple(pages))


def seal(report):
    report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
    return report


class ContinuationConditionTests(unittest.TestCase):
    def observe(self, pdf=None):
        return continuation.inspect_case(fixture() if pdf is None else pdf, SOURCE, CASE)

    def assert_unknown_condition(self, pdf, name):
        result = self.observe(pdf)
        self.assertFalse(result["observed_guards"][name])
        self.assertEqual(result["state"], "CONTINUATION_CONDITIONS_NOT_CLOSED")
        self.assertIsNone(result["rule_input"])

    def test_same_pdf_adjacent_title_and_new_table_only_observe_conditions(self):
        case = self.observe()
        self.assertEqual(case["state"], "OBSERVED_CONTINUATION_CONDITIONS_NOT_CERTIFIED")
        self.assertTrue(all(case["observed_guards"].values()))
        self.assertEqual(case["row_amount_observations"]["current"]["value_cny"], "10.00")
        self.assertFalse(case["source_continuation_certified"])
        self.assertFalse(case["cash_classification_certified"])
        self.assertIsNone(case["rule_input"])

    def test_title_after_operating_or_receiving_cash_not_financing_payment(self):
        for heading in ("支付的其他与经营活动有关的现金", "支付的其他与投资活动有关的现金",
                        "收到的其他与筹资活动有关的现金"):
            pdf = alter(fixture(), 1, lambda ws: [replace(w, text=heading) if "与筹资活动" in w.text else w for w in ws])
            self.assert_unknown_condition(pdf, "unique_previous_page_financing_payment_heading")

    def test_duplicate_last_cash_heading_not_unique(self):
        pdf = alter(fixture(), 1, lambda ws: ws + [word("支付的其他与筹资活动有关的现金", 700, 285, 580)])
        self.assert_unknown_condition(pdf, "unique_previous_page_financing_payment_heading")

    def test_missing_previous_heading_not_borrowed_from_two_pages_back(self):
        pdf = alter(fixture(), 1, lambda ws: [w for w in ws if "与筹资活动" not in w.text])
        self.assert_unknown_condition(pdf, "unique_previous_page_financing_payment_heading")

    def test_intervening_paragraph_not_deleted(self):
        pdf = alter(fixture(), 1, lambda ws: ws + [word("未知的新事项说明", 760)])
        self.assert_unknown_condition(pdf, "only_applicability_after_heading")

    def test_new_same_page_cash_context_prevents_inheritance(self):
        pdf = alter(fixture(), 2, lambda ws: ws + [word("收到的其他与筹资活动有关的现金", 65)])
        self.assert_unknown_condition(pdf, "no_same_page_competing_cash_context")

    def test_nonadjacent_physical_page_identity_rejected(self):
        pdf = fixture()
        pdf = replace(pdf, pages=(pdf.pages[0], replace(pdf.pages[1], number=3), pdf.pages[2]))
        with self.assertRaisesRegex(ValueError, "physical page order"):
            self.observe(pdf)

    def test_rotated_or_resized_page_does_not_close_conditions(self):
        pdf = fixture()
        for change in ({"rotation": 90}, {"width": 610}, {"height": 852}):
            current = replace(pdf.pages[1], **change)
            self.assert_unknown_condition(replace(pdf, pages=(pdf.pages[0], current, pdf.pages[2])), "same_unrotated_dimensions")

    def test_unknown_unit_not_inherited_from_previous_page(self):
        pdf = alter(fixture(), 1, lambda ws: ws + [word("单位：元", 650)])
        pdf = alter(pdf, 2, lambda ws: [replace(w, text="单位：千元") if w.text == "单位：元" else w for w in ws])
        self.assert_unknown_condition(pdf, "same_page_supported_unit_and_two_columns")

    def test_no_same_page_unit_not_assumed(self):
        pdf = alter(fixture(), 2, lambda ws: [w for w in ws if w.text != "单位：元"])
        self.assert_unknown_condition(pdf, "same_page_supported_unit_and_two_columns")

    def test_wrong_year_or_swapped_header_not_supported(self):
        for label in ("2023年度", "上期发生额"):
            pdf = alter(fixture(), 2, lambda ws: [replace(w, text=label) if w.text == "本期发生额" else w for w in ws])
            self.assert_unknown_condition(pdf, "same_page_supported_unit_and_two_columns")

    def test_extra_amount_column_not_discarded(self):
        pdf = alter(fixture(), 2, lambda ws: ws + [word("2022年度", 100, 180, 240)])
        self.assert_unknown_condition(pdf, "same_page_supported_unit_and_two_columns")

    def test_previous_valid_table_not_bypassed_for_second_table(self):
        pdf = alter(fixture(), 2, lambda ws: ws + [word("项目", 65, end=65)])
        self.assert_unknown_condition(pdf, "first_same_page_table_header")

    def test_new_note_before_table_prevents_continuation_claim(self):
        pdf = alter(fixture(), 2, lambda ws: ws + [word("60、其他新附注", 65)])
        self.assert_unknown_condition(pdf, "next_note_after_target_and_header")

    def test_duplicate_or_split_native_target_label_not_joined(self):
        duplicate = alter(fixture(), 2, lambda ws: ws + [word(continuation.TARGET_LABEL, 215)])
        self.assert_unknown_condition(duplicate, "unique_complete_target_token")
        split = alter(fixture(), 2, lambda ws: [replace(w, text="偿还租赁负债本金和利息") if w.text == continuation.TARGET_LABEL else w for w in ws]
                      + [word("所支付的现金", 162)])
        self.assert_unknown_condition(split, "unique_complete_target_token")

    def test_clipped_native_target_not_complete(self):
        pdf = alter(fixture(), 2, lambda ws: [replace(w, box=(30, 150, 610, 160)) if w.text == continuation.TARGET_LABEL else w for w in ws])
        self.assert_unknown_condition(pdf, "unique_complete_target_token")

    def test_column_edge_and_duplicate_amount_not_guessed(self):
        pdf = alter(fixture(), 2, lambda ws: [replace(w, box=(430, 150, 445, 160)) if w.text == "10.00" else w for w in ws])
        self.assert_unknown_condition(pdf, "two_unambiguous_numeric_row_cells")
        pdf = alter(fixture(), 2, lambda ws: ws + [word("10.00", 150, 300, 320)])
        self.assert_unknown_condition(pdf, "two_unambiguous_numeric_row_cells")

    def test_parent_notes_and_duplicate_scope_not_combined(self):
        early_end = alter(fixture(), 1, lambda ws: ws + [word("十八、母公司财务报表主要项目注释", 680)])
        self.assert_unknown_condition(early_end, "inside_explicit_consolidated_note_interval")
        duplicate = alter(fixture(), 1, lambda ws: ws + [word("七、合并财务报表项目注释", 90)])
        self.assert_unknown_condition(duplicate, "inside_explicit_consolidated_note_interval")

    def test_total_reconciles_only_complete_current_column(self):
        pdf = fixture()
        result = continuation.target_table_reconciliation(pdf, self.observe(pdf))
        self.assertEqual(result["checks"]["current"], {"state": "SOURCE_ARITHMETIC_RECONCILED", "component_sum_cny": "14.23", "difference_cny": "0.00"})
        self.assertEqual(result["checks"]["comparative"]["state"], "UNKNOWN_INCOMPLETE_COMPONENTS")
        self.assertEqual(result["components"][2]["cells"]["comparative"]["state"], "BLANK_NOT_ZERO")
        self.assertIsNone(result["components"][2]["cells"]["comparative"]["value_cny"])
        self.assertFalse(result["blank_filled_as_zero"])

    def test_negative_source_amount_is_retained_not_absolute_value(self):
        pdf = alter(fixture(), 2, lambda ws: [replace(w, text="-10.00") if w.text == "10.00" else w for w in ws])
        self.assertEqual(self.observe(pdf)["row_amount_observations"]["current"]["value_cny"], "-10.00")

    def test_inventory_exact_tokens_excludes_bare_liability_and_expense(self):
        pdf = alter(fixture(), 2, lambda ws: ws + [word("租赁负债", 280), word("租赁费用", 300), word("支付 租赁款", 320)])
        locations = continuation.payment_inventory(pdf)
        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0]["context_state"], "PREVIOUS_PAGE_CONTEXT_CANDIDATE_NOT_LINKED")
        self.assertFalse(locations[0]["classification_certified"])

    def test_inventory_does_not_search_two_pages_back(self):
        pdf = fixture()
        middle = page(2, (word("无分类标题", 70),))
        target = replace(pdf.pages[1], number=3)
        pdf = replace(pdf, pages=(pdf.pages[0], middle, target, replace(pdf.pages[2], number=4)))
        location = continuation.payment_inventory(pdf)[0]
        self.assertEqual(location["context_state"], "NO_SAME_OR_PREVIOUS_PAGE_CONTEXT_IDENTIFIED")


class ContinuationRealEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_scope = SCOPE.read_bytes()
        cls.plan = json.loads(cls.raw_scope)
        with patch("requests.sessions.Session.request", side_effect=AssertionError("offline only")):
            cls.report = continuation.build_assessment(cls.raw_scope)
        cls.index = continuation.public_index(cls.report)
        cls.cases = {c["source"]["security_id"]: c for c in cls.report["selected_cases"]}

    def test_fourteen_pdf_inventory_only_one_previous_page_candidate(self):
        self.assertEqual(self.report["counts"], {"issuers": 11, "PDF_versions": 14, "native_payment_label_locations": 12,
                                              "previous_page_context_candidates_not_linked": 1, "selected_cases": 2,
                                              "selected_pages": 3, "selected_cross_page_conditions_observed": 1})
        selected = [(row["source"]["security_id"], loc["physical_page"]) for row in self.report["observations"]
                    for loc in row["payment_label_locations_not_cash_certification"]
                    if loc["context_state"] == "PREVIOUS_PAGE_CONTEXT_CANDIDATE_NOT_LINKED"]
        self.assertEqual(selected, [("sh.600066", 126)])

    def test_yutong_title_page_and_amount_table_are_distinct_native_evidence(self):
        case = self.cases["sh.600066"]
        self.assertEqual((case["heading_page"], case["target_page"]), (125, 126))
        self.assertTrue(all(case["observed_guards"].values()))
        self.assertEqual(case["table_header_observation"]["physical_page"], 126)
        self.assertEqual(case["table_header_observation"]["unit_multiplier"], 1)
        self.assertEqual([c["value_cny"] for c in case["row_amount_observations"].values()], ["14990744.76", "8061350.60"])
        self.assertEqual(case["target_label"], continuation.TARGET_LABEL)
        self.assertEqual(len([w for w in case["target_row_native_words"] if w["text"] == continuation.TARGET_LABEL]), 1)

    def test_yutong_blank_comparative_not_reverse_engineered_to_zero(self):
        table = self.cases["sh.600066"]["target_table_source_reconciliation"]
        self.assertEqual(table["checks"]["current"]["component_sum_cny"], "17735481.08")
        self.assertEqual(table["checks"]["current"]["difference_cny"], "0.00")
        self.assertEqual(table["checks"]["comparative"]["state"], "UNKNOWN_INCOMPLETE_COMPONENTS")
        self.assertIsNone(table["components"][2]["cells"]["comparative"]["value_cny"])
        self.assertEqual(table["total_native_cells"]["comparative"]["value_cny"], "9282499.82")

    def test_same_label_control_is_not_cross_page_or_forced_CNY(self):
        control = self.cases["sh.600585"]
        self.assertEqual(control["state"], "SAME_PAGE_CONTROL_NOT_CONTINUATION")
        self.assertIsNone(control["unchanged_parser_currency"])
        self.assertEqual(control["row_amount_observations"]["current"]["state"], "HEADER_OR_UNIT_UNSUPPORTED")
        self.assertIsNone(control["row_amount_observations"]["current"]["value_cny"])

    def test_selected_words_are_bound_to_saved_source_pages_and_sha(self):
        for case in self.report["selected_cases"]:
            source = case["source"]
            pages = {p["physical_page"]: p for p in case["selected_pages"]}
            for p in pages.values():
                self.assertEqual(p["document_sha256"], source["pdf_sha256"])
                self.assertEqual(hashlib.sha256(p["native_text"].encode("utf-8")).hexdigest(), p["native_text_sha256"])
            native = {(w["text"], tuple(w["box"])) for p in pages.values() for w in p["native_words"]}
            for field in ("target_row_native_words", "heading_native_words", "next_note_native_words"):
                for w in case[field]:
                    self.assertIn((w["text"], tuple(w["box"])), native)

    def test_all_fourteen_parser_lease_components_unchanged_from_frozen_parent(self):
        parent = json.loads((ROOT / self.plan["baseline_private_report"]["path"]).read_bytes())
        previous = {continuation.source_key(r["source"]): r for r in parent["observations"]}
        for row in self.report["observations"]:
            old = previous[continuation.source_key(row["source"])]
            self.assertEqual(row["currency"], old["currency"])
            self.assertEqual(row["unchanged_lease_component"], old["current_component"])

    def test_parser_bytes_match_full_frozen_commit_before_and_after(self):
        continuation.verify_parser(self.plan)
        self.assertFalse(self.report["parser_modified"])
        self.assertEqual(self.report["manifest"]["parser_commit"], "526fb38e65d6002c5663ad6a40ccb9a9ead4741f")

    def test_full_lease_PIT_and_rule_permissions_not_promoted(self):
        for case in self.cases.values():
            self.assertFalse(case["source_continuation_certified"])
            self.assertFalse(case["cash_classification_certified"])
            self.assertIsNone(case["rule_input"])
            self.assertIsNone(case["full_lease_cash"])
            self.assertIsNone(case["unchanged_parser_lease_component_value_cny"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertIsNone(self.report["diagnostic_available_at"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_new_artifacts_canonical_separate_identity(self):
        self.assertEqual(PRIVATE.read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual(PUBLIC.read_bytes(), canonical_bytes(self.index) + b"\n")
        self.assertNotEqual(self.index["logical_content_hash"], self.report["logical_content_hash"])
        self.assertEqual(self.index["private_report_sha256"], hashlib.sha256(PRIVATE.read_bytes()).hexdigest())

    def test_public_projection_removes_both_full_text_channels_and_context(self):
        encoded = canonical_bytes(self.index)
        for key in (b'"native_text":', b'"native_words":', b'"raw_text":', b'"text":', b'"table_header_observation":'):
            self.assertNotIn(key, encoded)
        case = self.cases["sh.600066"]
        self.assertNotIn(case["heading_native_words"][0]["text"].encode("utf-8"), encoded)
        self.assertNotIn(case["next_note_native_words"][0]["text"].encode("utf-8"), encoded)

    def test_extra_original_text_not_copied_to_public_index(self):
        report = deepcopy(self.report)
        report["whole_original_page"] = "private original page text"
        report["selected_cases"][0]["new_full_paragraph"] = "private original paragraph"
        encoded = canonical_bytes(continuation.public_index(seal(report)))
        self.assertNotIn(b"private original", encoded)

    def test_text_coordinate_and_unknown_label_rejected(self):
        for field, value in (("label_box", ["private words", 1, 2, 3]), ("label", "arbitrary full paragraph")):
            report = deepcopy(self.report)
            row = next(r for r in report["observations"] if r["payment_label_locations_not_cash_certification"])
            row["payment_label_locations_not_cash_certification"][0][field] = value
            with self.assertRaises(ValueError):
                continuation.public_index(seal(report))

    def test_hash_clock_flags_and_nonboolean_guards_rejected(self):
        for key, value in (("parser_modified", True), ("pit_admitted_observation_count", False),
                           ("pit_admitted_observation_count", 1), ("diagnostic_available_at", "2026-09-30"),
                           ("screening_input_exported", True)):
            report = seal({**deepcopy(self.report), key: value})
            with self.assertRaises(ValueError):
                continuation.public_index(report)
        report = deepcopy(self.report)
        report["selected_cases"][0]["observed_guards"]["adjacent_pages"] = "original paragraph"
        with self.assertRaises(ValueError):
            continuation.public_index(seal(report))

    def test_case_semantic_promotion_not_silently_cleared_by_projection(self):
        for key, value in (("rule_input", {}), ("source_continuation_certified", True), ("full_lease_cash", "10.00")):
            report = deepcopy(self.report)
            report["selected_cases"][0][key] = value
            with self.assertRaises(ValueError):
                continuation.public_index(seal(report))

    def test_scope_rejects_expanded_search_partial_commit_and_nonadjacent_pages(self):
        for key, value in (("extra", True), ("parser_commit", "526fb38")):
            plan = deepcopy(self.plan)
            plan[key] = value
            with self.assertRaises(ValueError):
                continuation.read_plan(canonical_bytes(plan))
        for limit in (2, True):
            plan = deepcopy(self.plan)
            plan["search"]["previous_page_limit"] = limit
            with self.assertRaises(ValueError):
                continuation.read_plan(canonical_bytes(plan))
        plan = deepcopy(self.plan)
        plan["review_cases"][0]["physical_pages"] = [125, 127]
        with self.assertRaises(ValueError):
            continuation.read_plan(canonical_bytes(plan))

    def test_parent_and_code_hash_drift_rejected(self):
        for ref in ("baseline_private_report", "baseline_public_index", "input_refs_scope"):
            plan = deepcopy(self.plan)
            plan[ref]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                continuation.build_assessment(canonical_bytes(plan))
        plan = deepcopy(self.plan)
        plan["parser_code_sha256"]["scripts/parsing/annual_report_parser.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "parser drift"):
            continuation.build_assessment(canonical_bytes(plan))

    def test_CLI_refuses_overwrite_and_check_mismatch_without_writing(self):
        argv = ["--scope", str(SCOPE), "--output", str(PRIVATE), "--public-index", str(PUBLIC)]
        with patch.object(continuation, "build_assessment", return_value=self.report):
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                continuation.main(argv)
            modified = seal({**deepcopy(self.report), "method": "changed"})
            with patch.object(continuation, "build_assessment", return_value=modified):
                with self.assertRaisesRegex(ValueError, "byte mismatch"):
                    continuation.main(argv + ["--check"])

    def test_CLI_full_original_output_outside_storage_rejected(self):
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            continuation.main(["--scope", str(SCOPE), "--output", str(ROOT / "docs/data-pilots/not-permitted-full.json"),
                               "--public-index", str(PUBLIC)])


if __name__ == "__main__":
    unittest.main()
