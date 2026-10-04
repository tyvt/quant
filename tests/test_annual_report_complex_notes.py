"""Complete note-cell syntax only: preserve geometry, money, UNKNOWN and old bytes."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle, markdown
from scripts.parsing.field_binder import cell, note_reference_observation
from scripts.parsing.generic_extractor import Page, Word
from scripts.pilots.replay_frozen_annual_gap_map import replay_frozen_gap_map
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class ComplexNoteSyntaxTests(unittest.TestCase):
    def probe(self, texts, *, boxes=None, rotation=0, amount_left=300, multiplier=1):
        notes = tuple(Word(text, boxes[index] if boxes else (220 + index * 30, 100, 240 + index * 30, 110))
                      for index, text in enumerate(texts))
        words = notes + (Word("-100.25", (330, 100, 390, 110)), Word("90.50", (480, 100, 540, 110)))
        page = Page(1, 600, 800, rotation, "synthetic", words)
        return page, notes, cell(page, words, 105, 200, 450, multiplier, amount_left=amount_left)

    def rejected(self, texts, **kwargs):
        page, notes, observed = self.probe(texts, **kwargs)
        self.assertIsNone(observed["current"]["value_cny"])
        self.assertIsNone(observed["comparative"]["value_cny"])
        self.assertNotEqual(observed["current"]["state"], "OBSERVED_NUMERIC")
        return page, notes, observed

    def test_complete_dunhao_form_preserves_two_signed_money_columns(self):
        page, notes, observed = self.probe(("七、1",))
        self.assertEqual((observed["current"]["value_cny"], observed["comparative"]["value_cny"]), ("-100.25", "90.50"))
        self.assertEqual(note_reference_observation(page, notes, 200, 300)["reference_form"], "CHAPTER_DUNHAO_POSITIVE_ITEM")

    def test_complete_fullwidth_parentheses_form(self):
        page, notes, observed = self.probe(("七（1）",))
        self.assertEqual(observed["current"]["state"], "OBSERVED_NUMERIC")
        self.assertEqual(note_reference_observation(page, notes, 200, 300)["reference_form"], "CHAPTER_FULLWIDTH_PARENS_POSITIVE_ITEM")

    def test_canonical_chinese_chapters_one_to_ninety_nine(self):
        for text in ("一、1", "九（2）", "十、3", "十一（4）", "二十、5", "九十九（60）"):
            with self.subTest(text=text):
                self.assertEqual(self.probe((text,))[2]["current"]["state"], "OBSERVED_NUMERIC")

    def test_unknown_noncanonical_or_out_of_range_chapter(self):
        for text in ("甲（1）", "零、1", "〇、1", "一百、1", "九九、1", "一十（1）", "两、1", "七八（1）"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_zero_or_leading_zero_complex_item_not_positive_canonical(self):
        for text in ("七、0", "七（0）", "七、01", "七（01）"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_legacy_single_integer_and_dash_forms_remain_supported(self):
        for text in ("0", "7", "99", "-", "—", "–"):
            with self.subTest(text=text):
                self.assertEqual(self.probe((text,))[2]["current"]["state"], "OBSERVED_NUMERIC")

    def test_two_independent_integer_tokens_now_unknown(self):
        self.assertEqual(self.rejected(("7", "1"))[2]["current"]["state"], "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")

    def test_multiple_dash_or_reference_tokens_not_unique_cell(self):
        for texts in (("—", "—"), ("七、1", "七、2"), ("七、", "1"), ("七", "（1）")):
            with self.subTest(texts=texts):
                self.rejected(texts)

    def test_positive_and_negative_money_not_reference(self):
        for text in ("-1", "+1", "七、-1", "七（+1）", "−1"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_decimal_not_reference(self):
        for text in ("1.2", "七、1.2", "七（1.2）", "1,234.56"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_scientific_notation_not_reference(self):
        for text in ("1e2", "1E+2", "七（1e2）"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_truncated_or_unclosed_reference_not_repaired(self):
        for text in ("七（1", "七、", "（1）", "七（", "七（1）尾"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_lists_and_multiple_references_not_accepted(self):
        for text in ("七（1）、（2）", "七、1、2", "七（1）七（2）", "1,2"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_other_reference_spellings_not_added(self):
        for text in ("附注七", "七-1", "七(1)", "七，1", "7（1）", "第七（1）"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_whitespace_not_deleted_to_manufacture_reference(self):
        for text in ("7 1", "七、 1", " 七（1）", "七（1） ", "七\n（1）"):
            with self.subTest(text=text):
                self.rejected((text,))

    def test_same_page_next_line_is_not_joined(self):
        self.rejected(("七、", "1"), boxes=((220, 100, 240, 110), (220, 120, 240, 130)))

    def test_reference_from_foreign_page_not_native_to_current_page(self):
        page, notes, observed = self.probe(("七、1",))
        foreign = replace(notes[0], box=(221, 100, 241, 110))
        proof = note_reference_observation(page, (foreign,), 200, 300)
        self.assertEqual(proof["syntax_state"], "NOTE_GEOMETRY_UNKNOWN")

    def test_rotated_reference_stays_unknown(self):
        self.assertEqual(self.rejected(("七、1",), rotation=90)[2]["current"]["state"], "NOTE_GEOMETRY_UNKNOWN")

    def test_page_edge_clipping_not_complete_observation(self):
        page, notes, observed = self.probe(("七（1）",), boxes=((220, 790, 240, 810),))
        self.assertEqual(note_reference_observation(page, notes, 200, 300)["syntax_state"], "NOTE_GEOMETRY_UNKNOWN")

    def test_right_note_edge_crossing_money_column_unknown(self):
        self.assertEqual(self.rejected(("七、1",), boxes=((290, 100, 310, 110),))[2]["current"]["state"],
                         "NOTE_AMOUNT_BOUNDARY_AMBIGUOUS")

    def test_reference_touching_amount_boundary_unknown(self):
        self.assertEqual(self.rejected(("七、1",), boxes=((280, 100, 300, 110),))[2]["current"]["state"],
                         "NOTE_AMOUNT_BOUNDARY_AMBIGUOUS")

    def test_reference_left_of_declared_note_column_is_not_certified(self):
        page, notes, observed = self.probe(("七、1",))
        self.assertEqual(note_reference_observation(page, notes, 230, 300)["syntax_state"], "NOTE_GEOMETRY_UNKNOWN")

    def test_no_explicit_note_column_does_not_discard_complex_reference(self):
        page, notes, observed = self.probe(("七、1",), amount_left=None)
        self.assertEqual(observed["current"]["state"], "AMBIGUOUS_CELL")
        self.assertIsNone(observed["current"]["value_cny"])
        self.assertEqual(observed["comparative"]["value_cny"], "90.50")

    def test_unit_multiplier_preserved(self):
        self.assertEqual(self.probe(("七（1）",), multiplier=10000)[2]["current"]["value_cny"], "-1002500.00")

    def test_missing_money_not_derived_from_reference(self):
        page, notes, observed = self.probe(("七、1",))
        words = tuple(word for word in page.words if word.text != "-100.25")
        result = cell(replace(page, words=words), words, 105, 200, 450, 1, amount_left=300)
        self.assertEqual((result["current"]["state"], result["current"]["value_cny"]), ("BLANK_NOT_ZERO", None))

    def test_amount_column_boundary_not_relaxed(self):
        page, notes, observed = self.probe(("七、1",))
        words = tuple(replace(word, box=(330, 100, 451, 110)) if word.text == "-100.25" else word for word in page.words)
        result = cell(replace(page, words=words), words, 105, 200, 450, 1, amount_left=300)
        self.assertEqual(result["current"]["state"], "COLUMN_EDGE_AMBIGUOUS")
        self.assertIsNone(result["current"]["value_cny"])

    def test_proof_keeps_native_text_box_without_target_or_semantic_certification(self):
        page, notes, observed = self.probe(("七（1）",))
        proof = note_reference_observation(page, notes, 200, 300)
        self.assertEqual((proof["raw_text"], proof["boxes"]), (["七（1）"], [[220, 100, 240, 110]]))
        self.assertFalse(proof["note_target_resolved"])
        self.assertFalse(proof["note_semantics_certified"])


class ComplexNoteRealRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = {}
        for sid in ("600276", "600887", "601012"):
            raw = (ROOT / f"docs/data-pilots/2026-10-03-annual-report-bundle-{sid}-inputs.json").read_bytes()
            cls.reports[sid] = build_bundle(raw)
        cls.before = json.loads((ROOT / "docs/data-pilots/annual-gap-map-2026-10-03-v1/diagnostic-only.json").read_bytes())

    def formerly_blocked(self, sid):
        before = next(r for r in self.before["observations"] if r["source"]["security_id"] == "sh." + sid)
        keys = {(r["source_label"], r["physical_page"], tuple(r["label_box"])) for r in before["complex_note_rows"]}
        return [r for r in self.reports[sid]["bundles"][0]["balance_sheet_row_inventory"]
                if (r["source_label"], r["binding"]["physical_page"], tuple(r["binding"]["label_box"])) in keys]

    def test_frozen_JSON_and_markdown_reproduce_original_directories(self):
        from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
        for sid, report in self.reports.items():
            directory = ROOT / f"docs/data-pilots/annual-complex-notes-{sid}-2026-10-03-v1"
            scope = ROOT / f"docs/data-pilots/2026-10-03-annual-report-bundle-{sid}-inputs.json"
            replay = replay_frozen_bundle(scope, directory, "88fcd1763339cc792a5c63f2be93f3b50cb9bf1a")
            # Audit blocks and bounded lease aliases are separately versioned.
            # Actually replay both old files, then compare all unrelated fields.
            bundles = deepcopy(report["bundles"])
            old_bundles = deepcopy(replay["report"]["bundles"])
            for bundle in bundles:
                bundle["audit_text_observation"].pop("narrative_opinion_block")
                bundle.pop("lease_financing_component")
            for bundle in old_bundles:
                self.assertIsNone(bundle.pop("lease_financing_component")["observed_value_cny"])
            self.assertEqual(bundles, old_bundles)

    def test_all_133_old_rows_gain_syntax_not_semantic_certification(self):
        self.assertEqual([len(self.formerly_blocked(sid)) for sid in self.reports], [36, 49, 48])
        for sid in self.reports:
            for row in self.formerly_blocked(sid):
                proof = row["note_column_observation"]
                self.assertEqual(proof["syntax_state"], "OBSERVED_SINGLE_REFERENCE_SYNTAX")
                self.assertFalse(proof["note_target_resolved"])
                self.assertFalse(proof["note_semantics_certified"])
                self.assertEqual(row["binding"]["document_sha256"], self.reports[sid]["bundles"][0]["source"]["pdf_sha256"])

    def test_restored_numeric_cells_not_counted_as_133_complete_amount_rows(self):
        rows = [row for sid in self.reports for row in self.formerly_blocked(sid)]
        self.assertEqual(Counter(r["current"]["state"] for r in rows),
                         {"OBSERVED_NUMERIC": 126, "BLANK_NOT_ZERO": 6, "DASH_NOT_ZERO": 1})
        self.assertEqual(Counter(r["comparative"]["state"] for r in rows),
                         {"OBSERVED_NUMERIC": 129, "BLANK_NOT_ZERO": 3, "DASH_NOT_ZERO": 1})

    def test_seven_target_values_unchanged_and_hengrui_profit_gaps_preserved(self):
        prior_paths = {"600276": "annual-currency-600276-2026-10-03-v2",
                       "600887": "annual-holdout-600887-2026-10-03-v1",
                       "601012": "annual-joint-currency-601012-2026-10-03-v2"}
        for sid, directory in prior_paths.items():
            old = json.loads((ROOT / "docs/data-pilots" / directory / "diagnostic-only.json").read_bytes())
            for key, field in old["bundles"][0]["fields"].items():
                actual = self.reports[sid]["bundles"][0]["fields"][key]
                self.assertEqual((actual["state"], actual["observed_value_cny"], actual["comparative_not_target_value_cny"]),
                                 (field["state"], field["observed_value_cny"], field["comparative_not_target_value_cny"]))

    def test_real_blank_dash_and_geometry_unknowns_not_zero(self):
        for sid, report in self.reports.items():
            for row in report["bundles"][0]["balance_sheet_row_inventory"]:
                for column in ("current", "comparative"):
                    if row[column]["state"] != "OBSERVED_NUMERIC":
                        self.assertIsNone(row[column]["value_cny"])

    def test_currency_audit_and_complete_lease_not_promoted(self):
        # Current-code observations may improve; frozen first reports above are
        # still replayed by their own code. No full lease or PIT promotion.
        expected_parts = {"600276": "47375294.97", "601012": "191934806.52", "600887": "174129885.66"}
        for sid, report in self.reports.items():
            bundle = report["bundles"][0]
            self.assertEqual(bundle["currency"], "CNY")
            self.assertEqual(bundle["lease_financing_component"]["observed_value_cny"], expected_parts[sid])
            self.assertIsNone(bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
            self.assertIsNone(bundle["audit_text_observation"]["raw_opinion_type"])

    def test_PIT_zero_and_batch_loader_rejects_each_source_report(self):
        for report in self.reports.values():
            self.assertEqual(report["pit_admitted_observation_count"], 0)
            self.assertIsNone(report["diagnostic_available_at"])
            self.assertFalse(report["screening_input_exported"])
            self.assertFalse(report["production_reader_ready"])
            with self.assertRaises(ValueError):
                load_request(canonical_bytes(report))

    def test_new_code_identities_not_frozen_first_run_successes(self):
        for sid, report in self.reports.items():
            directory = ROOT / f"docs/data-pilots/annual-holdout-{sid}-2026-10-03-v1"
            old = json.loads((directory / "diagnostic-only.json").read_bytes())
            self.assertNotEqual(report["logical_content_hash"], old["logical_content_hash"])
            self.assertNotEqual(report["manifest"]["code_sha256"], old["manifest"]["code_sha256"])


class FrozenGapReplayRejectionTests(unittest.TestCase):
    scope = ROOT / "docs/data-pilots/2026-10-03-annual-gap-map-scope.json"
    directory = ROOT / "docs/data-pilots/annual-gap-map-2026-10-03-v1"
    commit = "b80a0343f86c7c64ccd4ab4c469d11e1b4f560cc"

    def rejected_report(self, edit, pattern):
        report = json.loads((self.directory / "diagnostic-only.json").read_bytes())
        edit(report)
        report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
        with tempfile.TemporaryDirectory(prefix="gap-replay-rejection-") as directory:
            target = Path(directory)
            (target / "diagnostic-only.json").write_bytes(canonical_bytes(report) + b"\n")
            (target / "diagnostic-only.md").write_bytes((self.directory / "diagnostic-only.md").read_bytes())
            with self.assertRaisesRegex(ValueError, pattern):
                replay_frozen_gap_map(self.scope, target, self.commit)

    def test_partial_commit_refused(self):
        with self.assertRaisesRegex(ValueError, "full immutable"):
            replay_frozen_gap_map(self.scope, self.directory, "b80a034")

    def test_wrong_backend_refused(self):
        self.rejected_report(lambda r: r["manifest"]["pdf_backend"].update(version="wrong"), "backend mismatch")

    def test_PIT_admission_refused(self):
        self.rejected_report(lambda r: r.update(pit_admitted_observation_count=1), "source-only gap map")

    def test_changed_scope_hash_refused(self):
        self.rejected_report(lambda r: r.update(scope_sha256="0" * 64), "scope mismatch")

    def test_changed_tool_blob_hash_refused(self):
        self.rejected_report(lambda r: r["manifest"].update(tool_sha256="0" * 64), "Git blob mismatch")

    def test_whitelist_expansion_refused(self):
        self.rejected_report(lambda r: r["manifest"]["parser_code_sha256"].update(extra="0" * 64), "whitelist mismatch")


if __name__ == "__main__":
    unittest.main()
