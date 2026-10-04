"""Exact same-page payment aliases; no new complete-cash/PIT semantics."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.parsing.annual_report_parser import LEASE_LABELS, _lease, parse_annual
from scripts.parsing.generic_extractor import PDFCache, Page, ParsedPDF, Word
from scripts.pilots import build_annual_lease_label_regression as regression
from scripts.pilots.replay_frozen_annual_indexed_pilot import replay_indexed_pilot, validated_report
from scripts.screening.contracts import canonical_bytes, content_hash, load_request

ROOT = regression.ROOT
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-lease-label-regression-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-lease-label-fix-2026-10-04-v1/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-lease-label-fix-2026-10-04-v1/evidence-index.json"
SOURCE = {"security_id": "sh.600001", "issuer": "测试股份有限公司", "fiscal_year": 2024,
          "version": "original", "pdf_sha256": "a" * 64}


def word(text, y, x=30, right=270):
    return Word(text, (x, y, right, y + 10))


def fixture(label="支付租赁款", *, context="支付的其他与筹资活动有关的现金", unit="单位：元",
            current="123.45", comparative="98.76", rotation=0):
    words = [word("七、合并财务报表项目注释", 20), word(context, 50), word(unit, 75),
             word("项目", 100, right=65), word("本期发生额", 100, 330, 410), word("上期发生额", 100, 470, 550),
             word(label, 135)]
    if current is not None:
        words.append(word(current, 135, 330, 410))
    if comparative is not None:
        words.append(word(comparative, 135, 470, 550))
    words.append(word("十八、母公司财务报表主要项目注释", 230))
    return pdf_from(words, rotation=rotation)


def pdf_from(words, *, rotation=0):
    words = tuple(words)
    return ParsedPDF("a" * 64, "synthetic", "b" * 64,
                     (Page(1, 600, 800, rotation, "\n".join(w.text for w in words), words),))


def changed(pdf, predicate, transform):
    page = pdf.pages[0]
    words = tuple(transform(w) if predicate(w) else w for w in page.words)
    return replace(pdf, pages=(replace(page, words=words, text="\n".join(w.text for w in words)),))


def seal(report):
    report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
    return report


class LeaseAliasGuardTests(unittest.TestCase):
    def observe(self, pdf=None):
        return _lease(fixture() if pdf is None else pdf, SOURCE)

    def assert_unknown(self, observation):
        self.assertIsNone(observation["observed_value_cny"])

    def test_exact_five_label_whitelist(self):
        self.assertEqual(LEASE_LABELS, ("偿还租赁负债支付的金额", "租赁支付的现金", *regression.ADDED))

    def test_three_new_same_page_labels_both_columns_and_binding(self):
        for label in regression.ADDED:
            with self.subTest(label=label):
                observed = self.observe(fixture(label))
                self.assertEqual(observed["observed_value_cny"], "123.45")
                self.assertEqual(observed["comparative_not_target_value_cny"], "98.76")
                row = observed["candidates"][0]
                self.assertEqual(row["source_label"], label)
                self.assertEqual(row["classification_evidence"]["classification"], "FINANCING_PAYMENT")
                for name in ("security_id", "issuer", "fiscal_year"):
                    self.assertEqual(row["binding"][name], SOURCE[name])
                self.assertEqual(row["binding"]["document_sha256"], "a" * 64)
                self.assertEqual(row["binding"]["physical_page"], 1)
                self.assertFalse(row["binding"]["pit_admitted"])
                self.assertFalse(observed["is_complete_lease_cash"])
                self.assertIsNone(observed["full_lease_cash_not_already_deducted"])

    def test_existing_two_labels_remain_supported(self):
        for label in LEASE_LABELS[:2]:
            self.assertEqual(self.observe(fixture(label))["observed_value_cny"], "123.45")

    def test_expense_not_payment_alias(self):
        for label in ("租赁费用", "长期租赁费用", "短期租赁费用", "租赁负债利息费用"):
            self.assert_unknown(self.observe(fixture(label)))

    def test_receipts_lessor_and_sale_leaseback_not_payment_aliases(self):
        for label in ("收到租金", "收到租赁款", "租赁收入", "售后租回交易现金流入"):
            self.assert_unknown(self.observe(fixture(label)))

    def test_bare_total_and_other_payment_labels_not_extended(self):
        for label in ("租赁负债", "与租赁相关的现金流出总额", "偿还租赁负债款",
                      "偿还租赁负债本金和利息所支付的现金"):
            self.assert_unknown(self.observe(fixture(label)))

    def test_partial_conditional_labels_not_fuzzy_matched(self):
        for label in ("支付租赁", "如支付租赁款", "未支付租赁款", "支付租赁款。", "应付租赁款"):
            self.assert_unknown(self.observe(fixture(label)))

    def test_operating_investing_and_receiving_contexts_not_financing_payment(self):
        for context in ("支付的其他与经营活动有关的现金", "支付的其他与投资活动有关的现金",
                        "收到的其他与筹资活动有关的现金", "与筹资活动有关的现金"):
            self.assert_unknown(self.observe(fixture(context=context)))

    def test_nearest_non_financing_context_cannot_be_bypassed(self):
        pdf = fixture()
        words = (*pdf.pages[0].words, word("支付的其他与经营活动有关的现金", 125))
        self.assert_unknown(self.observe(pdf_from(words)))

    def test_missing_context_not_inferred_from_label(self):
        pdf = fixture()
        words = tuple(w for w in pdf.pages[0].words if "与筹资活动" not in w.text)
        self.assert_unknown(self.observe(pdf_from(words)))

    def test_mother_company_note_label_not_admitted(self):
        pdf = changed(fixture(), lambda w: "母公司财务" in w.text,
                      lambda w: replace(w, box=(30, 120, 270, 130)))
        self.assert_unknown(self.observe(pdf))

    def test_label_before_consolidated_notes_not_admitted(self):
        pdf = changed(fixture(), lambda w: "合并财务" in w.text,
                      lambda w: replace(w, box=(30, 160, 270, 170)))
        self.assert_unknown(self.observe(pdf))

    def test_missing_or_duplicate_notes_scope_unknown(self):
        pdf = fixture()
        for words in (tuple(w for w in pdf.pages[0].words if "合并财务" not in w.text),
                      (*pdf.pages[0].words, word("七、合并财务报表项目注释", 35)),
                      (*pdf.pages[0].words, word("十八、母公司财务报表主要项目注释", 260))):
            self.assert_unknown(self.observe(pdf_from(words)))

    def test_context_on_previous_page_not_joined(self):
        pdf = fixture()
        original = pdf.pages[0]
        selected = tuple(w for w in original.words if w.y < 60)
        tail = tuple(w for w in original.words if w.y >= 60)
        split = replace(pdf, pages=(replace(original, words=selected, text=""),
                                    replace(original, number=2, words=tail, text="")))
        self.assert_unknown(self.observe(split))

    def test_header_on_previous_page_not_joined(self):
        pdf = fixture()
        original = pdf.pages[0]
        head = tuple(w for w in original.words if w.y < 130)
        tail = tuple(w for w in original.words if w.y >= 130)
        split = replace(pdf, pages=(replace(original, words=head, text=""),
                                    replace(original, number=2, words=tail, text="")))
        self.assert_unknown(self.observe(split))

    def test_unknown_and_missing_unit_unknown(self):
        for unit in ("单位：千元", "单位：美元", "单位：未知"):
            self.assert_unknown(self.observe(fixture(unit=unit)))
        pdf = fixture()
        self.assert_unknown(self.observe(pdf_from(w for w in pdf.pages[0].words if "单位" not in w.text)))

    def test_supported_unit_is_converted_not_assumed_one_yuan(self):
        observation = self.observe(fixture(unit="单位：万元"))
        self.assertEqual(observation["observed_value_cny"], "1234500.00")
        self.assertEqual(observation["candidates"][0]["binding"]["table_header"]["unit_multiplier"], 10000)

    def test_wrong_year_and_swapped_period_headers_not_used(self):
        for text in ("2023年度", "2024年度", "上期发生额"):
            pdf = changed(fixture(), lambda w: w.text == "本期发生额", lambda w: replace(w, text=text))
            self.assert_unknown(self.observe(pdf))

    def test_unknown_extra_amount_column_not_ignored(self):
        pdf = fixture()
        self.assert_unknown(self.observe(pdf_from((*pdf.pages[0].words, word("2022年度", 100, 175, 220)))))

    def test_invalid_nearest_header_not_bypassed(self):
        pdf = fixture()
        words = (*pdf.pages[0].words, word("项目", 120, right=65), word("2023年度", 120, 330, 410),
                 word("2022年度", 120, 470, 550))
        self.assert_unknown(self.observe(pdf_from(words)))

    def test_duplicate_payment_rows_not_added(self):
        pdf = fixture()
        duplicate = (word("支付租赁款", 180), word("100", 180, 330, 410), word("99", 180, 470, 550))
        result = self.observe(pdf_from((*pdf.pages[0].words, *duplicate)))
        self.assertEqual(result["state"], "AMBIGUOUS_LABEL")
        self.assert_unknown(result)

    def test_two_supported_different_labels_not_summed(self):
        pdf = fixture()
        another = (word("长期租赁付款", 180), word("123.45", 180, 330, 410), word("98.76", 180, 470, 550))
        self.assert_unknown(self.observe(pdf_from((*pdf.pages[0].words, *another))))

    def test_duplicate_amount_tokens_unknown(self):
        pdf = fixture()
        result = self.observe(pdf_from((*pdf.pages[0].words, word("12.00", 135, 310, 325))))
        self.assert_unknown(result)
        self.assertEqual(result["candidates"][0]["current"]["state"], "AMBIGUOUS_CELL")

    def test_column_boundary_crossing_unknown_not_rounded_into_column(self):
        pdf = changed(fixture(), lambda w: w.text == "123.45", lambda w: replace(w, box=(430, 135, 445, 145)))
        observation = self.observe(pdf)
        self.assert_unknown(observation)
        self.assertEqual(observation["candidates"][0]["current"]["state"], "COLUMN_EDGE_AMBIGUOUS")

    def test_clipped_amount_not_parseable_number(self):
        pdf = changed(fixture(), lambda w: w.text == "123.45", lambda w: replace(w, box=(330, -2, 410, 282)))
        self.assert_unknown(self.observe(pdf))

    def test_rotated_page_not_admitted(self):
        self.assert_unknown(self.observe(fixture(rotation=90)))

    def test_clipped_header_and_context_not_admitted(self):
        for label in ("本期发生额", "支付的其他与筹资活动有关的现金"):
            pdf = changed(fixture(), lambda w: w.text == label, lambda w: replace(w, box=(30, w.box[1], 610, w.box[3])))
            self.assert_unknown(self.observe(pdf))

    def test_blank_dash_and_comparative_not_backfilled_as_current(self):
        for amount in (None, "—", "-"):
            observed = self.observe(fixture(current=amount))
            self.assert_unknown(observed)
            self.assertEqual(observed["comparative_not_target_value_cny"], "98.76")

    def test_unparseable_money_not_guessed(self):
        for amount in ("1e2", "NaN", "1/2", "(123.45)", "+123.45", "123.45元"):
            self.assert_unknown(self.observe(fixture(current=amount)))

    def test_negative_source_amount_retained_not_abs_or_netting(self):
        self.assertEqual(self.observe(fixture(current="-123.45"))["observed_value_cny"], "-123.45")

    def test_currency_block_does_not_execute_new_labels(self):
        pdf = fixture()
        cover = Page(1, 600, 800, 0, "测试股份有限公司 sh.600001 2024年年度报告", ())
        pdf = replace(pdf, pages=(cover, replace(pdf.pages[0], number=2)))
        result = parse_annual(pdf, SOURCE)
        self.assertIsNone(result["currency"])
        self.assertIsNone(result["lease_financing_component"]["observed_value_cny"])
        self.assertEqual(result["lease_financing_component"]["candidates"], [])

    def test_wrong_declared_year_issuer_or_source_hash_rejected(self):
        pdf = fixture()
        cover = Page(1, 600, 800, 0, "测试股份有限公司 sh.600001 2024年年度报告", ())
        pdf = replace(pdf, pages=(cover, replace(pdf.pages[0], number=2)))
        for source in ({**SOURCE, "fiscal_year": 2023}, {**SOURCE, "issuer": "其他股份有限公司"},
                       {**SOURCE, "security_id": "sh.600999"}, {**SOURCE, "pdf_sha256": "0" * 64}):
            with self.assertRaises(ValueError):
                parse_annual(pdf, source)


class LeaseRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope_raw = SCOPE.read_bytes()
        cls.scope = json.loads(cls.scope_raw)
        with patch("requests.sessions.Session.request", side_effect=AssertionError("offline only")):
            cls.report = regression.build_regression(cls.scope_raw)
        cls.rows = {r["source"]["security_id"]: r for r in cls.report["observations"]}
        cls.index = regression.public_index(cls.report)

    def test_three_values_and_comparatives_bound_to_native_pages(self):
        expected = {"sh.600900": ("148332535.64", "126233185.12", 200, "支付租赁款"),
                    "sh.600276": ("47375294.97", "34334628.13", 220, "长期租赁付款"),
                    "sh.601012": ("191934806.52", "231203121.88", 246, "支付租赁负债")}
        cache = PDFCache()
        for security, (current, comparative, physical, label) in expected.items():
            row = self.rows[security]
            value, source = row["current_component"], row["source"]
            self.assertEqual((value["observed_value_cny"], value["comparative_not_target_value_cny"]), (current, comparative))
            candidate = value["candidates"][0]
            self.assertEqual(candidate["source_label"], label)
            bind = candidate["binding"]
            self.assertEqual((bind["physical_page"], bind["document_sha256"], bind["source_version"]),
                             (physical, source["pdf_sha256"], source["version"]))
            pdf = cache.parse((ROOT / source["pdf_path"]).read_bytes(), source["pdf_sha256"])
            native = {(w.text, w.box) for w in pdf.pages[physical - 1].words}
            self.assertIn((label, tuple(bind["label_box"])), native)
            for column in ("current", "comparative"):
                for text, box in zip(candidate[column]["raw_text"], candidate[column]["boxes"]):
                    self.assertIn((text, tuple(box)), native)
            self.assertEqual(bind["table_header"]["unit_multiplier"], 1)
            self.assertFalse(bind["pit_admitted"])

    def test_fourteen_pdfs_eleven_issuers_only_three_components_changed(self):
        self.assertEqual(self.report["counts"], {"issuers": 11, "PDF_versions": 14, "component_changed_PDFs": 3,
                                              "component_observed_PDFs": 8, "evaluated_unknown_PDFs": 2,
                                              "currency_blocked_PDFs": 4})
        self.assertEqual({r["source"]["security_id"] for r in self.report["observations"] if r["component_changed"]},
                         {"sh.600900", "sh.600276", "sh.601012"})

    def test_old_five_component_observations_unchanged(self):
        old_rows = [r for r in self.report["observations"] if r["baseline_component"]["observed_value_cny"] is not None]
        self.assertEqual(len(old_rows), 5)
        for row in old_rows:
            self.assertEqual(row["baseline_component"], row["current_component"])
            self.assertFalse(row["component_changed"])

    def test_unsupported_yutong_yili_and_currency_blocks_still_unknown(self):
        for security in ("sh.600066", "sh.600887", "sh.600585", "sh.600741", "sh.600309", "sz.000651"):
            row = self.rows[security]
            self.assertIsNone(row["current_component"]["observed_value_cny"])
            self.assertEqual(row["baseline_component"], row["current_component"])
        for security in ("sh.600585", "sh.600741", "sh.600309", "sz.000651"):
            self.assertEqual(self.rows[security]["existing_lease_branch"], "NOT_EVALUATED_CURRENCY_BLOCKED")
            self.assertEqual(self.rows[security]["current_component"]["candidates"], [])

    def test_main_fields_currency_audit_and_inventory_unchanged_from_pre_fix(self):
        cache = PDFCache()
        parser = "scripts/parsing/annual_report_parser.py"
        commit = self.scope["implementation_base_commit"]
        old_code = subprocess.check_output(["git", "show", f"{commit}:{parser}"], cwd=ROOT)
        self.assertEqual(hashlib.sha256(old_code).hexdigest(),
                         "82d67859ed8767f13a62f0a4fb985eab74ef0f431a12ddc868c6a7bb063bd842")
        # The five imported/support parser blobs are unchanged. Execute the actual
        # trusted frozen parser blob in memory; no checkout or saved-value fallback.
        for path in regression.SOURCE_PATHS:
            if path != parser:
                old = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
                self.assertEqual(old, (ROOT / path).read_bytes())
        namespace = {"__name__": "frozen_lease_label_baseline"}
        exec(compile(old_code, f"{commit}:{parser}", "exec"), namespace)
        for security in ("sh.600276", "sh.601012", "sh.600900"):
            source = self.rows[security]["source"]
            pdf = cache.parse((ROOT / source["pdf_path"]).read_bytes(), source["pdf_sha256"])
            old, current = namespace["parse_annual"](pdf, source), parse_annual(pdf, source)
            for bundle in (old, current):
                bundle.pop("lease_financing_component")
            self.assertEqual(current, old, security)

    def test_full_cash_FCF_PIT_and_permissions_still_unopened(self):
        for row in self.report["observations"]:
            value = row["current_component"]
            self.assertFalse(value["is_complete_lease_cash"])
            self.assertIsNone(value["full_lease_cash_not_already_deducted"])
            for key in ("full_lease_cash", "full_lease_cash_pit", "FCF_conservative"):
                self.assertIsNone(row[key])
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_frozen_parent_bytes_and_public_projection_preserved(self):
        for name in ("assessment_scope", "baseline_private_report", "baseline_public_index"):
            ref = self.scope[name]
            self.assertEqual(hashlib.sha256((ROOT / ref["path"]).read_bytes()).hexdigest(), ref["sha256"])

    def test_new_private_and_public_bytes_are_canonical_and_exact(self):
        self.assertEqual(PRIVATE.read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual(PUBLIC.read_bytes(), canonical_bytes(self.index) + b"\n")
        self.assertNotEqual(self.index["logical_content_hash"], self.report["logical_content_hash"])
        self.assertEqual(self.index["private_report_sha256"], hashlib.sha256(PRIVATE.read_bytes()).hexdigest())

    def test_scope_and_six_code_hashes_match_new_identity(self):
        self.assertEqual(regression.verify_code(self.scope, ROOT), self.report["manifest"]["parser_code_sha256"])
        self.assertEqual(self.report["scope_sha256"], hashlib.sha256(self.scope_raw).hexdigest())
        self.assertTrue(self.report["manifest"]["base_commit_is_not_new_parser_identity"])

    def test_unknown_scope_fields_bad_labels_and_partial_commit_rejected(self):
        for key, value in (("extra", True), ("added_exact_labels", ["租赁负债"]),
                           ("implementation_base_commit", "e023535"), ("as_of", "2026-02-30")):
            scope = deepcopy(self.scope)
            scope[key] = value
            with self.assertRaises(ValueError):
                regression.read_regression_scope(canonical_bytes(scope))

    def test_frozen_parent_hash_drift_rejected(self):
        scope = deepcopy(self.scope)
        scope["baseline_private_report"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            regression.build_regression(canonical_bytes(scope))

    def test_parser_code_drift_rejected_before_input_processing(self):
        scope = deepcopy(self.scope)
        scope["expected_parser_code_sha256"]["scripts/parsing/annual_report_parser.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "code or whitelist drift"):
            regression.build_regression(canonical_bytes(scope))

    def test_public_index_omits_both_original_text_channels(self):
        encoded = canonical_bytes(self.index)
        for key in (b'"text":', b'"native_text":', b'"words":', b'"raw_text":', b'"label_text":', b'"table_header":'):
            self.assertNotIn(key, encoded)
        for row in self.report["observations"]:
            for candidate in row["current_component"]["candidates"]:
                self.assertNotIn(candidate["classification_evidence"]["text"].encode("utf-8"), encoded)

    def test_unexpected_original_text_not_leaked_by_projection(self):
        report = deepcopy(self.report)
        report["complete_original_page"] = "private original text must stay local"
        report["observations"][0]["current_component"]["full_original_tokens"] = "private tokens"
        encoded = canonical_bytes(regression.public_index(seal(report)))
        self.assertNotIn(b"private original", encoded)
        self.assertNotIn(b"private tokens", encoded)

    def test_text_hidden_in_coordinate_rejected(self):
        report = deepcopy(self.report)
        row = next(r for r in report["observations"] if r["current_component"]["candidates"])
        row["current_component"]["candidates"][0]["binding"]["label_box"][0] = "private text"
        with self.assertRaisesRegex(ValueError, "coordinates"):
            regression.public_index(seal(report))

    def test_public_non_allowlisted_label_rejected(self):
        report = deepcopy(self.report)
        row = next(r for r in report["observations"] if r["current_component"]["candidates"])
        row["current_component"]["candidates"][0]["source_label"] = "arbitrary full paragraph"
        with self.assertRaisesRegex(ValueError, "allowlisted"):
            regression.public_index(seal(report))

    def test_public_hash_timing_or_permissions_drift_rejected(self):
        for key, value in (("logical_content_hash", "0" * 64), ("diagnostic_available_at", "2026-09-30"),
                           ("diagnostic_only", False), ("pit_admitted_observation_count", False),
                           ("pit_admitted_observation_count", 1), ("screening_input_exported", True)):
            report = deepcopy(self.report)
            report[key] = value
            if key != "logical_content_hash":
                seal(report)
            with self.assertRaises(ValueError):
                regression.public_index(report)

    def test_replayer_requires_full_commit_and_whitelisted_canonical_report(self):
        with self.assertRaisesRegex(ValueError, "full immutable"):
            replay_indexed_pilot(SCOPE, PRIVATE, PUBLIC, "e023535")
        with self.assertRaisesRegex(ValueError, "canonical indexed"):
            validated_report(canonical_bytes(self.report) + b"\n")

    def test_old_report_guard_rejects_noncanonical_hash_and_PIT_promotion(self):
        old = json.loads((ROOT / self.scope["baseline_private_report"]["path"]).read_bytes())
        self.assertEqual(validated_report(canonical_bytes(old) + b"\n"), old)
        for key, value in (("diagnostic_only", False), ("pit_admitted_observation_count", 1),
                           ("diagnostic_available_at", "2026-09-30"), ("production_reader_ready", True)):
            modified = seal({**deepcopy(old), key: value})
            with self.assertRaises(ValueError):
                validated_report(canonical_bytes(modified) + b"\n")
        with self.assertRaises(ValueError):
            validated_report(json.dumps(old).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
