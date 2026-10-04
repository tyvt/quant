"""Suffix syntax is not a resolved note target, row semantics or rule input."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import unittest
from unittest.mock import patch

from scripts.parsing.field_binder import cell, note_reference_observation
from scripts.parsing.generic_extractor import Page, Word
from scripts.pilots import build_annual_note_suffix_regression as regression
from scripts.screening.contracts import canonical_bytes, content_hash, load_request

ROOT = regression.ROOT
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-note-suffix-regression-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-note-suffix-fix-2026-10-04-v1/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-note-suffix-fix-2026-10-04-v1/evidence-index.json"


def seal(report):
    report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
    return report


class NoteSuffixSyntaxTests(unittest.TestCase):
    def probe(self, texts=("七（79）3",), *, boxes=None, rotation=0, multiplier=1):
        notes = tuple(Word(t, boxes[i] if boxes else (220 + i * 30, 100, 240 + i * 30, 110)) for i, t in enumerate(texts))
        words = notes + (Word("-100.25", (330, 100, 390, 110)), Word("90.50", (480, 100, 540, 110)))
        page = Page(1, 600, 800, rotation, "synthetic", words)
        return page, notes, cell(page, words, 105, 200, 450, multiplier, amount_left=300)

    def rejected(self, texts, **kwargs):
        page, notes, observed = self.probe(texts, **kwargs)
        proof = note_reference_observation(page, notes, 200, 300)
        self.assertNotEqual(proof["reference_form"], regression.FORM)
        self.assertIsNone(observed["current"]["value_cny"])
        self.assertIsNone(observed["comparative"]["value_cny"])
        return proof

    def test_complete_single_token(self):
        page, notes, observed = self.probe()
        proof = note_reference_observation(page, notes, 200, 300)
        self.assertEqual(proof["reference_form"], regression.FORM)
        self.assertEqual(proof["syntax_state"], "OBSERVED_SINGLE_REFERENCE_SYNTAX")
        self.assertEqual((observed["current"]["value_cny"], observed["comparative"]["value_cny"]), ("-100.25", "90.50"))

    def test_all_canonical_chapters_one_to_ninety_nine(self):
        digits = "一二三四五六七八九"
        for n in range(1, 100):
            chapter = digits[n-1] if n < 10 else ("" if n < 20 else digits[n//10-1]) + "十" + (digits[n%10-1] if n%10 else "")
            with self.subTest(n=n):
                self.assertEqual(self.probe((chapter + "（79）3",))[2]["current"]["state"], "OBSERVED_NUMERIC")

    def test_noncanonical_chapters(self):
        for chapter in ("零", "〇", "百", "一百", "两", "甲", "九九", "一十", "七八", ""):
            with self.subTest(chapter=chapter): self.rejected((chapter + "（79）3",))

    def test_positive_ASCII_parent_and_suffix(self):
        self.assertEqual(self.probe(("九十九（12345）67890",))[2]["current"]["state"], "OBSERVED_NUMERIC")

    def test_zero_parent(self): self.rejected(("七（0）3",))
    def test_zero_suffix(self): self.rejected(("七（79）0",))
    def test_leading_zero_parent(self): self.rejected(("七（079）3",))
    def test_leading_zero_suffix(self): self.rejected(("七（79）03",))
    def test_signed_parent(self):
        for s in ("七（-79）3", "七（+79）3"): self.rejected((s,))
    def test_signed_suffix(self):
        for s in ("七（79）-3", "七（79）+3"): self.rejected((s,))
    def test_fullwidth_or_chinese_digits(self):
        for s in ("七（７９）3", "七（79）３", "七（七十九）3", "七（79）三"): self.rejected((s,))
    def test_decimal(self):
        for s in ("1.2", "七（79.1）3", "七（79）3.1"): self.rejected((s,))
    def test_scientific_notation(self):
        for s in ("1e2", "七（79e1）3", "七（79）3e1"): self.rejected((s,))
    def test_signed_money(self):
        for s in ("-1", "+1", "-100.25"): self.rejected((s,))
    def test_ASCII_parentheses(self): self.rejected(("七(79)3",))
    def test_half_or_unclosed_parentheses(self):
        for s in ("七（79", "七（79)3", "七(79）3", "七79）3"): self.rejected((s,))
    def test_list_or_multiple_references(self):
        for s in ("七（79）3、4", "七（79）3，4", "七（79）3/4", "七（79）3七（80）4"): self.rejected((s,))
    def test_other_two_multilevel_families_remain_rejected(self):
        for s in ("七、78（1）", "七、79（4）", "七-59（1）", "五、70（3）"): self.rejected((s,))
    def test_dotted_or_prefixed_forms_remain_rejected(self):
        for s in ("七、79.3", "附注七（79）3", "七-79.3"): self.rejected((s,))
    def test_no_whitespace_deletion(self):
        for s in (" 七（79）3", "七（79）3 ", "七 （79）3", "七（79） 3", "七（79）\n3"): self.rejected((s,))
    def test_no_trailing_text_or_nested_reference(self):
        for s in ("七（79）3现金", "七（79）3（1）", "（七（79）3）"): self.rejected((s,))
    def test_no_same_line_token_join(self): self.rejected(("七（79）", "3"))
    def test_no_cross_line_reference_join(self):
        page, notes, _ = self.probe(("七（79）", "3"), boxes=((220,100,240,110),(220,115,240,125)))
        proof = note_reference_observation(page, notes, 200, 300)
        self.assertEqual(proof["syntax_state"], "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
        # The first token alone is still an OLD supported parent-item form;
        # preserving that path must not be described as new suffix recognition.
        self.assertNotEqual(note_reference_observation(page, notes[:1],200,300)["reference_form"], regression.FORM)
    def test_no_cross_page_token_import(self):
        page, notes, _ = self.probe()
        page = replace(page, words=page.words[1:])
        self.assertEqual(note_reference_observation(page, notes,200,300)["syntax_state"], "NOTE_GEOMETRY_UNKNOWN")
    def test_rotation(self): self.rejected(("七（79）3",), rotation=90)
    def test_page_edge_clipping(self):
        page,notes,_=self.probe()
        clipped=replace(page,height=105)
        self.assertEqual(note_reference_observation(clipped,notes,200,300)["syntax_state"],"NOTE_GEOMETRY_UNKNOWN")
        observed=cell(clipped,clipped.words,105,200,450,1,amount_left=300)
        self.assertIsNone(observed["current"]["value_cny"])
    def test_note_left_boundary(self):
        page,notes,_=self.probe(boxes=((199,100,240,110),))
        self.assertEqual(note_reference_observation(page,notes,200,300)["syntax_state"],"NOTE_GEOMETRY_UNKNOWN")
    def test_note_touches_amount_boundary(self):
        self.rejected(("七（79）3",),boxes=((220,100,300,110),))
    def test_note_crosses_amount_boundary(self):
        self.rejected(("七（79）3",),boxes=((220,100,310,110),))
    def test_no_explicit_note_column_no_discard(self):
        page, notes, _ = self.probe()
        result = cell(page,page.words,105,200,450,1)
        self.assertEqual(result["current"]["state"], "AMBIGUOUS_CELL")
        self.assertIsNone(result["current"]["value_cny"])
    def test_amount_column_guard_not_relaxed(self):
        page, notes, _ = self.probe()
        words = tuple(replace(w,box=(330,100,451,110)) if w.text == "-100.25" else w for w in page.words)
        result=cell(replace(page,words=words),words,105,200,450,1,amount_left=300)
        self.assertEqual(result["current"]["state"],"COLUMN_EDGE_AMBIGUOUS")
    def test_blank_dash_zero_and_negative_preserved(self):
        page, notes, _ = self.probe()
        for text, state, value in ((None,"BLANK_NOT_ZERO",None),("—","DASH_NOT_ZERO",None),("0","OBSERVED_NUMERIC","0"),("-8","OBSERVED_NUMERIC","-8")):
            words=tuple(w for w in page.words if w.text!="-100.25")
            if text is not None: words+= (Word(text,(330,100,390,110)),)
            result=cell(replace(page,words=words),words,105,200,450,1,amount_left=300)
            self.assertEqual((result["current"]["state"],result["current"]["value_cny"]),(state,value))
    def test_unit_multiplier(self):
        self.assertEqual(self.probe(multiplier=10000)[2]["current"]["value_cny"],"-1002500.00")
    def test_old_four_reference_forms_preserved(self):
        for s in ("7","—","七、79","七（79）"):
            self.assertEqual(self.probe((s,))[2]["current"]["state"],"OBSERVED_NUMERIC")
    def test_native_text_geometry_and_false_certification_flags(self):
        page,notes,_=self.probe(); proof=note_reference_observation(page,notes,200,300)
        self.assertEqual(proof["raw_text"],["七（79）3"])
        self.assertEqual(proof["boxes"],[[220,100,240,110]])
        self.assertFalse(proof["note_target_resolved"])
        self.assertFalse(proof["note_semantics_certified"])


class NoteSuffixRealRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=SCOPE.read_bytes(); cls.plan=json.loads(cls.raw)
        with patch("requests.sessions.Session.request",side_effect=AssertionError("offline")):
            cls.report=regression.build_regression(cls.raw)
        cls.index=regression.public_index(cls.report)
        cls.changes=[c for r in cls.report["observations"] for cs in r["changes"].values() for c in cs]

    def test_fourteen_sources_only_one_PDF_and_six_rows_change(self):
        self.assertEqual(self.report["counts"],{"issuers":11,"PDF_versions":14,"changed_PDFs":1,"changed_rows":6,
            "raw_multilevel_tokens":21,"currency_blocked_PDFs":4,"unchanged_bundles":14})
        self.assertEqual([r["source"]["security_id"] for r in self.report["observations"] if any(r["changes"].values())],["sh.600887"])
    def test_frozen_old_code_executed_and_old_row_assertions_preserved(self):
        self.assertEqual(self.report["manifest"]["baseline_code_commit"],"e530dd915840aac5c8cc311b931234604ad8b1b1")
        self.assertEqual(self.report["manifest"]["baseline_execution"],"ACTUAL_FROZEN_CODE_NOT_SAVED_OUTPUT")
        for c in self.changes:
            for k in ("current","comparative"):
                self.assertEqual(c["before"][k]["state"],"NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
                self.assertIsNone(c["before"][k]["value_cny"])
    def test_eleven_numeric_cells_one_blank_not_twelve_numbers(self):
        states=Counter(c["after"][k]["state"] for c in self.changes for k in ("current","comparative"))
        self.assertEqual(states,{"OBSERVED_NUMERIC":11,"BLANK_NOT_ZERO":1})
        blank=next(c["after"] for c in self.changes if c["after"]["current"]["state"]=="BLANK_NOT_ZERO")
        self.assertIsNone(blank["current"]["value_cny"])
    def test_main_financing_total_matches_payment_note_but_not_added_as_lease(self):
        c=next(c["after"] for c in self.changes if c["after"]["source_label"]=="支付其他与筹资活动有关的现金")
        self.assertEqual((c["current"]["value_cny"],c["comparative"]["value_cny"]),("965171650.04","1045156845.45"))
        r=next(r for r in self.report["observations"] if r["source"]["security_id"]=="sh.600887")
        self.assertEqual(r["baseline_snapshot"]["bundle"]["lease_financing_component"]["observed_value_cny"],"174129885.66")
    def test_other_thirteen_tables_and_all_bundles_unchanged(self):
        for r in self.report["observations"]:
            self.assertEqual(r["bundle_content_hash"],content_hash(r["baseline_snapshot"]["bundle"]))
            if r["source"]["security_id"]!="sh.600887":
                self.assertEqual(r["current_tables"],r["baseline_snapshot"]["tables"])
    def test_other_nine_evaluated_multilevel_candidates_stay_unknown(self):
        rows=[r for source in self.report["observations"] for t in source["current_tables"].values() for r in t["rows"]]
        other=[r for r in rows if len(r.get("note_column_observation",{}).get("raw_text",[]))==1
            and any(__import__('re').fullmatch(p,r["note_column_observation"]["raw_text"][0]) for f,p in regression.FORMS.items() if f!=regression.FORM)]
        self.assertEqual(len(other),9)
        self.assertTrue(all(r["current"]["state"]=="NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE" for r in other))
    def test_four_currency_blocks_not_reported_as_note_pass(self):
        for r in self.report["observations"]:
            if r["currency"] is None:
                self.assertTrue(all(t["state"]=="CURRENCY_EVIDENCE_UNKNOWN" and t["rows"]==[] for t in r["current_tables"].values()))
    def test_only_binder_bytes_changed_in_six_parser_files(self):
        m=self.report["manifest"]
        self.assertEqual([p for p,h in m["parser_code_sha256"].items() if h!=m["baseline_parser_code_sha256"][p]],["scripts/parsing/field_binder.py"])
    def test_each_source_input_and_parent_SHA_stays_fixed(self):
        for key in regression.REFS:
            ref=self.plan[key]; self.assertEqual(hashlib.sha256((ROOT/ref["path"]).read_bytes()).hexdigest(),ref["sha256"])
        for r in self.report["observations"]:
            s=r["source"]; self.assertEqual(hashlib.sha256((ROOT/s["pdf_path"]).read_bytes()).hexdigest(),s["pdf_sha256"])
    def test_complete_lease_PIT_and_screening_stay_unavailable(self):
        for r in self.report["observations"]:
            for key in ("full_lease_cash","full_lease_cash_pit","FCF_conservative"): self.assertIsNone(r[key])
            b=r["baseline_snapshot"]["bundle"]
            self.assertFalse(b["dependency_preview_only"]["admitted_to_hard_gates"])
        for c in self.changes:
            n=c["after"]["note_column_observation"]
            self.assertFalse(n["note_target_resolved"]); self.assertFalse(n["note_semantics_certified"])
        with self.assertRaises(ValueError): load_request(canonical_bytes(self.report))
    def test_canonical_reports_and_independent_index_identity(self):
        self.assertEqual(PRIVATE.read_bytes(),canonical_bytes(self.report)+b"\n")
        self.assertEqual(PUBLIC.read_bytes(),canonical_bytes(self.index)+b"\n")
        self.assertNotEqual(self.index["logical_content_hash"],self.report["logical_content_hash"])
    def test_public_index_no_full_original_text_channels(self):
        raw=canonical_bytes(self.index)
        for name in ("raw_text","text","words","native_text","source_label","label_text","table_header","baseline_snapshot","current_tables"):
            self.assertNotIn(('"'+name+'":').encode(),raw)
        self.assertNotIn("支付其他与筹资活动有关的现金".encode(),raw)
    def test_public_projection_cannot_promote_permissions_or_semantics(self):
        for key,value in (("note_target_resolved",True),("note_semantics_certified",True),("screening_input_exported",True),
                          ("pit_admitted_observation_count",False),("diagnostic_available_at","2026-09-30")):
            with self.assertRaises(ValueError): regression.public_index(seal({**deepcopy(self.report),key:value}))
    def test_public_reference_text_or_coordinates_cannot_smuggle_paragraph(self):
        for mode in ("reference","box","amount","note_certification"):
            r=deepcopy(self.report); c=next(c["after"] for row in r["observations"] for cs in row["changes"].values() for c in cs)
            if mode=="reference": c["note_column_observation"]["raw_text"]=["private paragraph"]
            elif mode=="box": c["binding"]["label_box"]=["paragraph",1,2,3]
            elif mode=="amount": c["current"]["value_cny"]="paragraph"
            else: c["note_column_observation"]["note_target_resolved"]=True
            with self.assertRaises(ValueError): regression.public_index(seal(r))
    def test_unknown_extra_text_not_projected(self):
        r=deepcopy(self.report); r["full_page"]="do not publish this text"
        self.assertNotIn(b"do not publish this text",canonical_bytes(regression.public_index(seal(r))))
    def test_table_header_binding_and_row_order_changes_rejected(self):
        r=next(r for r in self.report["observations"] if any(r["changes"].values()))
        before=r["baseline_snapshot"]["tables"]["cashflow"]; after=r["current_tables"]["cashflow"]
        for mode in ("header","binding","order"):
            changed=deepcopy(after)
            if mode=="header": changed["header"]["fiscal_year"]=2023
            elif mode=="order": changed["rows"]=list(reversed(changed["rows"]))
            else: changed["rows"][0]["binding"]["statement_scope"]="PARENT"
            with self.assertRaises(ValueError): regression.row_changes(before,changed)
    def test_bad_plan_form_commit_date_whitelist_rejected(self):
        for key,value in (("new_reference_form","ANY_REFERENCE"),("baseline_code_commit","e530dd9"),("as_of","2026-02-30"),("extra",1)):
            with self.assertRaises(ValueError): regression.read_plan(canonical_bytes({**deepcopy(self.plan),key:value}))
        r=deepcopy(self.plan); r["expected_parser_code_sha256"]["other"]="0"*64
        with self.assertRaises(ValueError): regression.read_plan(canonical_bytes(r))
    def test_parent_and_current_code_hash_drift_rejected(self):
        for key in regression.REFS:
            plan=deepcopy(self.plan); plan[key]["sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"hash mismatch"): regression.build_regression(canonical_bytes(plan))
        plan=deepcopy(self.plan); plan["expected_parser_code_sha256"]["scripts/parsing/field_binder.py"]="0"*64
        with self.assertRaisesRegex(ValueError,"implementation drift"): regression.build_regression(canonical_bytes(plan))
    def test_baseline_blob_drift_rejected_before_execution(self):
        plan=deepcopy(self.plan); plan["baseline_parser_code_sha256"]["scripts/parsing/field_binder.py"]="0"*64
        with self.assertRaisesRegex(ValueError,"blob mismatch"): regression.frozen_snapshot(plan,[],ROOT)
    def test_CLI_refuses_overwrite_and_check_writes_nothing(self):
        args=["--scope",str(SCOPE),"--output",str(PRIVATE),"--public-index",str(PUBLIC)]
        with patch.object(regression,"build_regression",return_value=self.report):
            with self.assertRaisesRegex(ValueError,"refusing to overwrite"): regression.main(args)
            self.assertIsNone(regression.main(args+["--check"]))
    def test_private_output_outside_storage_rejected(self):
        with self.assertRaises(SystemExit),patch("sys.stderr"):
            regression.main(["--scope",str(SCOPE),"--output",str(ROOT/"docs/data-pilots/full.json"),"--public-index",str(PUBLIC)])


if __name__ == "__main__":
    unittest.main()
