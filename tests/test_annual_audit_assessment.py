"""Assessment evidence stays raw: no narrative opinion, semantics or gate."""

from copy import deepcopy
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.parsing.generic_extractor import Page, Word
from scripts.pilots import assess_annual_audit_narratives as assessment
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class AnnualAuditAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope_path = assessment.ROOT / "docs/data-pilots/2026-10-04-annual-audit-assessment-scope.json"
        cls.raw_scope = cls.scope_path.read_bytes()
        cls.scope = json.loads(cls.raw_scope)
        cls.directory = assessment.ROOT / "docs/data-pilots/annual-audit-assessment-2026-10-04-v1"
        cls.raw_report = (cls.directory / "diagnostic-only.json").read_bytes()
        cls.report = json.loads(cls.raw_report)
        cls.by_key = {assessment.source_key(r["source"]): r for r in cls.report["observations"]}
        cls.by_security = {r["source"]["security_id"]: r for r in cls.report["observations"]}

    def changed_scope(self, field, value):
        scope = deepcopy(self.scope)
        scope[field] = value
        return canonical_bytes(scope)

    def synthetic_page(self, text, *, rotation=0, box=(10, 10, 590, 20)):
        source = self.by_security["sh.600900"]["source"]
        page = Page(1, 600, 800, rotation, text, (Word(text, box),))
        return assessment.page_observation(page, source)

    def test_scope_and_own_logical_hashes(self):
        self.assertEqual(self.report["scope_sha256"], hashlib.sha256(self.raw_scope).hexdigest())
        self.assertEqual(self.report["logical_content_hash"],
                         content_hash({k: v for k, v in self.report.items() if k != "logical_content_hash"}))
        self.assertEqual(self.report["logical_content_hash"],
                         "18b268857306eed59b6ff6bebb7f0a3177203fd77f4ff72cb9996b98c45c52b1")

    def test_canonical_JSON_and_markdown_stable_after_reload(self):
        self.assertEqual(self.raw_report, canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.directory / "diagnostic-only.md").read_bytes(), assessment.markdown(self.report))
        self.assertEqual(assessment.markdown(self.report), assessment.markdown(json.loads(canonical_bytes(self.report))))

    def test_frozen_six_code_blobs_and_rule_identity(self):
        manifest = self.report["manifest"]
        self.assertEqual(manifest["parser_commit"], "5bf686c0f4217b5a50d3eafb0c49c2df8d99d98d")
        self.assertEqual(len(manifest["parser_code_sha256"]), 6)
        for path, digest in manifest["parser_code_sha256"].items():
            blob = subprocess.check_output(["git", "show", f"{manifest['parser_commit']}:{path}"], cwd=assessment.ROOT)
            self.assertEqual(hashlib.sha256(blob).hexdigest(), digest)
        self.assertEqual(manifest["rule_sha256"], assessment.RULE_SHA256)

    def test_eleven_issuers_fourteen_versions_six_types_eight_unknown(self):
        self.assertEqual(self.report["counts"], {"issuers": 11, "PDF_versions": 14,
                         "legacy_raw_type_identified": 6, "legacy_raw_type_unknown": 8, "selected_review_pages": 9})
        self.assertEqual(len(self.by_key), 14)

    def test_existing_baselines_and_inputs_have_exact_bytes(self):
        for ref in self.scope["inputs"] + self.scope["baseline_reports"]:
            raw = (assessment.ROOT / ref["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), ref["sha256"])
        self.assertEqual(self.scope["inputs"], self.report["manifest"]["input_scopes"])

    def test_each_raw_source_hash_and_page_count_bound(self):
        import fitz
        for row in self.report["observations"]:
            source = row["source"]
            raw = (assessment.ROOT / source["pdf_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), source["pdf_sha256"])
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                self.assertEqual(pdf.page_count, source["page_count"])

    def test_explicit_pages_only_for_eight_legacy_unknowns(self):
        expected = {"sh.600066": [57, 58], "sh.600276": [139], "sh.600309": [75], "sh.600585": [97],
                    "sh.600741": [67], "sh.600887": [83], "sh.600900": [85], "sh.601012": [111]}
        actual = {r["source"]["security_id"]: [p["physical_page"] for p in r["selected_page_observations"]]
                  for r in self.report["observations"] if r["selected_page_observations"]}
        self.assertEqual(actual, expected)
        for sid in expected:
            self.assertIsNone(self.by_security[sid]["legacy_audit_text_observation"]["raw_opinion_type"])

    def test_native_page_text_and_word_boxes_match_verified_PDF(self):
        from scripts.parsing.generic_extractor import PDFCache
        for row in self.report["observations"]:
            if not row["selected_page_observations"]:
                continue
            source = row["source"]
            pdf = PDFCache().parse((assessment.ROOT / source["pdf_path"]).read_bytes(), source["pdf_sha256"])
            for observed in row["selected_page_observations"]:
                page = pdf.pages[observed["physical_page"] - 1]
                self.assertEqual(observed, assessment.page_observation(page, source))
                self.assertEqual(observed["native_text_sha256"], hashlib.sha256(page.text.encode("utf-8")).hexdigest())

    def test_native_evidence_refs_and_all_certification_flags_false(self):
        for row in self.report["observations"]:
            for page in row["selected_page_observations"]:
                self.assertEqual(page["evidence_ref"],
                                 f"pdf:sha256:{row['source']['pdf_sha256']}:physical-page:{page['physical_page']}")
                self.assertEqual(page["state"], "OBSERVED_SELECTED_NATIVE_PAGE_NOT_OPINION_TYPE")
                for key in ("report_object_verified", "whole_audit_report_reviewed", "public_availability_verified",
                            "latest_audit_version_verified"):
                    self.assertFalse(page[key])
                self.assertIsNone(page["opinion_type_inferred"])
                self.assertIsNone(page["audit_gate_result"])

    def test_eight_first_pages_have_narrative_not_table_type_label(self):
        for row in self.report["observations"]:
            if row["selected_page_observations"]:
                flags = row["selected_page_observations"][0]["literal_markers_not_semantic_proof"]
                for key in ("declared_issuer_characters", "declared_period_end_characters", "we_audited_characters",
                            "we_believe_characters", "narrative_opinion_heading_characters"):
                    self.assertTrue(flags[key])
                self.assertFalse(flags["legacy_opinion_type_word"])

    def test_huayu_nested_content_and_opinion_subheadings_kept(self):
        text = self.by_security["sh.600741"]["selected_page_observations"][0]["native_text"]
        self.assertIn("(一)我们审计的内容", text)
        self.assertIn("(二)我们的意见", text)
        self.assertIsNone(self.by_security["sh.600741"]["narrative_opinion_type"])

    def test_yutong_parenthesized_headings_not_transformed(self):
        text = self.by_security["sh.600066"]["selected_page_observations"][0]["native_text"]
        self.assertIn("(一)审计意见", text)
        self.assertIn("(二)形成审计意见的基础", text)

    def test_report_number_forms_kept_without_regex_normalization(self):
        expected = {"sh.600276": "安永华明(2025)审字第70043287_B01号",
                    "sh.600309": "安永华明（2025）审字第70032716_J01号",
                    "sh.600585": "安永华明（2025）审字第70055930_Y01号",
                    "sh.600741": "普华永道中天审字(2025)第10026号",
                    "sh.600887": "XYZH/2025XAAA4B0186", "sh.600900": "大华审字[2025]0011006910号",
                    "sh.601012": "毕马威华振审字第2514608号"}
        for sid, raw in expected.items():
            text = self.by_security[sid]["selected_page_observations"][0]["native_text"]
            self.assertIn(raw, "".join(text.split()))  # Search-only; stored native text is not normalized.

    def test_yutong_two_pages_no_number_does_not_invent_or_reject_report(self):
        row = self.by_security["sh.600066"]
        text = "".join(p["native_text"] for p in row["selected_page_observations"])
        self.assertNotIn("审字", text)
        self.assertIn("二〇二五年三月二十九日", text)
        self.assertIsNone(row["narrative_opinion_type"])
        self.assertIsNone(row["audit_gate_result"])

    def test_yutong_responsibility_condition_not_actual_going_concern_finding(self):
        row = self.by_security["sh.600066"]
        text = "".join(row["selected_page_observations"][1]["native_text"].split())
        self.assertIn("如果我们得出结论认为存在重大不确定性", text)
        self.assertIsNone(row["legacy_audit_text_observation"]["going_concern_uncertainty_pit"])

    def test_yili_physical83_not_printed79(self):
        page = self.by_security["sh.600887"]["selected_page_observations"][0]
        self.assertEqual(page["physical_page"], 83)
        self.assertIn("79 / 266", page["native_text"])

    def test_beiyinmei_three_versions_keep_emphasis_type_not_plain_type(self):
        rows = [r for r in self.report["observations"] if r["source"]["security_id"] == "sz.002570"]
        self.assertEqual(len(rows), 3)
        for row in rows:
            audit = row["legacy_audit_text_observation"]
            self.assertEqual(audit["raw_opinion_type"], "带强调事项段的无保留意见")
            self.assertIsNone(audit["latest_audit_unmodified_pit"])
            self.assertEqual(audit["amended_whole_statement_audit_status"], "UNKNOWN")

    def test_gree_and_000637_table_controls_do_not_certify_gates(self):
        for row in self.report["observations"]:
            if row["source"]["security_id"] in ("sz.000651", "sz.000637"):
                audit = row["legacy_audit_text_observation"]
                self.assertEqual(audit["raw_opinion_type"], "标准的无保留意见")
                self.assertEqual(audit["state"], "OBSERVED_TEXT_NOT_AUDIT_GATE")
                self.assertEqual(row["selected_page_observations"], [])
                self.assertIsNone(row["audit_gate_result"])

    def test_any_opinion_type_keyword_alone_remains_unclassified(self):
        for text in ("无保留意见", "保留意见", "否定意见", "无法表示意见", "带强调事项段的无保留意见"):
            page = self.synthetic_page(text)
            self.assertIsNone(page["opinion_type_inferred"])
            self.assertIsNone(page["audit_gate_result"])

    def test_we_believe_example_negation_and_special_review_not_semantics(self):
        for text in ("例：我们认为财务报表公允反映", "我们认为，财务报表未能公允反映", "会计差错更正专项审核：我们认为"):
            page = self.synthetic_page(text)
            self.assertTrue(page["literal_markers_not_semantic_proof"]["we_believe_characters"])
            self.assertFalse(page["report_object_verified"])
            self.assertIsNone(page["opinion_type_inferred"])

    def test_foreign_issuer_or_wrong_period_not_certified(self):
        page = self.synthetic_page("我们审计了其他公司的2023年12月31日财务报表。我们认为。")
        flags = page["literal_markers_not_semantic_proof"]
        self.assertFalse(flags["declared_issuer_characters"])
        self.assertFalse(flags["declared_period_end_characters"])
        self.assertFalse(page["report_object_verified"])

    def test_truncated_rotated_outside_page_preserved_not_admitted(self):
        for rotation, box in ((90, (10, 10, 590, 20)), (0, (10, 10, 620, 20))):
            page = self.synthetic_page("审计意见：我们认", rotation=rotation, box=box)
            self.assertFalse(page["all_native_words_inside_unrotated_page"])
            self.assertEqual(page["native_words"][0]["box"], list(box))
            self.assertIsNone(page["opinion_type_inferred"])

    def test_repeated_report_numbers_not_merged_into_latest_version(self):
        page = self.synthetic_page("大华审字[2025]0011006910号 大华审字[2025]0011006910号")
        self.assertEqual(page["native_text"].count("大华审字"), 2)
        self.assertFalse(page["latest_audit_version_verified"])

    def test_no_PIT_selection_ready_or_batch_export(self):
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertIsNone(self.report["diagnostic_available_at"])
        for key in ("narrative_parser_implemented", "screening_input_exported", "real_pit_run_authorized",
                    "production_reader_ready", "official_selection"):
            self.assertFalse(self.report[key])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_scope_duplicate_keys_nonfinite_or_wrong_schema_rejected(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"schema":NaN}', self.changed_scope("schema", "wrong")):
            with self.assertRaises(ValueError):
                assessment.read_assessment_scope(raw)

    def test_duplicate_scope_reference_or_review_identity_rejected(self):
        for key in ("inputs", "baseline_reports", "review_pages"):
            with self.assertRaises(ValueError):
                assessment.read_assessment_scope(self.changed_scope(key, self.scope[key] + [self.scope[key][0]]))

    def test_invalid_review_pages_or_empty_sections_rejected(self):
        for pages in ([0], [True], [57, 57], [58, 57], []):
            scope = deepcopy(self.scope)
            scope["review_pages"][0]["physical_pages"] = pages
            with self.assertRaises(ValueError):
                assessment.read_assessment_scope(canonical_bytes(scope))
        for key in ("inputs", "baseline_reports", "review_pages"):
            with self.assertRaises(ValueError):
                assessment.read_assessment_scope(self.changed_scope(key, []))

    def test_diagnostic_baseline_hash_or_PIT_state_mutation_rejected(self):
        for mode in ("hash", "pit", "schema"):
            report = deepcopy(self.report)
            if mode == "hash":
                report["logical_content_hash"] = "0" * 64
            elif mode == "pit":
                report["pit_admitted_observation_count"] = 1
            else:
                report["schema"] = "wrong"
                report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            with patch.object(assessment, "verified_bytes", return_value=canonical_bytes(report)), self.assertRaises(ValueError):
                assessment.baseline_sources(self.scope["baseline_reports"], assessment.ROOT)

    def test_missing_extra_review_or_wrong_asof_rejected_before_PDFs(self):
        for mode in ("missing", "extra", "asof"):
            scope = deepcopy(self.scope)
            if mode == "missing":
                scope["review_pages"].pop()
            elif mode == "extra":
                scope["review_pages"][0]["security_id"] = "sz.000651"
            else:
                scope["as_of"] = "2025-09-30"
            with patch.object(assessment, "verify_parser"), self.assertRaises(ValueError):
                assessment.build_assessment(canonical_bytes(scope))

    def test_frozen_offline_rebuild_exact_no_network(self):
        from scripts.pilots.replay_frozen_annual_audit_assessment import replay_frozen_assessment
        with patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")):
            replay = replay_frozen_assessment(self.scope_path, self.directory,
                                             "88fcd1763339cc792a5c63f2be93f3b50cb9bf1a")
        self.assertEqual(replay["json_sha256"], hashlib.sha256(self.raw_report).hexdigest())
        self.assertEqual(replay["markdown_sha256"], hashlib.sha256((self.directory / "diagnostic-only.md").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
