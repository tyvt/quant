"""Issuer eleven: preserve the first currency-blocked output, not a note test."""

import hashlib
import json
import subprocess
import unittest

from scripts.extract_annual_report_bundle import ROOT, SOURCE_PATHS, build_bundle, markdown
from scripts.parsing.annual_report_parser import _currency_evidence, _currency_section
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import select_source
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class EleventhAnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-000651-plan.json").read_bytes()
        cls.plan = json.loads(cls.plan_raw)
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-000651-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.raw_dir = ROOT / cls.source["pdf_path"]
        cls.raw_dir = cls.raw_dir.parent
        cls.capture_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-000651-capture.json").read_bytes()
        cls.capture = json.loads(cls.capture_raw)
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-000651-2026-10-03-v1"
        cls.replay = replay_frozen_bundle(cls.scope_path, cls.result_dir, cls.plan["parser_commit"])
        cls.report = cls.replay["report"]
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = PDFCache().parse((cls.raw_dir / "annual.pdf").read_bytes(), cls.source["pdf_sha256"])
        cls.section = _currency_section(cls.pdf)

    def test_six_code_blobs_bound_to_full_frozen_commit(self):
        self.assertEqual(self.plan["parser_commit"], "2c17b9083fd3eec4124abb3d91546b5ee4ae3c28")
        self.assertEqual(set(self.plan["parser_code_sha256"]), set(SOURCE_PATHS))
        self.assertEqual(self.plan["parser_code_sha256"], self.report["manifest"]["code_sha256"])
        for name, digest in self.plan["parser_code_sha256"].items():
            raw = subprocess.check_output(["git", "show", f"{self.plan['parser_commit']}:{name}"], cwd=ROOT)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)

    def test_selection_is_metadata_only_no_repair_or_preinspection(self):
        protocol = self.plan["protocol"]
        self.assertIn("metadata_only_not_financial_values_or_layout", protocol["selection_basis"])
        for key in ("pdf_body_inspected_before_first_run", "parser_edited_before_first_run", "fixes_in_this_run"):
            self.assertFalse(protocol[key])
        self.assertTrue(protocol["first_run_before_manual_source_review"])

    def test_preliminary_reads_separate_from_formal_capture(self):
        protocol = self.plan["protocol"]
        self.assertEqual(protocol["preliminary_security_lookup_request_count"], 1)
        self.assertEqual(protocol["preliminary_catalogue_request_count"], 1)
        self.assertEqual(protocol["official_homepage_metadata_read_count"], 1)
        self.assertTrue(protocol["successful_security_lookup_url"].endswith("/topSearch/query"))

    def test_scope_capture_and_plan_hashes_and_exact_byte_copies(self):
        self.assertEqual(hashlib.sha256(self.plan_raw).hexdigest(), self.capture["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.capture["scope_sha256"])
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.capture_raw, (self.raw_dir / "capture.json").read_bytes())
        self.assertEqual(hashlib.sha256(self.capture_raw).hexdigest(),
                         "bf31dab3c2cbbf1e0d20ac254427f07b85334a11bd2806761c5a2f6e9e3b2767")

    def test_capture_exact_two_requests_no_retries_and_source_hash(self):
        self.assertEqual(self.plan["protocol"]["capture_request_limit"], 2)
        self.assertFalse(self.plan["protocol"]["automatic_retry_or_third_party_fallback"])
        self.assertEqual([r["method"] for r in self.capture["resources"]], ["POST", "GET"])
        for item in self.capture["resources"]:
            raw = (self.raw_dir / item["name"]).read_bytes()
            self.assertEqual((hashlib.sha256(raw).hexdigest(), len(raw)), (item["sha256"], item["bytes"]))
            self.assertEqual(item["http_status"], 200)
        self.assertFalse(self.capture["pdf_body_read"])
        self.assertEqual(self.source["page_count"], 248)
        self.assertEqual(self.source["pdf_sha256"],
                         "c7184706caf5f57c04a795990967cfc4f4253024e02f8bdaffe2b260df2c6006")

    def test_select_only_chinese_full_report_not_summary_or_english(self):
        selected = select_source(self.catalogue_raw, self.plan)
        self.assertEqual(selected["announcementId"], "1223330631")
        self.assertEqual(selected["announcementTitle"], "2024年年度报告")
        self.assertEqual({r["announcementId"] for r in json.loads(self.catalogue_raw)["announcements"]},
                         {"1223330631", "1223330640", "1223836182"})
        self.assertEqual(json.loads(self.scope_raw)["reference_reports"], [])

    def test_title_URL_security_and_org_drift_rejected(self):
        for key in ("announcementTitle", "adjunctUrl", "secCode", "orgId"):
            value = json.loads(self.catalogue_raw)
            next(r for r in value["announcements"] if r["announcementId"] == "1223330631")[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_duplicate_ID_and_incomplete_counts_rejected(self):
        for mode in ("duplicate", "count", "more"):
            value = json.loads(self.catalogue_raw)
            if mode == "duplicate":
                value["announcements"][0]["announcementId"] = value["announcements"][1]["announcementId"]
            elif mode == "count":
                value["totalRecordNum"] += 1
            else:
                value["hasMore"] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_actual_frozen_CLI_replays_normal_JSON_and_markdown(self):
        self.assertEqual(self.replay["verified_code_files"], 6)
        self.assertEqual(self.replay["json_sha256"],
                         "2d446e6aecddeb59ee736b4a68450c39e8ed7651c2ba3bc6de7957564a03ee47")
        self.assertEqual(self.replay["markdown_sha256"],
                         "9201ba3260b3000a2705da994e65fef086c542252ef5b5cb59cfcb6d10500315")
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), markdown(self.report))

    def test_logical_identity_excludes_only_self_hash(self):
        self.assertEqual(self.report["logical_content_hash"],
                         "4b7eb3278bb6a8300956dafe09de51cf6adca3a17a8139deffd5fc035937bcf4")
        self.assertEqual(self.report["logical_content_hash"], content_hash({k: v for k, v in self.report.items()
                                                                         if k != "logical_content_hash"}))

    def test_normal_bundle_not_identity_rejection(self):
        self.assertEqual(self.report["schema"], "annual-source-bundle-diagnostic-v1")
        self.assertEqual(len(self.report["bundles"]), 1)
        self.assertEqual((self.bundle["source"]["security_id"], self.bundle["source"]["fiscal_year"]),
                         ("sz.000651", 2024))
        self.assertTrue(self.report["diagnostic_only"])

    def test_currency_missing_blocks_all_three_tables(self):
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual(self.bundle["currency_evidence"], [])
        self.assertEqual(set(self.bundle["table_states"]), {"balance", "income", "cashflow"})
        self.assertEqual({v["state"] for v in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})

    def test_seven_values_comparatives_and_candidates_not_filled(self):
        self.assertEqual(set(self.bundle["fields"]), set(self.plan["expected_field_names"]))
        for field in self.bundle["fields"].values():
            self.assertIsNone(field["observed_value_cny"])
            self.assertIsNone(field["comparative_not_target_value_cny"])
            self.assertIsNone(field["pit_value"])
            self.assertEqual(field["state"], "NOT_IDENTIFIED")
            self.assertEqual(field["candidates"], [])

    def test_zero_row_inventory_means_note_feature_not_evaluated(self):
        self.assertEqual(self.bundle["balance_sheet_row_inventory"], [])
        self.assertEqual(len(self.bundle["reconciliations"]), 4)
        self.assertEqual({r["state"] for r in self.bundle["reconciliations"]}, {"UNKNOWN"})
        self.assertTrue(all(r["difference_cny"] is None for r in self.bundle["reconciliations"]))
        self.assertFalse(self.bundle["full_balance_sheet_semantics_certified"])

    def test_source_policy_and_legacy_subsection_are_localized(self):
        self.assertIsNotNone(self.section)
        lines = self.section["lines"]
        expected = {"start": (124, "三、重要会计政策及会计估计"), "end": (152, "四、税项"),
                    "index": (124, "4、记账本位币"),
                    "section_end": (124, "5、重要性标准确定方法和选择依据")}
        for key, value in expected.items():
            page, _, text = lines[self.section[key]]
            self.assertEqual((page.number, text), value)
        self.assertFalse(self.section["parenthesized"])

    def test_comma_connected_statement_native_word_not_full_stop_declaration(self):
        page, words, text = self.section["lines"][self.section["index"] + 1]
        expected = "本公司以人民币为记账本位币，本公司的个别子公司采用人民币以外的货币作为记账本位币。"
        self.assertEqual((page.number, text), (124, expected))
        self.assertEqual([word.text for word in words], [expected])
        self.assertEqual(words[0].box, (90.984, 464.314, 500.768, 474.274))
        self.assertNotIn("本公司以人民币为记账本位币。", text)
        self.assertEqual(_currency_evidence(self.pdf, section=self.section), [])

    def test_observed_audit_type_bound_to_page106_not_audit_gate(self):
        audit = self.bundle["audit_text_observation"]
        self.assertEqual((audit["raw_opinion_type"], audit["state"]),
                         ("标准的无保留意见", "OBSERVED_TEXT_NOT_AUDIT_GATE"))
        self.assertEqual(len(audit["candidates"]), 1)
        binding = audit["candidates"][0]["binding"]
        self.assertEqual((binding["physical_page"], binding["document_sha256"]),
                         (106, self.source["pdf_sha256"]))
        self.assertFalse(binding["pit_admitted"])
        self.assertIsNone(audit["latest_audit_unmodified_pit"])
        self.assertEqual(audit["amended_whole_statement_audit_status"], "UNKNOWN")

    def test_full_lease_and_historical_version_remain_unknown(self):
        lease = self.bundle["lease_financing_component"]
        self.assertIsNone(lease["observed_value_cny"])
        self.assertIsNone(lease["full_lease_cash_not_already_deducted"])
        self.assertFalse(lease["is_complete_lease_cash"])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")
        self.assertFalse(self.capture["complete_revision_chain_verified"])

    def test_catalogue_and_fetch_times_not_historical_PIT_or_export(self):
        self.assertEqual(self.capture["catalogue_time_raw_ms"], 1745769600000)
        self.assertIsNone(self.capture["exact_available_at_utc"])
        self.assertEqual(self.report["timing_policy"], "UNKNOWN_UNLESS_VERIFIED")
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        for key in ("screening_input_exported", "real_pit_run_authorized", "production_reader_ready", "official_selection"):
            self.assertFalse(self.report[key])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_current_cold_warm_repeatable_without_rewriting_frozen_files(self):
        old_json = (self.result_dir / "diagnostic-only.json").read_bytes()
        old_md = (self.result_dir / "diagnostic-only.md").read_bytes()
        cache = PDFCache()
        a, b = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(markdown(a), markdown(b))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), old_json)
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), old_md)


if __name__ == "__main__":
    unittest.main()
