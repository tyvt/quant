"""Eighth unseen issuer: immutable first failure, before any source inspection."""

import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from scripts.extract_annual_report_bundle import ROOT, SOURCE_PATHS, build_bundle, markdown
from scripts.parsing.annual_report_parser import _currency_section, _lines, _title
from scripts.parsing.field_binder import compact
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import select_source
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class EighthAnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600066-plan.json").read_bytes()
        cls.plan = json.loads(cls.plan_raw)
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600066-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.raw_dir = ROOT / Path(cls.source["pdf_path"]).parent
        cls.capture_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600066-capture.json").read_bytes()
        cls.capture = json.loads(cls.capture_raw)
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-600066-2026-10-03-v1"
        cls.replayed = replay_frozen_bundle(cls.scope_path, cls.result_dir, cls.plan["parser_commit"])
        cls.report = cls.replayed["report"]
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = PDFCache().parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])

    def test_frozen_code_matches_first_manifest_and_commit(self):
        self.assertEqual(self.plan["parser_commit"], "d08668ab0aadf84b9925a08adbeda8148f13710a")
        self.assertEqual(set(self.plan["parser_code_sha256"]), set(SOURCE_PATHS))
        self.assertEqual(self.plan["parser_code_sha256"], self.report["manifest"]["code_sha256"])
        # Bind historical blobs, not whatever parser a later repair installs.
        for name, digest in self.plan["parser_code_sha256"].items():
            blob = subprocess.check_output(["git", "show", f"{self.plan['parser_commit']}:{name}"], cwd=ROOT)
            self.assertEqual(hashlib.sha256(blob).hexdigest(), digest)

    def test_protocol_freezes_order_and_no_selection_by_layout_or_amount(self):
        protocol = self.plan["protocol"]
        for key in ("pdf_body_inspected_before_first_run", "parser_edited_before_first_run", "fixes_in_this_run"):
            self.assertFalse(protocol[key])
        self.assertTrue(protocol["first_run_before_manual_source_review"])
        self.assertIn("metadata_only_not_financial_values_or_layout", protocol["selection_basis"])
        self.assertEqual(protocol["preliminary_security_lookup_request_count"], 1)
        self.assertEqual(protocol["preliminary_catalogue_request_count"], 1)
        self.assertIn("not_disclosure_absence", protocol["official_homepage_browser_attempt"])

    def test_plan_and_scope_hashes_bind_capture(self):
        self.assertEqual(hashlib.sha256(self.plan_raw).hexdigest(), self.capture["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.capture["scope_sha256"])
        self.assertEqual(self.source, self.capture["source"])

    def test_tracked_capture_and_inputs_are_original_generated_bytes(self):
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.capture_raw, (self.raw_dir / "capture.json").read_bytes())

    def test_only_two_official_capture_reads_bind_complete_raw_bytes(self):
        self.assertEqual(self.plan["protocol"]["capture_request_limit"], 2)
        self.assertFalse(self.plan["protocol"]["automatic_retry_or_third_party_fallback"])
        self.assertEqual([r["method"] for r in self.capture["resources"]], ["POST", "GET"])
        for resource in self.capture["resources"]:
            raw = (self.raw_dir / resource["name"]).read_bytes()
            self.assertEqual(resource["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(resource["bytes"], len(raw))
            self.assertEqual(resource["http_status"], 200)
        self.assertEqual(len(self.pdf.pages), 158)
        self.assertEqual(self.pdf.sha256, "5edfe6e4ac095d6c28e17903cc87e284b5d8f75ba3be3f4515a0fbb92f5bc023")

    def test_selected_full_report_not_summary(self):
        row = select_source(self.catalogue_raw, self.plan)
        self.assertEqual((row["announcementId"], row["announcementTitle"]), ("1222974533", "2024年年度报告"))
        rows = json.loads(self.catalogue_raw)["announcements"]
        self.assertEqual({r["announcementId"] for r in rows}, {"1222974533", "1222974523"})
        self.assertEqual(json.loads(self.scope_raw)["reference_reports"], [])

    def test_catalogue_identity_title_and_URL_drift_hard_fail(self):
        for key in ("secCode", "orgId", "announcementTitle", "adjunctUrl"):
            value = json.loads(self.catalogue_raw)
            next(r for r in value["announcements"] if r["announcementId"] == "1222974533")[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_duplicate_ID_and_incomplete_catalogue_hard_fail(self):
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

    def test_frozen_Git_replay_generates_first_JSON_and_markdown_byte_exact(self):
        self.assertEqual(self.replayed["verified_code_files"], 6)
        self.assertEqual(self.replayed["code_commit"], self.plan["parser_commit"])
        self.assertEqual(self.replayed["json_sha256"], "f079521b6c017b45ae4c89e8a5c275308f1a92bd2dcde3e552f9b29d20ef57e9")
        self.assertEqual(self.replayed["markdown_sha256"], "de2f366b8be1e6249f6c5b568441a5da1468a6102b24be039051a53510ee6d93")
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), markdown(self.report))

    def test_canonical_hash_excludes_only_self_field(self):
        self.assertEqual(self.report["logical_content_hash"], content_hash({k: v for k, v in self.report.items()
                                                                         if k != "logical_content_hash"}))
        self.assertEqual(self.report["logical_content_hash"], "ec7af2ae4efc412bca88c138e360cd1a75fb29f639f2f8cce14172a6ebe093ad")

    def test_document_passes_but_currency_blocks_all_three_tables(self):
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual(self.bundle["currency_evidence"], [])
        self.assertEqual(self.bundle["currency_evidence_pages"], [])
        self.assertEqual({t["state"] for t in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})
        self.assertNotIn("currency_subsection_observation", self.bundle)

    def test_no_manual_values_or_candidates_injected(self):
        self.assertEqual(set(self.bundle["fields"]), set(self.plan["expected_field_names"]))
        for field in self.bundle["fields"].values():
            self.assertIsNone(field["observed_value_cny"])
            self.assertIsNone(field["comparative_not_target_value_cny"])
            self.assertEqual(field["state"], "NOT_IDENTIFIED")
            self.assertEqual(field["candidates"], [])
        self.assertEqual(self.bundle["balance_sheet_row_inventory"], [])
        self.assertEqual({r["state"] for r in self.bundle["reconciliations"]}, {"UNKNOWN"})

    def test_post_blind_cover_identity_matches_declared_source(self):
        text = compact(self.pdf.pages[0].text)
        for expected in (self.source["issuer"], "600066", "2024年年度报告"):
            self.assertIn(expected, text)

    def test_post_blind_chinese_parenthesized_subsection_is_unrecognized(self):
        rows = [compact("".join(w.text for w in group)) for group in _lines(self.pdf.pages[70].words)]
        self.assertIn("五、重要会计政策及会计估计", rows)
        index = rows.index("(四)记账本位币")
        self.assertEqual(rows[index + 1], "本公司的记账本位币为人民币。")
        self.assertEqual(rows[index + 2], "(五)重要性标准确定方法和选择依据")
        self.assertIn("六、税项", compact(self.pdf.pages[97].text))
        self.assertEqual(_title(rows[index]), "(四)记账本位币")
        self.assertIsNone(_currency_section(self.pdf))

    def test_post_blind_subsidiary_currency_rows_not_issuer_policy(self):
        self.assertIn("子公司名称", compact(self.pdf.pages[127].text))
        self.assertIn("记账本位币", compact(self.pdf.pages[127].text))
        self.assertIsNone(self.bundle["currency"])

    def test_lease_audit_and_version_chain_not_promoted(self):
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertFalse(self.bundle["lease_financing_component"]["is_complete_lease_cash"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertIsNone(self.bundle["audit_text_observation"]["latest_audit_unmodified_pit"])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")

    def test_metadata_time_and_diagnostic_not_PIT_or_production_permission(self):
        self.assertEqual(self.capture["catalogue_time_raw_ms"], 1743436800000)
        self.assertIsNone(self.capture["exact_available_at_utc"])
        for key in ("pdf_body_read", "complete_revision_chain_verified", "snapshot_published", "production_reader_ready"):
            self.assertFalse(self.capture[key])
        self.assertEqual(self.report["timing_policy"], "UNKNOWN_UNLESS_VERIFIED")
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        for key in ("screening_input_exported", "real_pit_run_authorized", "production_reader_ready"):
            self.assertFalse(self.report[key])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_current_cold_warm_replay_keeps_all_unknowns(self):
        cache = PDFCache()
        a, b = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(markdown(a), markdown(b))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))
        self.assertEqual(a["logical_content_hash"], self.report["logical_content_hash"])


if __name__ == "__main__":
    unittest.main()
