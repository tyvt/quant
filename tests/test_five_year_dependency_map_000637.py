"""The source index preserves eight versions and zero historical PIT inputs."""

from __future__ import annotations

import copy
from decimal import ROUND_DOWN, localcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.pilots import build_five_year_dependency_map_000637 as pilot
from scripts.pilots import build_limited_diagnostics as base

ROOT = Path(__file__).resolve().parents[1]


class FiveYearDependencyMapTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = pilot.build_map(ROOT)
        _, cls.scope, cls.reports = pilot.load_sources(ROOT)

    def reject_resealed(self, result):
        result["logical_content_hash"] = base.logical_content_hash(result)
        with self.assertRaises(ValueError): pilot.validate_map(result, ROOT)

    def test_exactly_five_originals_and_three_amendments(self):
        rows = self.result["version_rows"]
        self.assertEqual(len(rows), 8)
        self.assertEqual([r["year"] for r in rows if r["version"].startswith("original")], [2021, 2022, 2023, 2024, 2025])
        self.assertEqual([r["year"] for r in rows if r["version"].startswith("amended")], [2023, 2024, 2025])
        self.assertEqual({r["version"]: r["document"]["announcement_id"] for r in rows}, pilot.EXPECTED_VERSIONS)

    def test_source_fields_same_pdf_and_physical_pages(self):
        for row in self.result["version_rows"]:
            doc = row["document"]
            base.verified_bytes(ROOT, doc["path"], doc["sha256"])
            for field in row["fields"].values():
                for ref in field["evidence_refs"]:
                    self.assertIn(doc["sha256"], ref)
                    self.assertIn(int(ref.split(":")[-1]), doc["evidence_pages"])
                self.assertEqual(field["source_state"], "SOURCE_VALUE_BOUND_NOT_PIT")

    def test_each_version_arithmetic_uses_its_own_inputs(self):
        for row in self.result["version_rows"]:
            self.assertEqual(row["ordinary_source_arithmetic"], pilot.ordinary_arithmetic(row["fields"]))
        rows = {r["version"]: r for r in self.result["version_rows"]}
        self.assertEqual(rows["original_2025_annual_report"]["ordinary_source_arithmetic"]["FCF_ordinary_source_arithmetic_cny"], "-16158353.92113239932027895383")
        self.assertEqual(rows["amended_2025_annual_report"]["ordinary_source_arithmetic"]["FCF_ordinary_source_arithmetic_cny"], "-119380263.3277545425210896909")

    def test_decimal_context_does_not_change_projection(self):
        with localcontext() as context:
            context.prec = 6; context.rounding = ROUND_DOWN
            self.assertEqual(pilot.project(self.reports), {key: self.result[key] for key in
                             ("version_rows", "adjacent_year_comparisons", "revision_differences", "policy_bridge_reference")})

    def test_2023_original_lease_not_filled_from_amendment(self):
        rows = {r["version"]: r for r in self.result["version_rows"]}
        original = rows["original_2023_annual_report"]["lease_component"]
        amended = rows["amended_2023_annual_report"]["lease_component"]
        self.assertIsNone(original["observed_cny"])
        self.assertEqual(original["observation_state"], "NOT_IDENTIFIED_IN_FIXED_NOTE_SECTION")
        self.assertEqual(amended["observed_cny"], "10104914.34")

    def test_revision_differences_preserve_all_three_changed_ocfs(self):
        self.assertEqual([r["amended_minus_original_cny"]["OCF"] for r in self.result["revision_differences"]],
                         ["-106218013.72", "-194193040.66", "-122569677.05"])
        for revision in self.result["revision_differences"]:
            self.assertIsNone(revision["latest_visible_version"])
            for name in ("E", "N", "Capex"): self.assertEqual(revision["amended_minus_original_cny"][name], "0.00")

    def test_all_adjacent_existing_version_combinations_are_compared(self):
        comparisons = self.result["adjacent_year_comparisons"]
        self.assertEqual(len(comparisons), 11)
        mixed = [r for r in comparisons if r["earlier_version"] == "original_2023_annual_report" and r["later_version"] == "amended_2024_annual_report"][0]
        self.assertEqual(mixed["later_comparative_minus_earlier_source_cny"]["OCF"], "-106218013.72")
        self.assertFalse(mixed["all_four_source_values_equal"])

    def test_equal_values_still_do_not_prove_full_comparability(self):
        equal = [r for r in self.result["adjacent_year_comparisons"] if r["all_four_source_values_equal"]]
        self.assertTrue(equal)
        self.assertTrue(all(r["full_comparability"] == "UNKNOWN" for r in equal))
        self.assertTrue(all(r["used_to_replace_earlier_source"] is False for r in self.result["adjacent_year_comparisons"]))

    def test_policy_bridge_only_indexes_original_prior_package(self):
        bridge = self.result["policy_bridge_reference"]
        self.assertTrue(bridge["not_used_to_backfill"])
        self.assertEqual(bridge["details"], self.reports["2022"]["policy_bridge"])
        rows = {r["version"]: r for r in self.result["version_rows"]}
        self.assertEqual(rows["original_2022_annual_report"]["fields"]["E"]["observed_value"], "879714239.26")
        self.assertIsNone(bridge["details"]["tables"]["rows"]["surplus_reserve"]["observed_impact_cny"])

    def test_all_unknown_dependencies_and_no_selected_run_version(self):
        self.assertEqual(self.result["historical_pit_observations_admitted"], 0)
        self.assertIsNone(self.result["chosen_version_by_year"])
        self.assertFalse(self.result["complete_standard_fcf_window"])
        for row in self.result["version_rows"]:
            self.assertTrue(all(value is None for value in row["unknown_dependencies"].values()))
            self.assertFalse(row["pit_admitted"])
            self.assertFalse(row["selected_for_run"])

    def test_next_probe_is_one_announcement_bounded_and_not_executed(self):
        probe = self.result["next_probe"]
        self.assertEqual(probe["announcement_id"], "1212743936")
        self.assertEqual(probe["dependency"], "verified_available_at")
        self.assertEqual(probe["maximum_official_read_requests"], 4)
        self.assertFalse(probe["assumption_authorized"])
        self.assertEqual(probe["status"], "SELECTED_NOT_EXECUTED")

    def test_cross_version_and_period_scope_field_projection_fail(self):
        for key in ("version", "security_id", "document_sha256", "period_end", "unit", "statement_scope", "field", "historical_pit_status"):
            reports = copy.deepcopy(self.reports)
            reports["2021"]["version_bundles"][0]["observations"]["OCF"][key] = "different"
            with self.subTest(key=key), self.assertRaises(ValueError): pilot.project(reports)

    def test_cashflow_lease_join_rejects_wrong_2025_pdf_or_version(self):
        for key in ("document_sha256", "version"):
            reports = copy.deepcopy(self.reports)
            reports["2025_lease"]["version_bundles"][0][key] = "different"
            with self.subTest(key=key), self.assertRaises(ValueError): pilot.project(reports)
        reports = copy.deepcopy(self.reports)
        reports["2025_lease"]["source_documents"][0]["announcement_id"] = "1"
        with self.assertRaises(ValueError): pilot.project(reports)

    def test_duplicated_versions_and_invented_document_fail(self):
        reports = copy.deepcopy(self.reports)
        reports["2021"]["version_bundles"].append(copy.deepcopy(reports["2021"]["version_bundles"][0]))
        with self.assertRaises(ValueError): pilot.project(reports)
        reports = copy.deepcopy(self.reports)
        reports["2021"]["source_documents"][0]["announcement_id"] = "123"
        with self.assertRaises(ValueError): pilot.project(reports)

    def test_projection_rejects_lease_completion_arithmetic_and_evidence_tampering(self):
        for kind in ("lease", "arithmetic", "page", "time"):
            reports = copy.deepcopy(self.reports)
            b = reports["2021"]["version_bundles"][0]
            if kind == "lease": b["lease_financing_component"]["full_lease_cash_coverage"] = "COMPLETE"
            if kind == "arithmetic": b["ordinary_source_arithmetic"]["alpha_observed"] = "1"
            if kind == "page": b["observations"]["E"]["evidence_refs"] = ["pdf:sha256:wrong:physical-page:1"]
            if kind == "time": reports["2021"]["source_documents"][0]["exact_available_at_utc"] = "2022-03-31"
            with self.subTest(kind=kind), self.assertRaises(ValueError): pilot.project(reports)

    def test_missing_value_and_negative_capex_cannot_be_invented(self):
        for name, value in (("E", "0"), ("N", None), ("Capex", "-1")):
            reports = copy.deepcopy(self.reports)
            reports["2021"]["version_bundles"][0]["observations"][name]["observed_value"] = value
            with self.subTest(name=name), self.assertRaises((ValueError, TypeError)): pilot.project(reports)

    def test_resealed_authority_timing_latest_version_and_window_fail(self):
        for key, value in (("official_selection", True), ("production_reader_ready", True), ("diagnostic_available_at", "2022-03-31"),
                           ("chosen_version_by_year", {}), ("historical_pit_observations_admitted", True), ("complete_standard_fcf_window", True)):
            result = copy.deepcopy(self.result); result[key] = value
            with self.subTest(key=key): self.reject_resealed(result)

    def test_resealed_index_field_and_lease_backfill_fail(self):
        for kind in ("value", "lease", "unknown", "selection", "comparison"):
            result = copy.deepcopy(self.result)
            if kind == "value": result["version_rows"][0]["fields"]["OCF"]["observed_value"] = "0.00"
            if kind == "lease": result["version_rows"][2]["lease_component"]["observed_cny"] = "10104914.34"
            if kind == "unknown": result["version_rows"][0]["unknown_dependencies"]["available_at"] = "2022-04-01"
            if kind == "selection": result["version_rows"][0]["selected_for_run"] = True
            if kind == "comparison": result["adjacent_year_comparisons"][0]["full_comparability"] = "PASS"
            with self.subTest(kind=kind): self.reject_resealed(result)

    def test_resealed_manifest_source_rule_scope_and_code_hash_fail(self):
        for key in ("rule_sha256", "scope", "source_reports", "code_hashes"):
            result = copy.deepcopy(self.result)
            result["manifest"][key] = "different"
            with self.subTest(key=key): self.reject_resealed(result)

    def test_resealed_probe_cannot_authorize_assumption_or_report_success(self):
        for key, value in (("assumption_authorized", True), ("assumption_authorized", 0), ("status", "COMPLETE"), ("maximum_official_read_requests", 100)):
            result = copy.deepcopy(self.result); result["next_probe"][key] = value
            with self.subTest(key=key): self.reject_resealed(result)

    def test_no_strategy_or_standard_window_payload_allowed(self):
        for key in ("orders", "ranking", "nav", "F1", "F5", "annual_fcf_newest_to_oldest"):
            result = copy.deepcopy(self.result); result[key] = []
            with self.subTest(key=key): self.reject_resealed(result)

    def test_offline_reproduction_is_deterministic(self):
        with patch.object(yrequests(), "request", side_effect=AssertionError("network forbidden")):
            another = pilot.build_map(ROOT)
        self.assertEqual(base.canonical_bytes(self.result), base.canonical_bytes(another))
        reread = base._json(base.canonical_bytes(self.result))
        self.assertEqual(pilot.render_markdown(self.result), pilot.render_markdown(reread))

    def test_frozen_source_file_code_and_pdf_hashes(self):
        for reference in self.result["manifest"]["source_reports"].values():
            raw = base.verified_bytes(ROOT, reference["path"], reference["sha256"])
            self.assertEqual(base._json(raw)["logical_content_hash"], reference["logical_content_hash"])
        for path, sha in self.result["manifest"]["code_hashes"].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), sha)

    def test_frozen_sources_hash_or_bytes_drift_fail(self):
        original = base.verified_bytes
        def changed(root, path, sha):
            if path == self.scope["sources"]["2021"]["path"]: return b'{}'
            return original(root, path, sha)
        with patch.object(base, "verified_bytes", side_effect=changed), self.assertRaises((ValueError, KeyError)):
            pilot.load_sources(ROOT)
        with self.assertRaises(ValueError): base.verified_bytes(ROOT, pilot.INPUTS, "0" * 64)

    def test_cli_two_outputs_equal_and_refuse_overwrite(self):
        with TemporaryDirectory() as folder:
            stems = [Path(folder) / name for name in ("a", "b")]
            for stem in stems:
                result = subprocess.run([sys.executable, "-X", "utf8", pilot.TOOL, "--output-stem", str(stem)], cwd=ROOT, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            for suffix in (".json", ".md"): self.assertEqual(stems[0].with_suffix(suffix).read_bytes(), stems[1].with_suffix(suffix).read_bytes())
            result = subprocess.run([sys.executable, "-X", "utf8", pilot.TOOL, "--output-stem", str(stems[0])], cwd=ROOT, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"refusing to overwrite", result.stderr)

    def test_cli_frozen_check(self):
        result = subprocess.run([sys.executable, "-X", "utf8", pilot.TOOL, "--check"], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))


def yrequests():
    return pilot.y2021.capture.previous.requests
