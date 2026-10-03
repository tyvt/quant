"""Bounded raw-block extraction, semantic non-promotion, and safe publication."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts.parsing.annual_report_parser import _audit_narrative_block, _audit
from scripts.parsing.generic_extractor import Page, Word, ParsedPDF, PDFCache
from scripts.pilots.build_annual_audit_blocks import build_blocks, ROOT
from scripts.pilots.export_annual_audit_index import public_index
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


SUCCESS = "OBSERVED_NARRATIVE_OPINION_BLOCK_NOT_TYPE"


class NarrativeAuditBlockTests(unittest.TestCase):
    def setUp(self):
        self.source = {"security_id": "sh.600001", "issuer": "测试股份有限公司", "fiscal_year": 2024,
                       "version": "original", "pdf_sha256": "a" * 64}
        self.rows = ["审计报告", "审字[2025]001号", "一、审计意见",
                     "我们审计了测试股份有限公司的财务报表，包括2024年12月31日的合并及公司资产负债表。",
                     "我们认为，后附的财务报表在所有重大方面公允反映了财务状况。",
                     "二、形成审计意见的基础", "责任条件条款不在意见块内。"]

    def pdf(self, rows=None, *, rotation=0, boxes=None):
        rows = self.rows if rows is None else rows
        words = tuple(Word(text, (20, 20 + i * 20, 580, 30 + i * 20) if boxes is None else boxes[i])
                      for i, text in enumerate(rows))
        return ParsedPDF("a" * 64, "test", "b" * 64,
                         (Page(1, 600, 800, rotation, "\n".join(rows), words),))

    def observe(self, rows=None, **kwargs):
        return _audit_narrative_block(self.pdf(rows, **kwargs), self.source)

    def assert_unknown(self, result):
        self.assertNotEqual(result["state"], SUCCESS)
        self.assertEqual(result["lines"], [])
        self.assertIsNone(result["opinion_type_inferred"])
        self.assertIsNone(result["audit_gate_result"])

    def test_unique_complete_same_page_raw_block(self):
        block = self.observe()
        self.assertEqual(block["state"], SUCCESS)
        self.assertEqual([r["words"][0]["text"] for r in block["lines"]], self.rows[3:5])
        self.assertEqual(block["binding"]["object_line_indices"], [0])
        self.assertEqual(block["binding"]["opinion_line_indices"], [1])

    def test_wrong_source_PDF_hash_rejected_before_extraction(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            _audit_narrative_block(replace(self.pdf(), sha256="0" * 64), self.source)

    def test_words_coordinates_are_not_normalized(self):
        rows = self.rows.copy()
        rows[4] = rows[4].replace("我们认为", "我们 认为")
        block = self.observe(rows)
        self.assertEqual(block["state"], SUCCESS)
        self.assertEqual(block["lines"][1]["words"][0]["text"], rows[4])
        self.assertEqual(block["lines"][1]["words"][0]["box"], [20, 100, 580, 110])

    def test_after_attached_issuer_and_parent_scope_supported(self):
        rows = self.rows.copy()
        rows[3] = rows[3].replace("审计了", "审计了后附的").replace("合并及公司", "合并及母公司")
        self.assertEqual(self.observe(rows)["state"], SUCCESS)

    def test_legacy_raw_type_stays_unknown_for_narrative(self):
        audit = _audit(self.pdf(), self.source)
        self.assertIsNone(audit["raw_opinion_type"])
        self.assertEqual(audit["state"], "UNKNOWN")
        self.assertEqual(audit["narrative_opinion_block"]["state"], SUCCESS)

    def test_wrong_issuer_not_rescued_by_name_elsewhere(self):
        rows = self.rows.copy()
        rows[3] = rows[3].replace("测试股份有限公司", "其他股份有限公司")
        rows.insert(0, self.source["issuer"])
        self.assert_unknown(self.observe(rows))

    def test_issuer_prefix_collision_rejected(self):
        rows = self.rows.copy()
        rows[3] = rows[3].replace("测试股份有限公司", "测试股份有限公司关联公司")
        self.assert_unknown(self.observe(rows))

    def test_wrong_target_year_rejected(self):
        self.assert_unknown(self.observe([r.replace("2024年", "2023年") for r in self.rows]))

    def test_comparative_date_before_target_does_not_rescue(self):
        rows = self.rows.copy()
        rows[3] = rows[3].replace("2024年12月31日", "2023年12月31日以及2024年12月31日")
        self.assert_unknown(self.observe(rows))

    def test_missing_consolidated_object_rejected(self):
        self.assert_unknown(self.observe([r.replace("合并及公司", "公司") for r in self.rows]))

    def test_parenthesized_titles_not_silently_converted(self):
        rows = self.rows.copy()
        rows[2], rows[5] = "(一)审计意见", "(二)形成审计意见的基础"
        self.assert_unknown(self.observe(rows))

    def test_nested_structure_rejected(self):
        rows = self.rows.copy()
        rows.insert(3, "(一)我们审计的内容")
        self.assert_unknown(self.observe(rows))

    def test_duplicate_opinion_heading_rejected(self):
        self.assert_unknown(self.observe([self.rows[2]] + self.rows))

    def test_duplicate_basis_heading_rejected(self):
        self.assert_unknown(self.observe(self.rows + [self.rows[5]]))

    def test_missing_heading_rejected(self):
        self.assert_unknown(self.observe(self.rows[:5]))

    def test_titles_in_wrong_order_rejected(self):
        rows = self.rows.copy()
        rows[2], rows[5] = rows[5], rows[2]
        self.assert_unknown(self.observe(rows))

    def test_cross_page_pair_rejected(self):
        pdf = self.pdf()
        first = replace(pdf.pages[0], words=pdf.pages[0].words[:5])
        second = replace(pdf.pages[0], number=2, words=pdf.pages[0].words[5:])
        self.assert_unknown(_audit_narrative_block(replace(pdf, pages=(first, second)), self.source))

    def test_split_heading_not_joined_across_rows(self):
        rows = self.rows.copy()
        rows[2:3] = ["一、", "审计意见"]
        self.assert_unknown(self.observe(rows))

    def test_clipped_heading_rejected(self):
        rows = self.rows.copy()
        rows[5] = "二、形成审计意见的基"
        self.assert_unknown(self.observe(rows))

    def test_rotated_page_rejected(self):
        self.assert_unknown(self.observe(rotation=90))

    def test_outside_page_word_rejected(self):
        boxes = [(20, 20 + i * 20, 580, 30 + i * 20) for i in range(len(self.rows))]
        boxes[4] = (20, 100, 620, 110)
        self.assert_unknown(self.observe(boxes=boxes))

    def test_two_column_native_row_rejected(self):
        pdf = self.pdf()
        words = list(pdf.pages[0].words)
        words[4:5] = [Word("我们认为，", (20, 100, 90, 110)), Word("正文。", (180, 100, 230, 110))]
        self.assert_unknown(_audit_narrative_block(replace(pdf, pages=(replace(pdf.pages[0], words=tuple(words)),)), self.source))

    def test_overlapping_word_boxes_rejected(self):
        pdf = self.pdf()
        words = list(pdf.pages[0].words)
        words[4:5] = [Word("我们认为，", (20, 100, 100, 110)), Word("正文。", (80, 100, 200, 110))]
        self.assert_unknown(_audit_narrative_block(replace(pdf, pages=(replace(pdf.pages[0], words=tuple(words)),)), self.source))

    def test_truncated_object_sentence_rejected(self):
        rows = self.rows.copy()
        rows[3] = rows[3][:-1]
        self.assert_unknown(self.observe(rows))

    def test_truncated_opinion_sentence_rejected(self):
        rows = self.rows.copy()
        rows[4] = rows[4][:-1]
        self.assert_unknown(self.observe(rows))

    def test_missing_opinion_sentence_rejected(self):
        rows = self.rows.copy()
        rows[4] = "这里提到我们认为，但不是意见首句。"
        self.assert_unknown(self.observe(rows))

    def test_repeated_opinion_sentence_rejected(self):
        rows = self.rows.copy()
        rows.insert(5, rows[4])
        self.assert_unknown(self.observe(rows))

    def test_special_review_not_promoted_to_annual_audit(self):
        self.assert_unknown(self.observe(["会计差错更正专项审核报告"] + self.rows))

    def test_example_and_quoted_context_rejected(self):
        for prefix in ("示例", "引用", "例："):
            with self.subTest(prefix=prefix):
                self.assert_unknown(self.observe([prefix] + self.rows))

    def test_quoted_object_not_a_direct_object_sentence(self):
        rows = self.rows.copy()
        rows[3] = "“" + rows[3] + "”"
        self.assert_unknown(self.observe(rows))

    def test_negated_we_audited_not_a_direct_object_sentence(self):
        self.assert_unknown(self.observe([r.replace("我们审计了", "我们未审计") for r in self.rows]))

    def test_negative_opinion_remains_raw_and_unclassified(self):
        rows = self.rows.copy()
        rows[4] = "我们认为，财务报表未能公允反映财务状况。"
        result = self.observe(rows)
        self.assertEqual(result["state"], SUCCESS)
        self.assertIsNone(result["opinion_type_inferred"])
        self.assertIsNone(result["audit_gate_result"])

    def test_key_audit_matter_and_other_information_context_rejected(self):
        for prefix in ("关键审计事项", "其他信息"):
            with self.subTest(prefix=prefix):
                self.assert_unknown(self.observe([prefix] + self.rows))

    def test_conditional_going_concern_later_not_opinion_evidence(self):
        rows = self.rows + ["如果我们得出结论认为存在重大不确定性，应提请注意。"]
        block = self.observe(rows)
        self.assertEqual(block["state"], SUCCESS)
        self.assertFalse(block["whole_audit_report_reviewed"])
        self.assertNotIn("重大不确定性", json.dumps(block["lines"], ensure_ascii=False))
        self.assertIsNone(_audit(self.pdf(rows), self.source)["going_concern_uncertainty_pit"])

    def test_missing_report_number_does_not_invent_one(self):
        result = self.observe([self.rows[0]] + self.rows[2:])
        self.assertEqual(result["state"], SUCCESS)
        self.assertIsNone(result["report_number"])
        self.assertEqual(result["report_number_state"], "NOT_EVALUATED")

    def test_repeated_report_number_does_not_mean_latest(self):
        result = self.observe([self.rows[1]] + self.rows)
        self.assertEqual(result["state"], SUCCESS)
        self.assertFalse(result["latest_audit_version_verified"])

    def test_amended_version_reusing_audit_block_not_certified(self):
        source = {**self.source, "version": "amended"}
        block = _audit_narrative_block(self.pdf(), source)
        self.assertEqual(block["binding"]["version"], "amended")
        self.assertEqual(block["amended_whole_statement_audit_status"], "UNKNOWN")
        self.assertFalse(block["report_object_verified"])


class AuditBlockRealRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = ROOT / "docs/data-pilots/2026-10-04-annual-audit-assessment-scope.json"
        cls.path = ROOT / "storage/pilots/annual-audit-blocks-2026-10-04-v2/diagnostic-only.json"
        cls.raw = cls.path.read_bytes()
        cls.report = json.loads(cls.raw)
        cls.rows = cls.report["observations"]
        cls.old_path = ROOT / "docs/data-pilots/annual-audit-assessment-2026-10-04-v1/diagnostic-only.json"
        cls.old = json.loads(cls.old_path.read_bytes())

    def test_six_raw_blocks_two_unresolved_six_table_controls(self):
        self.assertEqual(self.report["counts"], {"issuers": 11, "PDF_versions": 14,
                         "legacy_raw_type_identified": 6, "narrative_raw_blocks_observed": 6,
                         "narrative_raw_blocks_unresolved": 2})

    def test_exact_six_physical_pages(self):
        actual = {r["source"]["security_id"]: r["audit_text_observation"]["narrative_opinion_block"]["physical_page"]
                  for r in self.rows if r["audit_text_observation"]["narrative_opinion_block"]["state"] == SUCCESS}
        self.assertEqual(actual, {"sh.600276": 139, "sh.600309": 75, "sh.600585": 97,
                                  "sh.600887": 83, "sh.600900": 85, "sh.601012": 111})

    def test_huayu_nested_and_yutong_variant_stay_unresolved(self):
        rows = {r["source"]["security_id"]: r for r in self.rows}
        self.assertEqual(rows["sh.600741"]["audit_text_observation"]["narrative_opinion_block"]["state"],
                         "NESTED_OR_OTHER_SECTION_UNSUPPORTED")
        self.assertEqual(rows["sh.600066"]["audit_text_observation"]["narrative_opinion_block"]["state"], "NOT_IDENTIFIED")

    def test_every_legacy_audit_field_unchanged(self):
        key = lambda r: (r["source"]["security_id"], r["source"]["fiscal_year"], r["source"]["version"])
        old = {key(r): r["legacy_audit_text_observation"] for r in self.old["observations"]}
        for row in self.rows:
            self.assertEqual({k: v for k, v in row["audit_text_observation"].items() if k != "narrative_opinion_block"}, old[key(row)])

    def test_raw_blocks_bind_native_word_text_and_geometry(self):
        cache = PDFCache()
        for row in self.rows:
            block = row["audit_text_observation"]["narrative_opinion_block"]
            if block["state"] != SUCCESS:
                continue
            source = row["source"]
            pdf = cache.parse((ROOT / source["pdf_path"]).read_bytes(), source["pdf_sha256"])
            page = pdf.pages[block["physical_page"] - 1]
            words = {(w.text, w.box) for w in page.words}
            for line in block["lines"]:
                for word in line["words"]:
                    self.assertIn((word["text"], tuple(word["box"])), words)
            self.assertEqual(block["binding"]["document_sha256"], pdf.sha256)

    def test_no_semantic_PIT_or_hard_gate_promotion(self):
        for row in self.rows:
            block = row["audit_text_observation"]["narrative_opinion_block"]
            for key in ("report_object_verified", "whole_audit_report_reviewed", "public_availability_verified", "latest_audit_version_verified"):
                self.assertFalse(block[key])
            self.assertIsNone(block["opinion_type_inferred"])
            self.assertIsNone(block["audit_gate_result"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertIsNone(self.report["diagnostic_available_at"])
        with self.assertRaises(ValueError):
            load_request(self.raw)

    def test_canonical_hash_and_offline_rebuild_are_exact(self):
        self.assertEqual(self.raw, canonical_bytes(self.report) + b"\n")
        self.assertEqual(self.report["logical_content_hash"], content_hash({k: v for k, v in self.report.items() if k != "logical_content_hash"}))
        with patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")):
            rebuilt = build_blocks(self.scope.read_bytes())
        self.assertEqual(self.raw, canonical_bytes(rebuilt) + b"\n")

    def test_public_index_has_source_urls_and_no_original_words(self):
        index = public_index(self.raw)
        encoded = canonical_bytes(index)
        for row in self.rows:
            self.assertIn(row["source"]["url"].encode(), encoded)
            block = row["audit_text_observation"]["narrative_opinion_block"]
            for line in block["lines"]:
                long_words = [w["text"] for w in line["words"] if len(w["text"]) > 25]
                for word in long_words:
                    self.assertNotIn(word.encode("utf-8"), encoded)
        for key in (b'"native_text":', b'"native_words":', b'"words":', b'"lines":'):
            self.assertNotIn(key, encoded)

    def test_public_index_matches_saved_projection(self):
        index = public_index(self.raw)
        saved = ROOT / "docs/data-pilots/annual-audit-blocks-2026-10-04-v2/evidence-index.json"
        self.assertEqual(saved.read_bytes(), canonical_bytes(index) + b"\n")
        self.assertEqual(index["private_report_sha256"], hashlib.sha256(self.raw).hexdigest())

    def test_old_assessment_projection_removes_both_text_channels(self):
        index = public_index(self.old_path.read_bytes())
        encoded = canonical_bytes(index)
        for row in self.old["observations"]:
            for page in row["selected_page_observations"]:
                self.assertNotIn(page["native_text"].encode("utf-8"), encoded)
                for word in page["native_words"]:
                    if len(word["text"]) > 25:
                        self.assertNotIn(word["text"].encode("utf-8"), encoded)

    def test_old_assessment_public_v2_is_exact_and_full_original_unchanged(self):
        self.assertEqual((ROOT / "docs/data-pilots/annual-audit-assessment-2026-10-04-v1/evidence-index-v2.json").read_bytes(),
                         canonical_bytes(public_index(self.old_path.read_bytes())) + b"\n")
        self.assertEqual(hashlib.sha256(self.old_path.read_bytes()).hexdigest(),
                         "ae06d17238f5cb4c5935112aad60cfdce283f3bab40548cdcdcb996c76b4dd31")

    def test_unknown_legacy_raw_type_text_withheld_not_interpreted(self):
        report = deepcopy(self.report)
        report["observations"][0]["audit_text_observation"]["raw_opinion_type"] = "未经确认的长段审计正文" * 50
        report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
        index = public_index(canonical_bytes(report) + b"\n")
        self.assertIsNone(index["observations"][0]["legacy_raw_type_text"])
        self.assertTrue(index["observations"][0]["legacy_raw_type_identified"])
        self.assertNotIn("未经确认".encode("utf-8"), canonical_bytes(index))

    def test_public_projection_rejects_text_in_coordinate_channel(self):
        report = deepcopy(self.report)
        block = next(r["audit_text_observation"]["narrative_opinion_block"] for r in report["observations"]
                     if r["audit_text_observation"]["narrative_opinion_block"]["state"] == SUCCESS)
        block["lines"][0]["words"][0]["box"][0] = "private body text"
        report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
        with self.assertRaisesRegex(ValueError, "numeric coordinates"):
            public_index(canonical_bytes(report) + b"\n")

    def test_public_projection_rejects_invalid_hash_noncanonical_and_PIT(self):
        for mode in ("hash", "canonical", "pit", "ready", "counts"):
            changed = deepcopy(self.report)
            if mode == "hash":
                changed["logical_content_hash"] = "0" * 64
            elif mode == "pit":
                changed["pit_admitted_observation_count"] = 1
            elif mode == "ready":
                changed["production_reader_ready"] = True
            elif mode == "counts":
                changed["counts"]["text"] = "private passage"
            if mode != "hash":
                changed["logical_content_hash"] = content_hash({k: v for k, v in changed.items() if k != "logical_content_hash"})
            raw = canonical_bytes(changed) + (b"\n " if mode == "canonical" else b"\n")
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                public_index(raw)

    def test_private_file_ignored_and_not_in_publishable_history(self):
        private = "docs/data-pilots/annual-audit-assessment-2026-10-04-v1/diagnostic-only.json"
        self.assertEqual(subprocess.run(["git", "check-ignore", "-q", private], cwd=ROOT).returncode, 0)
        tracked = subprocess.check_output(["git", "ls-files", "--", private], cwd=ROOT)
        self.assertEqual(tracked, b"")
        history = subprocess.check_output(["git", "rev-list", "--objects", "main", "--", private], cwd=ROOT)
        self.assertEqual(history, b"")
        # A public clone deliberately does not have the local private object.
        commits = subprocess.check_output(["git", "rev-list", "main"], cwd=ROOT).decode("ascii").splitlines()
        self.assertNotIn("c7cbcc458f49a2eda337756201d0b902dc11f62d", commits)


if __name__ == "__main__":
    unittest.main()
