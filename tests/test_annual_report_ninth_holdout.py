"""Ninth metadata-selected issuer; actual frozen first failure, not a repair."""

import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from scripts.extract_annual_report_bundle import ROOT, SOURCE_PATHS, build_bundle, markdown
from scripts.parsing.annual_report_parser import _currency_section, _lines
from scripts.parsing.field_binder import compact
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import select_source
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class NinthAnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600309-plan.json").read_bytes()
        cls.plan = json.loads(cls.plan_raw)
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600309-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.raw_dir = ROOT / Path(cls.source["pdf_path"]).parent
        cls.capture_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600309-capture.json").read_bytes()
        cls.capture = json.loads(cls.capture_raw)
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-600309-2026-10-03-v1"
        cls.replay = replay_frozen_bundle(cls.scope_path, cls.result_dir, cls.plan["parser_commit"])
        cls.report = cls.replay["report"]
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = PDFCache().parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])

    def test_first_code_identity_matches_six_frozen_blobs(self):
        self.assertEqual(self.plan["parser_commit"], "9d160ad945a6237d844f08b5da28d670e4856512")
        self.assertEqual(self.plan["parser_code_sha256"], self.report["manifest"]["code_sha256"])
        self.assertEqual(set(self.plan["parser_code_sha256"]), set(SOURCE_PATHS))
        for name, digest in self.plan["parser_code_sha256"].items():
            blob = subprocess.check_output(["git", "show", f"{self.plan['parser_commit']}:{name}"], cwd=ROOT)
            self.assertEqual(hashlib.sha256(blob).hexdigest(), digest)

    def test_metadata_only_selection_and_first_run_before_review(self):
        protocol = self.plan["protocol"]
        self.assertIn("metadata_only_not_financial_values_or_layout", protocol["selection_basis"])
        for key in ("pdf_body_inspected_before_first_run", "parser_edited_before_first_run", "fixes_in_this_run"):
            self.assertFalse(protocol[key])
        self.assertTrue(protocol["first_run_before_manual_source_review"])
        self.assertEqual(protocol["preliminary_security_lookup_request_count"], 1)
        self.assertEqual(protocol["preliminary_catalogue_request_count"], 1)
        self.assertEqual(protocol["preliminary_security_lookup_failures"], [])

    def test_plan_and_input_hashes_bind_capture(self):
        self.assertEqual(hashlib.sha256(self.plan_raw).hexdigest(), self.capture["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.capture["scope_sha256"])
        self.assertEqual(self.source, self.capture["source"])

    def test_tracked_capture_and_scope_are_original_bytes(self):
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.capture_raw, (self.raw_dir / "capture.json").read_bytes())

    def test_two_bounded_reads_and_complete_PDF_bytes(self):
        self.assertEqual(self.plan["protocol"]["capture_request_limit"], 2)
        self.assertFalse(self.plan["protocol"]["automatic_retry_or_third_party_fallback"])
        self.assertEqual([r["method"] for r in self.capture["resources"]], ["POST", "GET"])
        for item in self.capture["resources"]:
            raw = (self.raw_dir / item["name"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
            self.assertEqual(len(raw), item["bytes"])
            self.assertEqual(item["http_status"], 200)
        self.assertEqual(len(self.pdf.pages), 223)
        self.assertEqual(self.pdf.sha256, "0c37e70c554609f4a22990fd97f3da4ee92bb717e44d641ac7800083789d4df7")

    def test_explicit_full_report_not_summary(self):
        selected = select_source(self.catalogue_raw, self.plan)
        self.assertEqual((selected["announcementId"], selected["announcementTitle"]),
                         ("1223097325", "万华化学2024年年度报告"))
        self.assertEqual({r["announcementId"] for r in json.loads(self.catalogue_raw)["announcements"]},
                         {"1223097325", "1223097319"})
        self.assertEqual(json.loads(self.scope_raw)["reference_reports"], [])

    def test_identity_title_and_URL_drift_hard_fail(self):
        for key in ("secCode", "orgId", "announcementTitle", "adjunctUrl"):
            value = json.loads(self.catalogue_raw)
            next(r for r in value["announcements"] if r["announcementId"] == "1223097325")[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_duplicate_or_incomplete_catalogue_hard_fail(self):
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

    def test_frozen_CLI_executes_and_recreates_first_bytes(self):
        self.assertEqual(self.replay["verified_code_files"], 6)
        self.assertEqual(self.replay["json_sha256"], "421502a95c67414f67d9e8890e16f6088815731ada947f461b0c63bef97bff9c")
        self.assertEqual(self.replay["markdown_sha256"], "d514c7d03692dc7029e359bf708d39dd140b3f8731dc4240cf29d5f6ebf2e7cf")
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), markdown(self.report))

    def test_self_hash_excludes_only_top_level_hash(self):
        self.assertEqual(self.report["logical_content_hash"], content_hash({k: v for k, v in self.report.items()
                                                                         if k != "logical_content_hash"}))
        self.assertEqual(self.report["logical_content_hash"], "056d5a8110690fd77e31431a7d49a75a2e381c8f2c49c33df48d8baab4c6008f")

    def test_identity_passes_while_currency_blocks_tables(self):
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual(self.bundle["currency_evidence"], [])
        self.assertEqual({t["state"] for t in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})
        self.assertNotIn("currency_subsection_observation", self.bundle)

    def test_no_manual_amounts_candidates_or_reconciled_values(self):
        self.assertEqual(set(self.bundle["fields"]), set(self.plan["expected_field_names"]))
        for field in self.bundle["fields"].values():
            self.assertIsNone(field["observed_value_cny"])
            self.assertIsNone(field["comparative_not_target_value_cny"])
            self.assertEqual(field["state"], "NOT_IDENTIFIED")
            self.assertEqual(field["candidates"], [])
        self.assertEqual(self.bundle["balance_sheet_row_inventory"], [])
        self.assertEqual({r["state"] for r in self.bundle["reconciliations"]}, {"UNKNOWN"})

    def test_post_blind_cover_and_policy_boundaries_match_source(self):
        for text in (self.source["issuer"], "600309", "2024年年度报告"):
            self.assertIn(text, compact(self.pdf.pages[0].text))
        self.assertIn("五、重要会计政策及会计估计", compact(self.pdf.pages[93].text))
        self.assertIn("六、税项", compact(self.pdf.pages[115].text))

    def test_post_blind_supported_heading_does_not_solve_statement(self):
        section = _currency_section(self.pdf)
        self.assertIsNotNone(section)
        lines = section["lines"]
        self.assertEqual(lines[section["index"]][2], "4、记账本位币")
        self.assertEqual(lines[section["section_end"]][2], "5、重要性标准确定方法和选择依据")
        self.assertEqual(lines[section["index"]][0].number, 95)
        self.assertIsNone(self.bundle["currency"])

    def test_post_blind_narrative_prefix_and_split_joint_subject_not_injected(self):
        rows = [compact("".join(w.text for w in group)) for group in _lines(self.pdf.pages[94].words)]
        i = rows.index("4、记账本位币")
        self.assertEqual(rows[i + 1], "人民币为本公司及境内子公司经营所处的主要经济环境中的货币，本公司及境内")
        self.assertTrue(rows[i + 2].startswith("子公司以人民币为记账本位币。本公司之境外子公司"))
        self.assertIn("报表时所采用的货币为人民币。", rows)
        self.assertEqual(self.bundle["currency_evidence"], [])

    def test_lease_audit_and_version_chain_not_promoted(self):
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertFalse(self.bundle["lease_financing_component"]["is_complete_lease_cash"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertIsNone(self.bundle["audit_text_observation"]["latest_audit_unmodified_pit"])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")

    def test_metadata_time_not_PIT_or_production_permission(self):
        self.assertEqual(self.capture["catalogue_time_raw_ms"], 1744646400000)
        self.assertIsNone(self.capture["exact_available_at_utc"])
        for key in ("pdf_body_read", "complete_revision_chain_verified", "snapshot_published", "production_reader_ready"):
            self.assertFalse(self.capture[key])
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        for key in ("screening_input_exported", "real_pit_run_authorized", "production_reader_ready"):
            self.assertFalse(self.report[key])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_current_cold_warm_determinism_not_historical_first_identity_requirement(self):
        cache = PDFCache()
        a, b = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(markdown(a), markdown(b))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))


if __name__ == "__main__":
    unittest.main()
