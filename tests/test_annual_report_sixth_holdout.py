"""Sixth unseen issuer rejected before extraction; do not invent a normal bundle.

Offline replay executes frozen Git code. Source checks are post-blind evidence,
not an identity bypass, manual financial observations or historical PIT inputs.
"""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.extract_annual_report_bundle import ROOT, SOURCE_PATHS, build_bundle
from scripts.parsing.field_binder import compact
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import select_source
from scripts.pilots.replay_frozen_annual_rejection import replay_frozen_rejection
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class SixthAnnualHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_path = ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600585-plan.json"
        cls.plan_raw = cls.plan_path.read_bytes()
        cls.plan = json.loads(cls.plan_raw)
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600585-inputs.json"
        cls.scope_raw = cls.scope_path.read_bytes()
        cls.source = json.loads(cls.scope_raw)["sources"][0]
        cls.raw_dir = ROOT / Path(cls.source["pdf_path"]).parent
        cls.capture_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-holdout-600585-capture.json").read_bytes()
        cls.capture = json.loads(cls.capture_raw)
        cls.catalogue_raw = (cls.raw_dir / "catalogue.json").read_bytes()
        cls.result_dir = ROOT / "docs/data-pilots/annual-holdout-600585-2026-10-03-v1"
        cls.rejection_path = cls.result_dir / "rejection.json"
        cls.rejection_raw = cls.rejection_path.read_bytes()
        cls.rejection = json.loads(cls.rejection_raw)
        cls.replayed = replay_frozen_rejection(cls.plan_path, cls.scope_path, cls.rejection_path)
        cls.pdf = PDFCache().parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])

    def reject_variant(self, update, *, reseal=True):
        record = copy.deepcopy(self.rejection)
        update(record)
        if reseal:
            record["logical_content_hash"] = content_hash(
                {k: v for k, v in record.items() if k != "logical_content_hash"})
        with tempfile.TemporaryDirectory(prefix="rejection-test-") as directory:
            path = Path(directory) / "rejection.json"
            path.write_bytes(canonical_bytes(record) + b"\n")
            with self.assertRaises(ValueError):
                replay_frozen_rejection(self.plan_path, self.scope_path, path)

    def test_plan_frozen_before_blind_phase_with_no_sample_specific_repairs(self):
        self.assertEqual(self.plan["parser_commit"], "6fa22fd9d312b708e7a1295f1aeec9637c8fb6e1")
        self.assertEqual(self.rejection["manifest"]["code_sha256"], self.plan["parser_code_sha256"])
        self.assertEqual(set(self.plan["parser_code_sha256"]), set(SOURCE_PATHS))
        for name in ("parser_edited_before_first_run", "pdf_body_inspected_before_first_run", "fixes_in_this_run"):
            self.assertFalse(self.plan["protocol"][name])
        self.assertTrue(self.plan["protocol"]["first_run_before_manual_source_review"])

    def test_scope_capture_and_plan_bytes_remain_bound(self):
        self.assertEqual(hashlib.sha256(self.plan_raw).hexdigest(), self.capture["plan_sha256"])
        self.assertEqual(hashlib.sha256(self.scope_raw).hexdigest(), self.capture["scope_sha256"])
        self.assertEqual(self.scope_raw, (self.raw_dir / "scope.json").read_bytes())
        self.assertEqual(self.capture_raw, (self.raw_dir / "capture.json").read_bytes())
        self.assertEqual(self.source, self.capture["source"])
        self.assertEqual(hashlib.sha256((ROOT / "scripts/pilots/capture_annual_holdout.py").read_bytes()).hexdigest(),
                         self.capture["capture_code_sha256"])

    def test_two_capture_requests_have_complete_raw_hashes(self):
        self.assertEqual([r["method"] for r in self.capture["resources"]], ["POST", "GET"])
        for resource in self.capture["resources"]:
            raw = (self.raw_dir / resource["name"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), resource["sha256"])
            self.assertEqual(len(raw), resource["bytes"])
            self.assertEqual(resource["http_status"], 200)
        self.assertEqual(len(self.pdf.pages), 281)
        self.assertEqual(self.pdf.sha256, "9ec252361911db404539df2230d83ef1b263f169753e48438657e8c8a36facef")

    def test_metadata_reads_not_hidden_in_capture_limit(self):
        protocol = self.plan["protocol"]
        self.assertEqual(protocol["preliminary_catalogue_request_count"], 1)
        self.assertEqual(protocol["preliminary_security_lookup_request_count"], 1)
        self.assertEqual(protocol["capture_request_limit"], 2)
        self.assertFalse(protocol["automatic_retry_or_third_party_fallback"])
        self.assertEqual(self.plan["catalogue_payload"]["stock"], "600585,gssh0600585")

    def test_specified_full_report_not_summary_is_captured(self):
        row = select_source(self.catalogue_raw, self.plan)
        self.assertEqual((row["announcementId"], row["announcementTitle"]), ("1222882790", "2024年度报告"))
        self.assertEqual({r["announcementId"] for r in json.loads(self.catalogue_raw)["announcements"]},
                         {"1222882790", "1222882791"})
        self.assertEqual(json.loads(self.scope_raw)["reference_reports"], [])
        self.assertEqual(self.source["announcement_id"], "1222882790")

    def test_catalogue_identity_or_full_title_drift_rejected(self):
        for key in ("secCode", "orgId", "adjunctUrl", "announcementTitle"):
            value = json.loads(self.catalogue_raw)
            next(r for r in value["announcements"] if r["announcementId"] == "1222882790")[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_duplicate_catalogue_ids_rejected(self):
        value = json.loads(self.catalogue_raw)
        value["announcements"][0]["announcementId"] = value["announcements"][1]["announcementId"]
        with self.assertRaises(ValueError):
            select_source(json.dumps(value).encode("utf-8"), self.plan)

    def test_canonical_frozen_rejection_and_self_hash(self):
        self.assertEqual(self.rejection_raw, canonical_bytes(self.rejection) + b"\n")
        self.assertEqual(hashlib.sha256(self.rejection_raw).hexdigest(),
                         "0e16d62643fef6b7b95a88427b3ca6573f556e3685ddd52891885d520301168b")
        self.assertEqual(self.rejection["logical_content_hash"],
                         content_hash({k: v for k, v in self.rejection.items() if k != "logical_content_hash"}))
        self.assertEqual(self.rejection["logical_content_hash"],
                         "cce7a4a8d9a30f2546003a7f226e0ef3321a2e3681ab006f8476dee441e51749")

    def test_process_outcome_is_cli_exit_two_with_exact_stderr_bytes(self):
        process = self.rejection["process"]
        self.assertEqual(process["exit_code"], 2)
        self.assertEqual(process["stdout_utf8"], "")
        self.assertEqual(process["stderr_utf8"].encode("utf-8"),
                         b"annual source extraction stopped: issuer, annual period or security identity absent/mismatched\r\n")
        self.assertTrue(process["confirmed_against_first_cli_tool_output"])

    def test_frozen_git_execution_recreates_rejection_not_normal_report(self):
        self.assertEqual(self.replayed["code_commit"], self.plan["parser_commit"])
        self.assertEqual(self.replayed["verified_code_files"], 6)
        self.assertEqual(self.replayed["exit_code"], 2)
        self.assertFalse(self.replayed["normal_bundle_created"])
        self.assertTrue(self.replayed["support_code_sha256"])
        self.assertFalse((self.result_dir / "diagnostic-only.json").exists())
        self.assertFalse((self.result_dir / "diagnostic-only.md").exists())

    def test_current_parser_also_rejects_without_bypass_or_field_injection(self):
        with self.assertRaisesRegex(ValueError, "issuer, annual period or security identity"):
            build_bundle(self.scope_raw)
        for key in ("bundles", "fields", "reconciliations"):
            self.assertNotIn(key, self.rejection)

    def test_post_blind_cover_has_real_identity_but_unsupported_annual_title(self):
        text = compact(self.pdf.pages[0].text)
        self.assertIn(self.source["issuer"], text)
        self.assertIn("600585", text)
        self.assertIn("00914", text)
        self.assertIn("二〇二四年度报告", text)
        self.assertNotIn("2024年年度报告", "".join(compact(p.text) for p in self.pdf.pages))

    def test_post_blind_period_and_accounting_bases_not_promoted_to_inputs(self):
        self.assertIn("2024年1月1日至2024年12月31日", compact(self.pdf.pages[5].text))
        self.assertIn("国际财务报告准则", compact(self.pdf.pages[8].text))
        self.assertIn("千元", compact(self.pdf.pages[8].text))
        self.assertIn("中国会计准则", compact(self.pdf.pages[9].text))
        self.assertIn("千元", compact(self.pdf.pages[9].text))
        self.assertFalse(self.rejection["screening_input_exported"])

    def test_directory_and_fetch_clocks_not_verified_historical_availability(self):
        self.assertEqual(self.capture["catalogue_time_raw_ms"], 1742832000000)
        self.assertIsNone(self.capture["exact_available_at_utc"])
        self.assertFalse(self.capture["pdf_body_read"])
        for name in ("complete_revision_chain_verified", "snapshot_published", "production_reader_ready"):
            self.assertFalse(self.capture[name])
        self.assertIsNone(self.rejection["diagnostic_available_at"])
        self.assertEqual(self.rejection["pit_admitted_observation_count"], 0)

    def test_rejection_is_not_a_screening_request_or_authorization(self):
        self.assertEqual(self.rejection["timing_policy"], "UNKNOWN_UNLESS_VERIFIED")
        for key in ("real_pit_run_authorized", "screening_input_exported", "production_reader_ready"):
            self.assertFalse(self.rejection[key])
        with self.assertRaises(ValueError):
            load_request(self.rejection_raw)

    def test_tampered_self_hash_rejected(self):
        self.reject_variant(lambda r: r["process"].update(stdout_utf8="invented"), reseal=False)

    def test_short_commit_rejected_even_with_resealed_json(self):
        self.reject_variant(lambda r: r["manifest"].update(parser_commit="6fa22fd"))

    def test_unapproved_code_path_rejected(self):
        self.reject_variant(lambda r: r["manifest"]["code_sha256"].update({"other.py": "0" * 64}))

    def test_wrong_frozen_rule_hash_rejected(self):
        self.reject_variant(lambda r: r["manifest"].update(rule_sha256="0" * 64))

    def test_runtime_version_drift_rejected(self):
        self.reject_variant(lambda r: r["manifest"].update(python_version="0.0.0"))
        self.reject_variant(lambda r: r["manifest"].update(pdf_backend={"name": "PyMuPDF", "version": "0.0.0"}))

    def test_source_scope_plan_identity_drift_rejected(self):
        self.reject_variant(lambda r: r["source"].update(announcement_id="wrong"))
        self.reject_variant(lambda r: r["manifest"].update(scope_sha256="0" * 64))
        self.reject_variant(lambda r: r["manifest"].update(plan_sha256="0" * 64))

    def test_nonzero_pit_normal_bundle_or_authorized_flags_rejected(self):
        for key, value in (("pit_admitted_observation_count", 1), ("normal_bundle_created", True),
                           ("real_pit_run_authorized", True), ("screening_input_exported", True),
                           ("production_reader_ready", True), ("diagnostic_available_at", "2025-03-25"),
                           ("timing_policy", "ASSUME_DIRECTORY_DATE")):
            with self.subTest(key=key):
                self.reject_variant(lambda r: r.update({key: value}))

    def test_success_exit_code_is_not_a_rejection(self):
        self.reject_variant(lambda r: r["process"].update(exit_code=0))

    def test_changed_replay_stderr_newline_is_not_byte_identical(self):
        original_run = subprocess.run

        def changed_run(args, **kwargs):
            if Path(args[0]).name.lower().startswith("git"):
                return original_run(args, **kwargs)
            return subprocess.CompletedProcess(args, 2, b"", self.rejection["process"]["stderr_utf8"].replace("\r\n", "\n").encode())

        with patch("scripts.pilots.replay_frozen_annual_rejection.subprocess.run", side_effect=changed_run):
            with self.assertRaisesRegex(ValueError, "not byte-identical"):
                replay_frozen_rejection(self.plan_path, self.scope_path, self.rejection_path)

    def test_replay_cannot_create_a_normal_bundle_even_with_matching_error(self):
        original_run = subprocess.run

        def creating_run(args, **kwargs):
            if Path(args[0]).name.lower().startswith("git"):
                return original_run(args, **kwargs)
            output = Path(args[args.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "diagnostic-only.json").write_bytes(b"{}\n")
            return subprocess.CompletedProcess(args, 2, b"", self.rejection["process"]["stderr_utf8"].encode())

        with patch("scripts.pilots.replay_frozen_annual_rejection.subprocess.run", side_effect=creating_run):
            with self.assertRaisesRegex(ValueError, "unexpectedly generated"):
                replay_frozen_rejection(self.plan_path, self.scope_path, self.rejection_path)


if __name__ == "__main__":
    unittest.main()
