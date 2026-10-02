"""Recovery and cross-process acceptance, not additional field supplementation."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from scripts import verify_workspace_integrity as integrity
from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import run_diagnostic_e2e as e2e


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceInsuranceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = integrity.read_json(ROOT / integrity.MANIFEST)

    def test_production_inventory_matches_538_file_reviewed_baseline(self):
        summary = integrity.verify_manifest(ROOT, self.manifest)
        self.assertEqual(summary["file_count"], 538)
        self.assertEqual(summary["inventory_sha256"], integrity.SNAPSHOT_SHA256)
        self.assertEqual(summary["rule_sha256"], integrity.RULE_SHA256)

    def test_inventory_altered_hash_or_missing_entry_fails(self):
        for mutate in (lambda value: value["files"][0].update(hash="0" * 64),
                       lambda value: value["files"].pop(),
                       lambda value: value.update(file_count=537)):
            altered = copy.deepcopy(self.manifest)
            mutate(altered)
            with patch.object(integrity, "capture_manifest", return_value=self.manifest):
                with self.assertRaisesRegex(ValueError, "inventory drift"):
                    integrity.verify_manifest(ROOT, altered)

    def test_inventory_cannot_silently_capture_a_new_baseline(self):
        with patch.object(integrity, "snapshot_inventory", return_value=self.manifest["files"][:-1]):
            with self.assertRaisesRegex(ValueError, "reviewed 538-file baseline"):
                integrity.capture_manifest(ROOT)

    def test_missing_raw_snapshots_is_failure_not_empty_coverage(self):
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(FileNotFoundError, "required local snapshots absent"):
                integrity.snapshot_inventory(Path(temporary))

    def test_inventory_encoding_keeps_original_path_then_hash_order(self):
        raw = b'[{"path":"storage/snapshots/a","hash":"ab"}]'
        import hashlib
        self.assertEqual(integrity.inventory_sha256([{"path": "storage/snapshots/a", "hash": "ab"}]),
                         hashlib.sha256(raw).hexdigest())

    def test_inventory_file_paths_cannot_escape_workspace(self):
        with self.assertRaisesRegex(ValueError, "unsafe or linked"):
            integrity.relative_file(ROOT, "../RULE_SPEC.md")

    def test_inventory_duplicate_keys_are_rejected(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_bytes(b'{"file_count":538,"file_count":0}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                integrity.read_json(path)

    def test_git_blob_preserves_approved_rule_and_frozen_files_exactly(self):
        result = integrity.verify_git_blobs(ROOT, [item["path"] for item in self.manifest["protected_files"]])
        self.assertEqual(result["verified_files"][0]["sha256"], integrity.RULE_SHA256)
        self.assertEqual(len(result["verified_files"]), 20)

    def test_storage_package_is_tracked_but_root_raw_data_is_not(self):
        tracked = integrity.git_bytes(ROOT, "ls-files", "-z").decode("utf-8").split("\0")
        self.assertIn("turtle_quant/storage/verification.py", tracked)
        self.assertFalse(any(path.startswith("storage/") for path in tracked))
        self.assertFalse(any("__pycache__/" in path or path.endswith(".pyc") for path in tracked))

    def test_git_attributes_disable_text_filters_and_ident(self):
        raw = integrity.git_bytes(ROOT, "check-attr", "text", "filter", "ident", "--",
                                  "RULE_SPEC.md", "docs/releases/v1.3.2.md").decode("utf-8")
        self.assertEqual(len(raw.splitlines()), 6)
        self.assertTrue(all(line.endswith(": unset") for line in raw.splitlines()))


class DiagnosticPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = {sample: integrity.read_json(ROOT / base.DEFAULT_OUTPUT / f"{sample}-diagnostic-only.json")
                       for sample in base.SAMPLE_SECURITIES}

    def report(self, sample="cashflow-000637"):
        return copy.deepcopy(self.reports[sample])

    def test_financial_gates_reach_needs_review_without_valuation(self):
        for sample in ("cashflow-000637", "financial-002570"):
            result = e2e.project_diagnostic(self.report(sample))
            self.assertEqual(len(result["rule_results"]), 6)
            self.assertTrue(all(gate["status"] == "UNKNOWN" and gate["value"] is None
                                for gate in result["rule_results"]))
            self.assertEqual(result["decision"]["kind"], "NEEDS_REVIEW")
            self.assertEqual(result["score_coverage"], "0")
            self.assertIsNone(result["quality_score"])
            self.assertEqual(result["valuation"]["execution"], "NOT_EXECUTED_UNKNOWN_DEPENDENCIES")

    def test_share_policy_gate_remains_unknown_through_pipeline(self):
        result = e2e.project_diagnostic(self.report("shares-000858"))
        self.assertEqual(result["decision"]["kind"], "NEEDS_REVIEW")
        self.assertTrue(result["rule_results"][0]["missing_fields"])
        self.assertIsNone(result["rule_results"][0]["value"])

    def test_buyback_evidence_does_not_fabricate_financial_premise(self):
        result = e2e.project_diagnostic(self.report("buybacks-600519"))
        self.assertEqual(result["decision"]["kind"], "NEEDS_REVIEW")
        self.assertEqual(len(result["rule_results"]), 1)
        self.assertEqual(result["rule_results"][0]["kind"], "EVIDENCE")
        self.assertNotIn("premise.roe_5y", result["decision"]["reasons"])
        self.assertIsNone(result["valuation"]["gg_pct"])

    def test_json_round_trip_preserves_diagnostic_pipeline_decisions(self):
        for report in self.reports.values():
            self.assertEqual(e2e.project_diagnostic(report),
                             e2e.project_diagnostic(json.loads(base.canonical_bytes(report))))

    def test_real_samples_remain_independent(self):
        results = [e2e.project_diagnostic(report) for report in self.reports.values()]
        self.assertEqual(len({item["security_id"] for item in results}), 4)
        self.assertEqual({item["as_of"] for item in results}, {"2026-09-30"})
        self.assertTrue(all(item["available_at"] is None and item["admitted_pit_observation_count"] == 0
                            for item in results))

    def test_unknown_pit_values_cannot_be_replaced_with_zero(self):
        report = self.report()
        report["source_observations"][0]["pit_value"] = "0"
        report["logical_content_hash"] = base.logical_content_hash(report)
        with self.assertRaisesRegex(ValueError, "admitted as PIT"):
            e2e.project_diagnostic(report)

    def test_availability_assumption_cannot_be_mislabeled_verified(self):
        report = self.report()
        report["timing_assumptions"]["available_at"] = "2026-04-30"
        report["logical_content_hash"] = base.logical_content_hash(report)
        with self.assertRaisesRegex(ValueError, "unverified availability"):
            e2e.project_diagnostic(report)

    def test_unknown_gate_cannot_be_given_numeric_value(self):
        report = self.report()
        report["observed_arithmetic_not_pit_rule_outputs"]["premise_execution"]["hard_gates"][0]["value"] = "0"
        report["logical_content_hash"] = base.logical_content_hash(report)
        with self.assertRaisesRegex(ValueError, "UNKNOWN / null"):
            e2e.project_diagnostic(report)

    def test_authority_upgrade_cannot_hide_behind_a_new_content_hash(self):
        report = self.report()
        report["official_selection"] = True
        report["logical_content_hash"] = base.logical_content_hash(report)
        with self.assertRaisesRegex(ValueError, "authority changed"):
            e2e.project_diagnostic(report)

    def test_artifact_byte_difference_or_extra_file_fails(self):
        with TemporaryDirectory() as temporary:
            first = Path(temporary) / "a"
            second = Path(temporary) / "b"
            first.mkdir()
            second.mkdir()
            (first / "result.json").write_bytes(b'{}\n')
            (second / "result.json").write_bytes(b'{}\n')
            e2e.require_artifact_equality(first, second)
            (second / "result.json").write_bytes(b'{} \n')
            with self.assertRaisesRegex(ValueError, "artifact identity mismatch"):
                e2e.require_artifact_equality(first, second)
            (second / "result.json").write_bytes(b'{}\n')
            (second / "orders.json").write_bytes(b'[]')
            with self.assertRaisesRegex(ValueError, "artifact identity mismatch"):
                e2e.require_artifact_equality(first, second)

    def test_skipped_controls_are_never_successful_acceptance(self):
        result = unittest.TestResult()
        result.testsRun = 4
        result.skipped = [("missing benchmark", "raw snapshot unavailable")]
        with self.assertRaisesRegex(ValueError, "failed or skipped"):
            e2e.require_control_success(result, 4)

    def test_zero_controls_or_expected_failures_are_not_acceptance(self):
        with self.assertRaisesRegex(ValueError, "failed or skipped"):
            e2e.require_control_success(unittest.TestResult(), 4)
        result = unittest.TestResult()
        result.testsRun = 4
        result.expectedFailures = [("control", "expected failure")]
        with self.assertRaisesRegex(ValueError, "failed or skipped"):
            e2e.require_control_success(result, 4)

    def test_worker_subprocess_failure_is_not_a_report(self):
        completed = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"intentional failure")
        with patch.object(e2e.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "intentional failure"):
                e2e.launch_worker(ROOT, ROOT, ROOT / "not-created")

    def test_fresh_isolated_worker_runs_the_actual_pipeline_and_controls(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "fresh-output"
            result = e2e.launch_worker(ROOT, ROOT, output)
            self.assertEqual(result["synthetic_controls"]["tests_run"], 4)
            self.assertEqual(result["synthetic_controls"]["skipped"], 0)
            self.assertEqual(len(result["negative_controls"]), 6)
            self.assertEqual(len(e2e.artifact_hashes(output)), 11)
            self.assertEqual({item["decision"]["kind"] for item in result["real_samples"]}, {"NEEDS_REVIEW"})
            e2e.verify_frozen_artifacts(output, ROOT)

    def test_existing_worker_output_is_refused_without_modification(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            sentinel = output / "sentinel.txt"
            sentinel.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                e2e.run_worker(ROOT, output)
            self.assertEqual(sentinel.read_bytes(), b"keep")
            self.assertEqual(list(output.iterdir()), [sentinel])

    def test_missing_evidence_subprocess_fails_before_output(self):
        with TemporaryDirectory() as temporary:
            absent = Path(temporary) / "absent"
            absent.mkdir()
            e2e.launch_worker(ROOT, absent, Path(temporary) / "must-not-exist", expect_failure=True)

    def test_archive_without_complete_source_fails_instead_of_using_host_imports(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("RULE_SPEC.md", b"placeholder")
        with patch.object(integrity, "git_bytes", side_effect=[b"a" * 40 + b"\n", data.getvalue()]):
            with TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(ValueError, "E2E tool and storage source package"):
                    e2e.restore_runtime(ROOT, "HEAD", Path(temporary))


if __name__ == "__main__":
    unittest.main()
