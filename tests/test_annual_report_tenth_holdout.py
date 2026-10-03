"""Frozen tenth-issuer first output: seven fields, not complete statements/PIT."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from scripts.extract_annual_report_bundle import ROOT, SOURCE_PATHS, build_bundle, markdown
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import select_source
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


CURRENT = {"attributable_equity_end": "53179935140.80", "minority_interest_end": "3827715536.11",
           "total_equity_end": "57007650676.91", "parent_net_profit": "8452859993.18",
           "total_net_profit": "8463710355.65", "operating_cash_flow": "21739740393.38", "capex": "3978318320.96"}
PRIOR = {"attributable_equity_end": "53539331413.16", "minority_interest_end": "3781026029.25",
         "total_equity_end": "57320357442.41", "parent_net_profit": "10428540457.94",
         "total_net_profit": "10284306198.28", "operating_cash_flow": "18290357650.56", "capex": "6955597704.25"}


class TenthAnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600887-plan.json").read_bytes()
        cls.plan = json.loads(cls.plan_raw)
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600887-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.raw_dir = ROOT / Path(cls.source["pdf_path"]).parent
        cls.capture_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600887-capture.json").read_bytes()
        cls.capture = json.loads(cls.capture_raw)
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-600887-2026-10-03-v1"
        cls.replay = replay_frozen_bundle(cls.scope_path, cls.result_dir, cls.plan["parser_commit"])
        cls.report = cls.replay["report"]
        cls.bundle = cls.report["bundles"][0]

    def test_six_blobs_match_frozen_commit_not_future_code(self):
        self.assertEqual(self.plan["parser_commit"], "33f10ff028e760a275303eaf80a056c7a682cb8c")
        self.assertEqual(set(self.plan["parser_code_sha256"]), set(SOURCE_PATHS))
        self.assertEqual(self.plan["parser_code_sha256"], self.report["manifest"]["code_sha256"])
        for name, digest in self.plan["parser_code_sha256"].items():
            raw = subprocess.check_output(["git", "show", f"{self.plan['parser_commit']}:{name}"], cwd=ROOT)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)

    def test_metadata_only_no_body_or_repair_before_first_run(self):
        protocol = self.plan["protocol"]
        self.assertIn("metadata_only_not_financial_values_or_layout", protocol["selection_basis"])
        for key in ("pdf_body_inspected_before_first_run", "parser_edited_before_first_run", "fixes_in_this_run"):
            self.assertFalse(protocol[key])
        self.assertTrue(protocol["first_run_before_manual_source_review"])

    def test_preliminary_endpoint_errors_explicit_not_disclosure_absence(self):
        protocol = self.plan["protocol"]
        self.assertEqual(protocol["preliminary_security_lookup_request_count"], 3)
        self.assertEqual([r["http_status"] for r in protocol["preliminary_security_lookup_failures"]], [500, 404])
        self.assertTrue(protocol["successful_security_lookup_url"].endswith("/topSearch/query"))
        self.assertEqual(protocol["official_javascript_metadata_endpoint_read_count"], 1)

    def test_plan_scope_and_capture_hashes_and_byte_copies(self):
        self.assertEqual(hashlib.sha256(self.plan_raw).hexdigest(), self.capture["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.capture["scope_sha256"])
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.capture_raw, (self.raw_dir / "capture.json").read_bytes())

    def test_exact_two_formal_reads_and_source_hash(self):
        self.assertEqual(self.plan["protocol"]["capture_request_limit"], 2)
        self.assertFalse(self.plan["protocol"]["automatic_retry_or_third_party_fallback"])
        self.assertEqual([r["method"] for r in self.capture["resources"]], ["POST", "GET"])
        for item in self.capture["resources"]:
            raw = (self.raw_dir / item["name"]).read_bytes()
            self.assertEqual((hashlib.sha256(raw).hexdigest(), len(raw)), (item["sha256"], item["bytes"]))
            self.assertEqual(item["http_status"], 200)
        self.assertEqual(self.source["page_count"], 270)
        self.assertEqual(self.source["pdf_sha256"], "a82a81e52f52da3cd1b7f38ded08625dc18e3d4522b15d3ef76bf921e54c1f43")

    def test_full_report_not_summary_and_no_reference_input_splicing(self):
        selected = select_source(self.catalogue_raw, self.plan)
        self.assertEqual(selected["announcementId"], "1223421123")
        self.assertEqual({r["announcementId"] for r in json.loads(self.catalogue_raw)["announcements"]},
                         {"1223421123", "1223421131"})
        self.assertEqual(json.loads(self.scope_raw)["reference_reports"], [])

    def test_title_URL_security_or_org_drift_hard_fail(self):
        for key in ("announcementTitle", "adjunctUrl", "secCode", "orgId"):
            value = json.loads(self.catalogue_raw)
            next(r for r in value["announcements"] if r["announcementId"] == "1223421123")[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_duplicate_and_incomplete_catalogue_hard_fail(self):
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

    def test_actual_frozen_CLI_first_JSON_and_markdown_bytes(self):
        self.assertEqual(self.replay["verified_code_files"], 6)
        self.assertEqual(self.replay["json_sha256"], "4ec8245311f3590f0656eae317d75f51a0786a5affabe6701caba5a6dc0d76e0")
        self.assertEqual(self.replay["markdown_sha256"], "ff68ba401e26b6838ceb50dde76c1a4f2dcb1f3dce8816e2c741b7db36df56b6")
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), markdown(self.report))

    def test_hash_excludes_only_own_top_level_field(self):
        self.assertEqual(self.report["logical_content_hash"], content_hash({k: v for k, v in self.report.items()
                                                                         if k != "logical_content_hash"}))
        self.assertEqual(self.report["logical_content_hash"], "881bbe487f1f1cc36a5c8d26c631e18fee72c612501b23394071da16296aba75")

    def test_currency_uses_legacy_direct_statement_not_new_intro_inference(self):
        self.assertEqual(self.bundle["currency"], "CNY")
        self.assertNotIn("currency_intro_observation", self.bundle)
        evidence = self.bundle["currency_evidence"][0]
        self.assertEqual((evidence["declaration_text"], evidence["physical_page"]),
                         ("本公司的记账本位币为人民币。", 106))
        self.assertEqual((evidence["policy_heading_physical_page"], evidence["policy_end_physical_page"]), (105, 149))
        self.assertEqual(evidence["document_sha256"], self.source["pdf_sha256"])

    def test_seven_current_values_observed_with_individual_source_bindings(self):
        pages = dict.fromkeys(("attributable_equity_end", "minority_interest_end", "total_equity_end"), 88)
        pages.update(parent_net_profit=92, total_net_profit=92, operating_cash_flow=94, capex=95)
        self.assertEqual(set(self.bundle["fields"]), set(self.plan["expected_field_names"]))
        for key, expected in CURRENT.items():
            field = self.bundle["fields"][key]
            self.assertEqual((field["observed_value_cny"], field["state"]), (expected, "OBSERVED_NUMERIC"))
            self.assertEqual(len(field["candidates"]), 1)
            binding = field["candidates"][0]["binding"]
            self.assertEqual((binding["physical_page"], binding["statement_scope"], binding["document_sha256"]),
                             (pages[key], "CONSOLIDATED", self.source["pdf_sha256"]))
            self.assertFalse(binding["pit_admitted"])

    def test_comparatives_remain_separate_not_original_2023_evidence(self):
        for key, value in PRIOR.items():
            self.assertEqual(self.bundle["fields"][key]["comparative_not_target_value_cny"], value)
            self.assertNotEqual(value, CURRENT[key])

    def test_headers_keep_native_years_units_and_parent_boundaries(self):
        for kind, header_page, end_page in (("balance", 87, 89), ("income", 91, 93), ("cashflow", 94, 96)):
            table = self.bundle["table_states"][kind]
            self.assertEqual(table["state"], "NATIVE_TWO_COLUMN_OBSERVATIONS")
            self.assertEqual((table["header"]["physical_page"], table["header"]["unit_multiplier"],
                              table["end_boundary"]["physical_page"]), (header_page, 1, end_page))
            self.assertIn("2024", table["header"]["current_column"])
            self.assertIn("2023", table["header"]["comparative_column"])
            self.assertFalse(table["completeness_certified"])

    def test_four_exact_reconciliations_not_whole_statement_certification(self):
        self.assertEqual(len(self.bundle["reconciliations"]), 4)
        self.assertEqual({r["difference_cny"] for r in self.bundle["reconciliations"]}, {"0.00"})
        for values in (CURRENT, PRIOR):
            self.assertEqual(Decimal(values["attributable_equity_end"]) + Decimal(values["minority_interest_end"]),
                             Decimal(values["total_equity_end"]))
        self.assertFalse(self.bundle["full_balance_sheet_semantics_certified"])

    def test_complex_note_reference_and_blanks_still_unknown_not_zero(self):
        rows = self.bundle["balance_sheet_row_inventory"]
        money = next(r for r in rows if r["source_label"] == "货币资金")
        self.assertEqual(money["note_column_observation"]["raw_text"], ["七（1）"])
        self.assertEqual(money["current"]["state"], "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
        self.assertIsNone(money["current"]["value_cny"])
        blank = next(r for r in rows if r["current"]["state"] == "BLANK_NOT_ZERO")
        self.assertIsNone(blank["current"]["value_cny"])

    def test_capex_payment_not_investment_subtotal_or_parent_observation(self):
        row = self.bundle["fields"]["capex"]["candidates"][0]
        self.assertEqual(row["source_label"], "购建固定资产、无形资产和其他长期资产支付的现金")
        self.assertNotEqual(row["current"]["value_cny"], "38437468857.31")
        self.assertNotEqual(row["current"]["value_cny"], "775497717.02")
        self.assertNotEqual(self.bundle["fields"]["operating_cash_flow"]["observed_value_cny"], "17916865066.69")

    def test_lease_audit_and_version_chain_stay_unknown(self):
        lease = self.bundle["lease_financing_component"]
        self.assertIsNone(lease["observed_value_cny"])
        self.assertIsNone(lease["full_lease_cash_not_already_deducted"])
        self.assertFalse(lease["is_complete_lease_cash"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")

    def test_metadata_time_and_numeric_success_not_PIT_or_ready(self):
        self.assertEqual(self.capture["catalogue_time_raw_ms"], 1745942400000)
        self.assertIsNone(self.capture["exact_available_at_utc"])
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        for key in ("screening_input_exported", "real_pit_run_authorized", "production_reader_ready", "official_selection"):
            self.assertFalse(self.report[key])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_current_cold_warm_deterministic_without_rewriting_first_identity(self):
        cache = PDFCache()
        a, b = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(markdown(a), markdown(b))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))


if __name__ == "__main__":
    unittest.main()
