"""Fifth issuer blind failure, source provenance and frozen-code reproducibility.

Post-blind source checks never inject values or repair the frozen parser.
These tests are offline; unknown input is not a successful enterprise gate.
"""

import hashlib
import json
from pathlib import Path
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle, markdown
from scripts.parsing.field_binder import compact
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import select_source
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class FifthAnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-601012-plan.json").read_bytes()
        cls.plan = json.loads(cls.plan_raw)
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-601012-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.raw_dir = ROOT / Path(cls.source["pdf_path"]).parent
        cls.capture_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-601012-capture.json").read_bytes()
        cls.record = json.loads(cls.capture_raw)
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-601012-2026-10-03-v1"
        cls.report = replay_frozen_bundle(cls.scope_path, cls.result_dir, cls.plan["parser_commit"])["report"]
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = PDFCache().parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])

    def test_plan_freezes_code_before_blind_phase_without_issuer_repairs(self):
        self.assertEqual(self.plan["parser_commit"], "f1666f7c561cc2b242e1888717edadcc7b7222d5")
        self.assertEqual(self.report["manifest"]["code_sha256"], self.plan["parser_code_sha256"])
        for name in ("parser_edited_before_first_run", "pdf_body_inspected_before_first_run", "fixes_in_this_run"):
            self.assertFalse(self.plan["protocol"][name])
        self.assertTrue(self.plan["protocol"]["first_run_before_manual_source_review"])

    def test_scope_and_capture_index_are_exact_generated_bytes(self):
        self.assertEqual(hashlib.sha256(self.plan_raw).hexdigest(), self.record["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.record["scope_sha256"])
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.capture_raw, (self.raw_dir / "capture.json").read_bytes())
        self.assertEqual(self.source, self.record["source"])
        self.assertEqual(hashlib.sha256((ROOT / "scripts/pilots/capture_annual_holdout.py").read_bytes()).hexdigest(),
                         self.record["capture_code_sha256"])

    def test_two_capture_requests_have_real_bytes_and_hashes(self):
        self.assertEqual([r["method"] for r in self.record["resources"]], ["POST", "GET"])
        for resource in self.record["resources"]:
            raw = (self.raw_dir / resource["name"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), resource["sha256"])
            self.assertEqual(len(raw), resource["bytes"])
            self.assertEqual(resource["http_status"], 200)
        self.assertEqual(len(self.pdf.pages), 301)
        self.assertEqual(self.pdf.sha256, "3dbaf5314ab01f44b58f58e8ad75fea0dce3ced0001db516829f2624b615a3a0")

    def test_metadata_reads_are_not_hidden_in_two_request_capture_limit(self):
        self.assertEqual(self.plan["protocol"]["preliminary_catalogue_request_count"], 4)
        self.assertEqual(self.plan["protocol"]["preliminary_security_lookup_request_count"], 1)
        self.assertEqual(self.plan["protocol"]["capture_request_limit"], 2)
        self.assertEqual(self.plan["catalogue_payload"]["stock"], "601012,9900022338")
        self.assertEqual(self.plan["catalogue_payload"]["category"], "category_ndbg_szsh;")
        self.assertFalse(self.plan["protocol"]["automatic_retry_or_third_party_fallback"])

    def test_full_report_not_summary_or_later_revision_selected(self):
        row = select_source(self.catalogue_raw, self.plan)
        self.assertEqual((row["announcementId"], row["announcementTitle"]), ("1223421477", "2024年年度报告"))
        rows = json.loads(self.catalogue_raw)["announcements"]
        self.assertEqual({r["announcementId"] for r in rows}, {"1223421484", "1223421477", "1223477802"})
        self.assertIn("修订版", next(r["announcementTitle"] for r in rows if r["announcementId"] == "1223477802"))
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")

    def test_catalogue_issuer_url_or_title_drift_hard_fails(self):
        for key in ("secCode", "orgId", "adjunctUrl", "announcementTitle"):
            value = json.loads(self.catalogue_raw)
            next(r for r in value["announcements"] if r["announcementId"] == "1223421477")[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_duplicate_catalogue_ids_rejected(self):
        value = json.loads(self.catalogue_raw)
        value["announcements"][0]["announcementId"] = value["announcements"][1]["announcementId"]
        with self.assertRaises(ValueError):
            select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_frozen_git_execution_recreates_first_report_bytes(self):
        for name, digest in (("diagnostic-only.json", "7d7c1072d3b4fb2a18efd845084a57f11e1a053e13aafc00182403ea2d73029f"),
                             ("diagnostic-only.md", "548820d0ca90a3bd1b49a330fed265d03eba7983f50e0dfe534ba62c25344e2e")):
            self.assertEqual(hashlib.sha256((self.result_dir / name).read_bytes()).hexdigest(), digest)
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), markdown(self.report))

    def test_self_hash_excludes_only_top_level_hash_field(self):
        self.assertEqual(self.report["logical_content_hash"],
                         content_hash({k: v for k, v in self.report.items() if k != "logical_content_hash"}))
        self.assertEqual(self.report["logical_content_hash"], "fb798fd80515c84a1611a28b0258ab2cf995fe4a11a24b3b683f32ed92a444b9")

    def test_cold_warm_results_deterministic_one_pdf_parse(self):
        cache = PDFCache()
        first, second = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))

    def test_currency_guard_still_blocks_all_tables_for_new_subject_phrase(self):
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual(self.bundle["currency_evidence"], [])
        self.assertEqual(self.bundle["currency_evidence_pages"], [])
        self.assertEqual(set(self.bundle["table_states"]), {"balance", "income", "cashflow"})
        self.assertEqual({v["state"] for v in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})

    def test_seven_unknown_fields_have_no_injected_values_or_candidates(self):
        self.assertEqual(set(self.bundle["fields"]), set(self.plan["expected_field_names"]))
        for field in self.bundle["fields"].values():
            self.assertIsNone(field["observed_value_cny"])
            self.assertIsNone(field["comparative_not_target_value_cny"])
            self.assertEqual(field["state"], "NOT_IDENTIFIED")
            self.assertEqual(field["candidates"], [])
        self.assertEqual(self.bundle["balance_sheet_row_inventory"], [])
        self.assertEqual({r["state"] for r in self.bundle["reconciliations"]}, {"UNKNOWN"})

    def test_post_blind_joint_subject_and_foreign_subsidiary_context_recorded(self):
        text = compact(self.pdf.pages[139].text)
        self.assertIn("4、记账本位币", text)
        self.assertIn("本公司及境内子公司记账本位币为人民币。", text)
        self.assertIn("境外子公司", text)
        self.assertIn("本财务报表以人民币列示。", text)
        self.assertNotIn("本公司的记账本位币为人民币。", text)
        self.assertIsNone(self.bundle["currency"])

    def test_currency_policy_range_and_source_identity_exist_but_do_not_fill_unknown(self):
        self.assertIn("五、重要会计政策及会计估计", compact(self.pdf.pages[138].text))
        self.assertIn("六、税项", compact(self.pdf.pages[167].text))
        cover = compact(self.pdf.pages[0].text)
        self.assertIn(self.source["issuer"], cover)
        self.assertIn("公司代码：601012", cover)
        self.assertIn("2024年年度报告", cover)
        self.assertIsNone(self.bundle["currency"])

    def test_post_blind_original_amounts_exist_without_rule_observations(self):
        for n, amounts in {121: ("60,895,314,122.52", "505,365,076.35"),
                           128: ("-4,724,978,931.84", "8,013,068,271.53")}.items():
            for amount in amounts:
                self.assertIn(amount, self.pdf.pages[n - 1].text)
        self.assertIsNone(self.bundle["fields"]["attributable_equity_end"]["observed_value_cny"])
        self.assertIsNone(self.bundle["fields"]["operating_cash_flow"]["observed_value_cny"])

    def test_presentation_currency_and_parent_tables_do_not_bypass_guard(self):
        self.assertIn("币种：人民币", compact(self.pdf.pages[117].text))
        self.assertIn("母公司资产负债表", self.pdf.pages[120].text)
        self.assertIn("母公司利润表", self.pdf.pages[125].text)
        self.assertIsNone(self.bundle["fields"]["parent_net_profit"]["observed_value_cny"])

    def test_directory_and_fetch_clocks_not_historical_availability_or_version_chain(self):
        self.assertEqual(self.record["catalogue_time_raw_ms"], 1745942400000)
        self.assertIsNone(self.record["exact_available_at_utc"])
        self.assertFalse(self.record["pdf_body_read"])
        for name in ("complete_revision_chain_verified", "snapshot_published", "production_reader_ready"):
            self.assertFalse(self.record[name])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])

    def test_no_other_issuer_reference_screening_export_or_pit_admission(self):
        self.assertEqual(json.loads(self.scope_raw)["reference_reports"], [])
        self.assertEqual(len(self.report["bundles"]), 1)
        self.assertEqual(self.bundle["source"]["security_id"], "sh.601012")
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["screening_input_exported"])
        self.assertFalse(self.report["real_pit_run_authorized"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))


if __name__ == "__main__":
    unittest.main()
