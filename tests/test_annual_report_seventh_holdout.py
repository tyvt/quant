"""Metadata-selected seventh issuer; frozen first output before source review.

This is a source-extraction failure, not missing issuer disclosure or a passed
financial gate. No network, manual amount injection or parser repair in tests.
"""

import hashlib
import json
from pathlib import Path
import unittest

from scripts.extract_annual_report_bundle import ROOT, SOURCE_PATHS, build_bundle, markdown
from scripts.parsing.field_binder import compact
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import select_source
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class SeventhAnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600741-plan.json").read_bytes()
        cls.plan = json.loads(cls.plan_raw)
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600741-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.raw_dir = ROOT / Path(cls.source["pdf_path"]).parent
        cls.capture_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600741-capture.json").read_bytes()
        cls.capture = json.loads(cls.capture_raw)
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-600741-2026-10-03-v1"
        cls.replayed = replay_frozen_bundle(cls.scope_path, cls.result_dir, cls.plan["parser_commit"])
        cls.report = cls.replayed["report"]
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = PDFCache().parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])

    def test_frozen_six_code_blobs_and_no_layout_selection_or_repairs(self):
        self.assertEqual(self.plan["parser_commit"], "9cf2ed9e5ecdc795b381e6c2016698bfe10a9cd0")
        self.assertEqual(self.plan["parser_code_sha256"], self.report["manifest"]["code_sha256"])
        self.assertEqual(set(self.plan["parser_code_sha256"]), set(SOURCE_PATHS))
        for key in ("parser_edited_before_first_run", "pdf_body_inspected_before_first_run", "fixes_in_this_run"):
            self.assertFalse(self.plan["protocol"][key])
        self.assertTrue(self.plan["protocol"]["first_run_before_manual_source_review"])

    def test_plan_scope_and_capture_bound_to_exact_generated_bytes(self):
        self.assertEqual(hashlib.sha256(self.plan_raw).hexdigest(), self.capture["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.capture["scope_sha256"])
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.capture_raw, (self.raw_dir / "capture.json").read_bytes())
        self.assertEqual(self.source, self.capture["source"])

    def test_two_capture_requests_preserve_raw_hash_size_and_status(self):
        self.assertEqual([r["method"] for r in self.capture["resources"]], ["POST", "GET"])
        for resource in self.capture["resources"]:
            raw = (self.raw_dir / resource["name"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), resource["sha256"])
            self.assertEqual(len(raw), resource["bytes"])
            self.assertEqual(resource["http_status"], 200)
        self.assertEqual(self.pdf.sha256, "0e6c40acb8919acef249e2ce3520ff7c7bba00f524e8ccff34d1d58f88f996c8")
        self.assertEqual(len(self.pdf.pages), 224)

    def test_failed_metadata_endpoint_is_recorded_not_absence_evidence(self):
        protocol = self.plan["protocol"]
        self.assertEqual(protocol["preliminary_security_lookup_request_count"], 2)
        self.assertEqual(protocol["preliminary_catalogue_request_count"], 1)
        self.assertEqual(protocol["capture_request_limit"], 2)
        self.assertEqual(len(protocol["preliminary_security_lookup_failures"]), 1)
        self.assertEqual(protocol["preliminary_security_lookup_failures"][0]["http_status"], 404)
        self.assertIn("incorrect_endpoint_not_disclosure_absence", protocol["preliminary_security_lookup_failures"][0]["meaning"])
        self.assertFalse(protocol["automatic_retry_or_third_party_fallback"])

    def test_only_specified_full_report_not_summary_is_captured(self):
        row = select_source(self.catalogue_raw, self.plan)
        self.assertEqual((row["announcementId"], row["announcementTitle"]), ("1223375149", "华域汽车2024年年度报告"))
        self.assertEqual({r["announcementId"] for r in json.loads(self.catalogue_raw)["announcements"]},
                         {"1223375149", "1223375157"})
        self.assertEqual(json.loads(self.scope_raw)["reference_reports"], [])

    def test_catalogue_issuer_title_or_URL_drift_rejected(self):
        for key in ("secCode", "orgId", "announcementTitle", "adjunctUrl"):
            value = json.loads(self.catalogue_raw)
            next(r for r in value["announcements"] if r["announcementId"] == "1223375149")[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_duplicate_catalogue_ID_or_incomplete_counts_rejected(self):
        for variant in ("duplicate", "count", "more"):
            value = json.loads(self.catalogue_raw)
            if variant == "duplicate":
                value["announcements"][0]["announcementId"] = value["announcements"][1]["announcementId"]
            elif variant == "count":
                value["totalRecordNum"] += 1
            else:
                value["hasMore"] = True
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_first_JSON_and_markdown_bytes_recreated_by_frozen_Git(self):
        self.assertEqual(self.replayed["verified_code_files"], 6)
        self.assertEqual(self.replayed["code_commit"], self.plan["parser_commit"])
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), markdown(self.report))
        self.assertEqual(self.replayed["json_sha256"], "3aa09e2f3bbea3ed3f04a4970b736747a9bc374755802235e6d543640388a6ca")
        self.assertEqual(self.replayed["markdown_sha256"], "f95244c62f56476b9a2c7cd44b63e9afad64e66379e6f8f3acf3a041cd9046ce")

    def test_self_hash_excludes_only_top_level_hash(self):
        self.assertEqual(self.report["logical_content_hash"],
                         content_hash({k: v for k, v in self.report.items() if k != "logical_content_hash"}))
        self.assertEqual(self.report["logical_content_hash"], "40af14ef61253d352f0e9e7dd8655fe3f0d823c87f9f66e0e4b15c7fb20cf699")

    def test_currency_guard_blocks_three_tables_not_document_identity(self):
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual(self.bundle["currency_evidence"], [])
        self.assertEqual(self.bundle["currency_evidence_pages"], [])
        self.assertEqual(set(self.bundle["table_states"]), {"balance", "income", "cashflow"})
        self.assertEqual({v["state"] for v in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})

    def test_no_primary_values_or_manual_candidates_injected(self):
        self.assertEqual(set(self.bundle["fields"]), set(self.plan["expected_field_names"]))
        for field in self.bundle["fields"].values():
            self.assertEqual(field["state"], "NOT_IDENTIFIED")
            self.assertIsNone(field["observed_value_cny"])
            self.assertIsNone(field["comparative_not_target_value_cny"])
            self.assertEqual(field["candidates"], [])
        self.assertEqual(self.bundle["balance_sheet_row_inventory"], [])
        self.assertEqual({r["state"] for r in self.bundle["reconciliations"]}, {"UNKNOWN"})

    def test_post_blind_cover_has_source_identity_and_supported_arabic_title(self):
        text = compact(self.pdf.pages[0].text)
        self.assertIn(self.source["issuer"], text)
        self.assertIn("600741", text)
        self.assertIn("2024年年度报告", text)
        self.assertNotIn("document_identity_evidence", self.bundle)

    def test_post_blind_policy_range_and_parenthesized_subsection_present(self):
        self.assertIn("二、重要会计政策及会计估计", compact(self.pdf.pages[83].text))
        self.assertIn("(6)记账本位币", compact(self.pdf.pages[84].text))
        self.assertIn("(7)同一控制下和非同一控制下企业合并的会计处理方法", compact(self.pdf.pages[84].text))
        self.assertIn("三、税项", compact(self.pdf.pages[102].text))
        self.assertEqual(self.bundle["currency_evidence_pages"], [])

    def test_post_blind_issuer_declaration_and_subsidiary_context_not_PIT(self):
        text = compact(self.pdf.pages[84].text)
        self.assertIn("本公司记账本位币为人民币。", text)
        self.assertIn("本公司下属子公司根据其经营所处的主要经济环境确定其记账本位币，", text)
        self.assertIn("公司之境外子公司的记账本位币包括美元、欧元、日元、泰铢等。", text)
        self.assertIn("本财务报表以人民币列示。", text)
        self.assertNotIn("本公司的记账本位币为人民币。", text)
        self.assertIsNone(self.bundle["currency"])

    def test_lease_and_audit_unknown_not_promoted_to_financial_gate(self):
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertFalse(self.bundle["lease_financing_component"]["is_complete_lease_cash"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertIsNone(self.bundle["audit_text_observation"]["latest_audit_unmodified_pit"])

    def test_metadata_time_and_snapshot_state_not_historical_availability(self):
        self.assertEqual(self.capture["catalogue_time_raw_ms"], 1745856000000)
        self.assertIsNone(self.capture["exact_available_at_utc"])
        self.assertFalse(self.capture["pdf_body_read"])
        for key in ("complete_revision_chain_verified", "snapshot_published", "production_reader_ready"):
            self.assertFalse(self.capture[key])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")

    def test_no_screening_export_or_historical_PIT_admission(self):
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertEqual(self.report["timing_policy"], "UNKNOWN_UNLESS_VERIFIED")
        for key in ("screening_input_exported", "real_pit_run_authorized", "production_reader_ready"):
            self.assertFalse(self.report[key])
        self.assertEqual(len(self.report["bundles"]), 1)
        self.assertEqual(self.bundle["source"]["security_id"], "sh.600741")
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_current_cold_warm_cache_is_deterministic_without_repair(self):
        cache = PDFCache()
        first, second = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))


if __name__ == "__main__":
    unittest.main()
