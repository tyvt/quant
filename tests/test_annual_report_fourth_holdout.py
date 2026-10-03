"""Fourth issuer first blind failure remains reproducible with frozen Git code.

Source review happens after the first JSON/Markdown. Never inject human values
or bypass the currency guard to relabel this first result as a successful parse.
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


class FourthAnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_path = ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600276-plan.json"
        cls.plan_raw = cls.plan_path.read_bytes()
        cls.plan = json.loads(cls.plan_raw)
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600276-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.raw_dir = ROOT / Path(cls.source["pdf_path"]).parent
        cls.capture_path = ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600276-capture.json"
        cls.record_raw = cls.capture_path.read_bytes()
        cls.record = json.loads(cls.record_raw)
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-600276-2026-10-03-v1"
        cls.report = replay_frozen_bundle(cls.scope_path, cls.result_dir, cls.plan["parser_commit"])["report"]
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = PDFCache().parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])

    def test_parser_frozen_to_repair_commit_before_new_source(self):
        self.assertEqual(self.plan["parser_commit"], "54d91210c65d2459dd4d5bc29bb3bce8a8ff6ab5")
        self.assertEqual(self.report["manifest"]["code_sha256"], self.plan["parser_code_sha256"])
        self.assertFalse(self.plan["protocol"]["parser_edited_before_first_run"])
        self.assertFalse(self.plan["protocol"]["pdf_body_inspected_before_first_run"])
        self.assertTrue(self.plan["protocol"]["first_run_before_manual_source_review"])
        self.assertFalse(self.plan["protocol"]["fixes_in_this_run"])

    def test_capture_binds_frozen_plan_scope_and_identical_index_bytes(self):
        self.assertEqual(hashlib.sha256(self.plan_raw).hexdigest(), self.record["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.record["scope_sha256"])
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.record_raw, (self.raw_dir / "capture.json").read_bytes())
        self.assertEqual(self.record["source"], self.source)
        self.assertEqual(hashlib.sha256((ROOT / "scripts/pilots/capture_annual_holdout.py").read_bytes()).hexdigest(),
                         self.record["capture_code_sha256"])

    def test_exact_official_capture_resources_have_unchanged_hashes(self):
        self.assertEqual(len(self.record["resources"]), 2)
        for resource in self.record["resources"]:
            raw = (self.raw_dir / resource["name"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), resource["sha256"])
            self.assertEqual(len(raw), resource["bytes"])
            self.assertEqual(resource["http_status"], 200)
        self.assertEqual(len(self.pdf.pages), 249)
        self.assertEqual(self.pdf.sha256, "7fad40fef23755f81ce5322f45483ea257ef026ebf1f7f5655c8d5998d7049fc")

    def test_catalogue_selects_full_report_not_summary(self):
        row = select_source(self.catalogue_raw, self.plan)
        self.assertEqual(row["announcementId"], "1222961962")
        self.assertEqual(row["announcementTitle"], "恒瑞医药2024年年度报告")
        summaries = [row for row in json.loads(self.catalogue_raw)["announcements"] if "摘要" in row["announcementTitle"]]
        self.assertEqual([row["announcementId"] for row in summaries], ["1222961969"])

    def test_catalogue_url_or_issuer_drift_still_rejected(self):
        for name in ("adjunctUrl", "orgId", "secCode"):
            value = json.loads(self.catalogue_raw)
            row = next(row for row in value["announcements"] if row["announcementId"] == "1222961962")
            row[name] = "wrong"
            with self.subTest(field=name), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_current_catalogue_datetime_and_fetches_are_not_PIT(self):
        self.assertEqual(self.record["catalogue_time_raw_ms"], 1743350400000)
        self.assertIsNone(self.record["exact_available_at_utc"])
        self.assertFalse(self.record["pdf_body_read"])
        self.assertFalse(self.record["complete_revision_chain_verified"])
        self.assertFalse(self.record["snapshot_published"])
        self.assertFalse(self.record["production_reader_ready"])

    def test_frozen_first_failure_json_and_markdown_replay_exactly(self):
        self.assertEqual((self.result_dir / "diagnostic-only.json").read_bytes(), canonical_bytes(self.report) + b"\n")
        self.assertEqual((self.result_dir / "diagnostic-only.md").read_bytes(), markdown(self.report))
        self.assertEqual(hashlib.sha256((self.result_dir / "diagnostic-only.json").read_bytes()).hexdigest(),
                         "75c9b75d6ef2343351ab4e742aedb0d28c5c42a7aebbdcb1e731b09d7ab65e3f")
        self.assertEqual(hashlib.sha256((self.result_dir / "diagnostic-only.md").read_bytes()).hexdigest(),
                         "f2744859e7451655ca6210a639613f06f94528dde0d4d9497b197fe833c603b1")

    def test_self_hash_excludes_only_own_top_level_key(self):
        self.assertEqual(self.report["logical_content_hash"],
                         content_hash({key: value for key, value in self.report.items() if key != "logical_content_hash"}))
        self.assertEqual(self.report["logical_content_hash"], "6e8c328eb900f442171bc93342b55d6fab11994d0df14887911a68fcc9ad5102")

    def test_one_cold_parse_then_cache_hit_deterministic(self):
        cache = PDFCache()
        first, second = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))

    def test_currency_failure_blocks_all_three_primary_tables(self):
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual(self.bundle["currency_evidence"], [])
        self.assertEqual(self.bundle["currency_evidence_pages"], [])
        self.assertEqual(set(self.bundle["table_states"]), {"balance", "income", "cashflow"})
        self.assertEqual({table["state"] for table in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})

    def test_unknown_seven_fields_are_not_zero_or_backfilled(self):
        self.assertEqual(set(self.bundle["fields"]), set(self.plan["expected_field_names"]))
        for field in self.bundle["fields"].values():
            self.assertIsNone(field["observed_value_cny"])
            self.assertIsNone(field["comparative_not_target_value_cny"])
            self.assertEqual(field["state"], "NOT_IDENTIFIED")
            self.assertEqual(field["candidates"], [])
        self.assertEqual(self.bundle["balance_sheet_row_inventory"], [])
        self.assertEqual({check["state"] for check in self.bundle["reconciliations"]}, {"UNKNOWN"})

    def test_source_really_declares_currency_but_not_in_supported_word_order(self):
        page = self.pdf.pages[156]
        self.assertIn("记账本位币", page.text)
        self.assertIn("本公司的记账本位币为人民币。", compact(page.text))
        self.assertNotIn("本公司以人民币为记账本位币", compact(page.text))
        # This source check is post-blind; it does not change the frozen failure.
        self.assertIsNone(self.bundle["currency"])

    def test_native_tables_show_values_without_injecting_human_observations(self):
        for number, tokens in {145: ("45,519,861,860.32", "570,388,872.99", "46,090,250,733.31"),
                               147: ("6,336,527,014.75", "6,336,994,647.53"),
                               149: ("7,422,753,038.71", "1,969,197,487.86")}.items():
            for token in tokens:
                self.assertIn(token, self.pdf.pages[number - 1].text)
        self.assertIsNone(self.bundle["fields"]["operating_cash_flow"]["observed_value_cny"])

    def test_table_headers_show_currency_and_complex_notes_not_globally_ignored(self):
        for number in (144, 146, 149):
            self.assertIn("币种：人民币", compact(self.pdf.pages[number - 1].text))
        self.assertIn("七、78（1）", compact(self.pdf.pages[148].text))
        self.assertIn("母公司资产负债表", self.pdf.pages[144].text)
        self.assertIn("母公司现金流量表", self.pdf.pages[149].text)

    def test_lease_audit_and_version_remain_unknown_not_certified(self):
        self.assertIsNone(self.bundle["lease_financing_component"]["observed_value_cny"])
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")
        self.assertEqual(self.bundle["source"]["version"], "declared_2024_annual_report")

    def test_no_screening_export_or_historical_admission(self):
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["screening_input_exported"])
        self.assertFalse(self.report["real_pit_run_authorized"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_no_reference_or_issuer_mixing(self):
        self.assertEqual(json.loads(self.scope_raw)["reference_reports"], [])
        self.assertEqual(len(self.report["bundles"]), 1)
        self.assertEqual(self.bundle["source"]["security_id"], "sh.600276")
        self.assertEqual(self.bundle["source"]["issuer"], "江苏恒瑞医药股份有限公司")


if __name__ == "__main__":
    unittest.main()
