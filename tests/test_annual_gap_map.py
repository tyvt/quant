"""Offline gap inventory: sample counts, note syntax and non-admission boundaries."""

from copy import deepcopy
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.pilots import build_annual_gap_map as gap
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class AnnualGapMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_scope = (gap.ROOT / "docs/data-pilots/2026-10-03-annual-gap-map-scope.json").read_bytes()
        cls.scope = json.loads(cls.raw_scope)
        cls.directory = gap.ROOT / "docs/data-pilots/annual-gap-map-2026-10-03-v1"
        # Imports reuse a capture guard, but inventory must never call the network.
        with patch("requests.sessions.Session.request", side_effect=AssertionError("unexpected network")):
            cls.report = gap.build_map(cls.raw_scope)
        cls.by_security = {r["source"]["security_id"]: r for r in cls.report["observations"]}
        cls.families = {r["id"]: r for r in cls.report["families"]}
        cls.probes = {tuple(r["note_tokens"]): r for r in cls.report["synthetic_note_probes"]}

    def mocked_build(self, scope, *, same_identity=False):
        """Exercise orchestration rejection without reparsing real documents."""
        refs = scope["inputs"]
        sample = deepcopy(self.report["observations"][0]["source"])
        bundle = {
            "source": sample, "currency": None, "fields": {}, "balance_sheet_row_inventory": [],
            "table_states": {}, "lease_financing_component": {"observed_value_cny": None},
            "audit_text_observation": {"raw_opinion_type": None},
        }
        reports = []
        for index, ref in enumerate(refs):
            item = deepcopy(bundle)
            if not same_identity:
                item["source"]["version"] = "mock_" + str(index)
            reports.append({"manifest": self.report["manifest"], "bundles": [item],
                            "logical_content_hash": "0" * 64})
        with patch.object(gap, "verify_parser"), patch.object(gap, "verified_bytes", return_value=b"{}"), \
                patch.object(gap, "read_scope", return_value={"as_of": scope["as_of"]}), \
                patch.object(gap, "build_bundle", side_effect=reports):
            return gap.build_map(canonical_bytes(scope))

    def test_same_input_regeneration_matches_frozen_JSON_bytes(self):
        self.assertEqual((self.directory / "diagnostic-only.json").read_bytes(),
                         canonical_bytes(self.report) + b"\n")

    def test_markdown_matches_and_survives_canonical_JSON_reload(self):
        raw = gap.markdown(self.report)
        self.assertEqual(raw, (self.directory / "diagnostic-only.md").read_bytes())
        self.assertEqual(raw, gap.markdown(json.loads(canonical_bytes(self.report))))

    def test_logical_hash_excludes_only_self_and_includes_evidence(self):
        value = deepcopy(self.report)
        expected = value.pop("logical_content_hash")
        self.assertEqual(content_hash(value), expected)
        value["observations"][0]["source"]["pdf_sha256"] = "0" * 64
        self.assertNotEqual(content_hash(value), expected)

    def test_manifest_binds_scope_tool_guard_rule_and_six_Git_blobs(self):
        manifest = self.report["manifest"]
        self.assertEqual(self.report["scope_sha256"], hashlib.sha256(self.raw_scope).hexdigest())
        self.assertEqual(manifest["parser_commit"], self.scope["parser_commit"])
        self.assertEqual(len(manifest["parser_code_sha256"]), 6)
        for name, digest in manifest["parser_code_sha256"].items():
            frozen = subprocess.check_output(["git", "show", f"{manifest['parser_commit']}:{name}"], cwd=gap.ROOT)
            self.assertEqual(frozen, (gap.ROOT / name).read_bytes())
            self.assertEqual(hashlib.sha256(frozen).hexdigest(), digest)
        for name, key in (("scripts/pilots/build_annual_gap_map.py", "tool_sha256"),
                          ("scripts/pilots/capture_annual_holdout.py", "capture_guard_sha256"),
                          ("RULE_SPEC.md", "rule_sha256")):
            self.assertEqual(hashlib.sha256((gap.ROOT / name).read_bytes()).hexdigest(), manifest[key])

    def test_thirteen_versions_are_ten_issuers_not_thirteen_companies(self):
        self.assertEqual(self.report["counts"], {"issuers": 10, "PDF_versions": 13})
        rows = self.report["observations"]
        self.assertEqual(sum(r["source"]["security_id"] == "sz.000637" for r in rows), 2)
        self.assertEqual(sum(r["source"]["security_id"] == "sz.002570" for r in rows), 3)

    def test_scope_reference_hashes_and_business_keys_are_unique(self):
        keys = []
        for row in self.report["observations"]:
            ref = row["scope_ref"]
            self.assertEqual(hashlib.sha256((gap.ROOT / ref["path"]).read_bytes()).hexdigest(), ref["sha256"])
            source = row["source"]
            keys.append((source["security_id"], source["fiscal_year"], source["version"]))
        self.assertEqual(len(keys), len(set(keys)))

    def test_complex_note_counts_are_per_row_and_sample_only(self):
        expected = {"sh.600276": 36, "sh.600887": 49, "sh.601012": 48}
        self.assertEqual({sid: len(row["complex_note_rows"]) for sid, row in self.by_security.items()
                          if row["complex_note_rows"]}, expected)
        family = self.families["complex_note_reference"]
        self.assertEqual((family["affected_pdf_count"], family["affected_row_count"]), (3, 133))
        self.assertEqual(family["affected_security_ids"], sorted(expected))
        self.assertEqual(sum(r["balance_row_candidate_count"] for r in self.report["observations"]), 876)

    def test_each_complex_row_keeps_source_page_raw_note_and_geometry(self):
        for record in self.report["observations"]:
            source = record["source"]
            for row in record["complex_note_rows"]:
                self.assertEqual(row["document_sha256"], source["pdf_sha256"])
                self.assertTrue(1 <= row["physical_page"] <= source["page_count"])
                self.assertEqual(row["evidence_ref"],
                                 f"pdf:sha256:{source['pdf_sha256']}:physical-page:{row['physical_page']}")
                self.assertEqual(len(row["label_box"]), 4)
                self.assertEqual(len(row["note"]["raw_text"]), len(row["note"]["boxes"]))
                self.assertFalse(row["note_target_resolved"])

    def test_real_note_examples_bind_distinct_PDFs_and_pages(self):
        for sid, page, raw in (("sh.600276", 144, "七、1"), ("sh.600887", 87, "七（1）"),
                               ("sh.601012", 118, "七、1")):
            row = self.by_security[sid]["complex_note_rows"][0]
            self.assertEqual((row["source_label"], row["physical_page"], row["note"]["raw_text"]),
                             ("货币资金", page, [raw]))

    def test_currency_blocked_rows_are_not_evaluated_not_absent(self):
        for sid in ("sh.600309", "sh.600585", "sh.600741"):
            row = self.by_security[sid]
            self.assertIsNone(row["currency"])
            self.assertEqual(row["note_inventory_scope"], "NOT_EVALUABLE_CURRENCY_BLOCKED")
            self.assertEqual((row["target_observed_count"], row["balance_row_candidate_count"]), (0, 0))
        self.assertEqual(self.families["currency_unknown"]["affected_pdf_count"], 3)

    def test_lease_unidentified_only_counts_currency_evaluable_samples(self):
        family = self.families["lease_component_unidentified"]
        self.assertEqual(family["affected_pdf_count"], 5)
        self.assertNotIn("sh.600309", family["affected_security_ids"])
        self.assertNotIn("sh.600585", family["affected_security_ids"])
        self.assertNotIn("sh.600741", family["affected_security_ids"])

    def test_audit_unknown_count_not_narrative_causality_or_audit_failure(self):
        family = self.families["audit_type_unidentified"]
        self.assertEqual(family["affected_pdf_count"], 8)
        self.assertFalse(family["cause_verified_by_count"])
        self.assertIn("未识别不能统一归因", family["rationale"])

    def test_column_edge_ambiguity_not_hidden_by_other_successes(self):
        family = self.families["column_edge_ambiguous"]
        self.assertEqual(family["affected_security_ids"], ["sh.600066", "sh.600276"])
        self.assertEqual(self.by_security["sh.600066"]["target_observed_count"], 2)
        self.assertEqual(self.by_security["sh.600276"]["target_observed_count"], 5)

    def test_seven_targets_pass_does_not_certify_all_balance_rows(self):
        row = self.by_security["sh.600887"]
        self.assertEqual(row["target_observed_count"], 7)
        self.assertEqual(len(row["complex_note_rows"]), 49)
        self.assertFalse(row["complete_statement_semantics_certified"])

    def test_synthetic_integer_and_dash_acceptance_not_target_resolution(self):
        for tokens in (("7",), ("—",)):
            row = self.probes[tokens]
            self.assertEqual((row["current_state"], row["synthetic_current_value"]), ("OBSERVED_NUMERIC", "100.00"))
            self.assertFalse(row["note_target_resolved"])
            self.assertFalse(row["note_semantics_certified"])

    def test_multiple_integer_tokens_pass_current_guard_not_unique_reference(self):
        row = self.probes[("7", "1")]
        self.assertEqual(row["current_state"], "OBSERVED_NUMERIC")
        self.assertFalse(row["note_target_resolved"])
        self.assertEqual(row["data_kind"], "SYNTHETIC_BINDER_PROBE_NOT_ISSUER_DATA")

    def test_complex_note_spellings_not_added_to_existing_guard(self):
        for tokens in (("七（1）",), ("七、1",), ("附注七",), ("七-1",)):
            row = self.probes[tokens]
            self.assertEqual(row["current_state"], "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
            self.assertIsNone(row["synthetic_current_value"])

    def test_signed_decimal_truncated_or_list_reference_keeps_unknown(self):
        for tokens in (("-1",), ("+1",), ("1.2",), ("七（1",), ("1,2",)):
            row = self.probes[tokens]
            self.assertEqual(row["comparative_state"], "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
            self.assertIsNone(row["synthetic_current_value"])

    def test_proposed_order_not_security_rank_or_market_estimate(self):
        self.assertEqual([r["proposed_engineering_order"] for r in self.report["families"]], [1, 2, 3, 4, 5])
        self.assertTrue(all(r["scope"] == "THIS_EXPLICIT_SAMPLE_ONLY_NOT_MARKET_PREVALENCE"
                            for r in self.report["families"]))
        self.assertTrue(all(not r["cause_verified_by_count"] for r in self.report["families"]))

    def test_original_observations_not_admitted_PIT_or_complete_lease(self):
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        for row in self.report["observations"]:
            self.assertIsNone(row["historical_available_at"])
            self.assertFalse(row["pit_admitted"])
            self.assertFalse(row["full_lease_known"])

    def test_no_ready_export_or_real_selection_and_batch_loader_rejects(self):
        for key in ("screening_input_exported", "real_pit_run_authorized", "production_reader_ready", "official_selection"):
            self.assertFalse(self.report[key])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_duplicate_JSON_keys_and_nonfinite_numbers_rejected(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"schema":NaN}', b'{"schema":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                gap.build_map(raw)

    def test_wrong_schema_extra_keys_and_empty_inputs_rejected(self):
        for mode in ("schema", "extra", "empty"):
            value = deepcopy(self.scope)
            if mode == "schema":
                value["schema"] = "wrong"
            elif mode == "extra":
                value["screening_input_exported"] = True
            else:
                value["inputs"] = []
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                gap.build_map(canonical_bytes(value))

    def test_scope_byte_hash_mismatch_is_hard_failure(self):
        value = deepcopy(self.scope)
        value["inputs"] = [dict(value["inputs"][0], sha256="0" * 64)]
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            gap.build_map(canonical_bytes(value))

    def test_source_path_escape_is_hard_failure(self):
        value = deepcopy(self.scope)
        value["inputs"] = [{"path": "../RULE_SPEC.md", "sha256": "0" * 64}]
        with self.assertRaisesRegex(ValueError, "unsafe or linked source path"):
            gap.build_map(canonical_bytes(value))

    def test_parser_drift_stops_before_any_source_run(self):
        with patch.object(gap, "verify_parser", side_effect=ValueError("parser drift")), \
                patch.object(gap, "build_bundle") as runner:
            with self.assertRaisesRegex(ValueError, "parser drift"):
                gap.build_map(self.raw_scope)
            runner.assert_not_called()

    def test_duplicate_scope_reference_is_hard_failure(self):
        value = deepcopy(self.scope)
        value["inputs"] = [value["inputs"][0], value["inputs"][0]]
        with self.assertRaisesRegex(ValueError, "duplicate input reference"):
            self.mocked_build(value)

    def test_duplicate_business_identity_is_not_double_counted(self):
        value = deepcopy(self.scope)
        value["inputs"] = value["inputs"][:2]
        with self.assertRaisesRegex(ValueError, "duplicate issuer/year/version"):
            self.mocked_build(value, same_identity=True)

    def test_mixed_as_of_is_not_combined_into_one_scope(self):
        with patch.object(gap, "verify_parser"), patch.object(gap, "verified_bytes", return_value=b"{}"), \
                patch.object(gap, "read_scope", return_value={"as_of": "2026-10-01"}), \
                patch.object(gap, "build_bundle") as runner:
            with self.assertRaisesRegex(ValueError, "mixed diagnostic as_of"):
                gap.build_map(self.raw_scope)
            runner.assert_not_called()

    def test_row_source_identity_drift_does_not_enter_inventory(self):
        row = deepcopy(self.by_security["sh.600887"]["complex_note_rows"][0])
        bundle = {"source": self.by_security["sh.600887"]["source"],
                  "balance_sheet_row_inventory": [{"current": {"state": row["current_state"]},
                                                   "comparative": {"state": row["comparative_state"]},
                                                   "binding": {"document_sha256": "0" * 64}}]}
        with self.assertRaisesRegex(ValueError, "row/source identity mismatch"):
            gap.summarize(bundle, {}, "0" * 64)

    def test_reference_order_changes_scope_identity_not_sorted_observations(self):
        a = deepcopy(self.scope)
        a["inputs"] = a["inputs"][:2]
        b = deepcopy(a)
        b["inputs"].reverse()
        first, second = self.mocked_build(a), self.mocked_build(b)
        self.assertEqual(first["observations"], second["observations"])
        self.assertEqual(first["families"], second["families"])
        self.assertNotEqual(first["scope_sha256"], second["scope_sha256"])
        self.assertNotEqual(first["logical_content_hash"], second["logical_content_hash"])


if __name__ == "__main__":
    unittest.main()
