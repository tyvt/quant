"""ASCII-hyphen note syntax never relaxes money geometry or resolves targets."""
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
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-note-hyphen-subitem-regression-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-note-hyphen-subitem-fix-2026-10-04-v1/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-note-hyphen-subitem-fix-2026-10-04-v1/evidence-index.json"
FORM = regression.HYPHEN_FORM


def seal(report):
    report["logical_content_hash"] = content_hash({k:v for k,v in report.items() if k!="logical_content_hash"})
    return report


class HyphenSubitemSyntaxTests(unittest.TestCase):
    def probe(self, texts=("七-59（1）",), *, boxes=None, rotation=0, multiplier=1):
        notes=tuple(Word(t,boxes[i] if boxes else (220+i*30,100,240+i*30,110)) for i,t in enumerate(texts))
        words=notes+(Word("-100.25",(330,100,390,110)),Word("90.50",(480,100,540,110)))
        p=Page(1,600,800,rotation,"synthetic",words)
        return p,notes,cell(p,words,105,200,450,multiplier,amount_left=300)
    def rejected(self,texts,**kwargs):
        p,w,c=self.probe(texts,**kwargs)
        self.assertNotEqual(note_reference_observation(p,w,200,300)["reference_form"],FORM)
        self.assertIsNone(c["current"]["value_cny"]); self.assertIsNone(c["comparative"]["value_cny"])
    def test_single_complete_native_token(self):
        p,w,c=self.probe(); n=note_reference_observation(p,w,200,300)
        self.assertEqual((n["reference_form"],n["syntax_state"]),(FORM,"OBSERVED_SINGLE_REFERENCE_SYNTAX"))
        self.assertEqual((c["current"]["value_cny"],c["comparative"]["value_cny"]),("-100.25","90.50"))
    def test_all_canonical_chapters_one_to_ninety_nine(self):
        digits="一二三四五六七八九"
        for n in range(1,100):
            chapter=digits[n-1] if n<10 else ("" if n<20 else digits[n//10-1])+"十"+(digits[n%10-1] if n%10 else "")
            with self.subTest(n=n):
                p,w,_=self.probe((chapter+"-59（1）",))
                self.assertEqual(note_reference_observation(p,w,200,300)["reference_form"],FORM)
    def test_noncanonical_chapters(self):
        for c in ("零","〇","百","一百","两","甲","九九","一十","七八",""):
            self.rejected((c+"-59（1）",))
    def test_large_positive_ASCII_items(self):
        self.assertEqual(self.probe(("九十九-12345（67890）",))[2]["current"]["state"],"OBSERVED_NUMERIC")
    def test_zero_item(self): self.rejected(("七-0（1）",))
    def test_zero_subitem(self): self.rejected(("七-59（0）",))
    def test_leading_zero_item(self): self.rejected(("七-059（1）",))
    def test_leading_zero_subitem(self): self.rejected(("七-59（01）",))
    def test_signed_item(self):
        for t in ("七--59（1）","七-+59（1）"): self.rejected((t,))
    def test_signed_subitem(self):
        for t in ("七-59（-1）","七-59（+1）"): self.rejected((t,))
    def test_fullwidth_and_chinese_digits(self):
        for t in ("七-５９（1）","七-59（１）","七-五十九（1）","七-59（一）"): self.rejected((t,))
    def test_decimal(self):
        for t in ("1.2","七-59.1（1）","七-59（1.2）"): self.rejected((t,))
    def test_scientific(self):
        for t in ("1e2","七-59e1（1）","七-59（1e2）"): self.rejected((t,))
    def test_signed_money(self):
        for t in ("-1","+1","-100.25"): self.rejected((t,))
    def test_ASCII_brackets(self): self.rejected(("七-59(1)",))
    def test_unclosed_or_half_brackets(self):
        for t in ("七-59（1","七-59（1)","七-59(1）","七-591）"): self.rejected((t,))
    def test_list_or_multiple_references(self):
        for t in ("七-59（1）、（2）","七-59（1）/2","七-59（1）七-60（2）"): self.rejected((t,))
    def test_only_ASCII_hyphen_not_unicode_hyphens(self):
        for t in ("七－59（1）","七—59（1）","七–59（1）","七−59（1）","七‑59（1）"): self.rejected((t,))
    def test_unsupported_punctuation(self):
        for t in ("七,59（1）","七，59（1）","七.59（1）","七-59.1"): self.rejected((t,))
    def test_prefix_suffix_and_nested_reference(self):
        for t in ("附注七-59（1）","七-59（1）现金","七-59（1）（2）","七-59（1）2"): self.rejected((t,))
    def test_no_whitespace_deletion(self):
        for t in (" 七-59（1）","七-59（1） ","七 -59（1）","七-59（ 1）","七-59\n（1）"): self.rejected((t,))
    def test_no_same_line_join(self): self.rejected(("七-59","（1）"))
    def test_no_cross_line_join(self):
        p,w,c=self.probe(("七-59","（1）"),boxes=((220,100,240,110),(220,115,240,125)))
        self.assertEqual(note_reference_observation(p,w,200,300)["syntax_state"],"NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
        self.assertNotEqual(note_reference_observation(p,w[:1],200,300)["reference_form"],FORM)
        self.assertIsNone(c["current"]["value_cny"])
    def test_no_cross_page_import(self):
        p,w,_=self.probe(); p=replace(p,words=p.words[1:])
        self.assertEqual(note_reference_observation(p,w,200,300)["syntax_state"],"NOTE_GEOMETRY_UNKNOWN")
    def test_rotation(self): self.rejected(("七-59（1）",),rotation=90)
    def test_truncated_page(self):
        p,w,_=self.probe(); p=replace(p,height=105)
        self.assertEqual(note_reference_observation(p,w,200,300)["syntax_state"],"NOTE_GEOMETRY_UNKNOWN")
        self.assertIsNone(cell(p,p.words,105,200,450,1,amount_left=300)["current"]["value_cny"])
    def test_left_boundary(self):
        p,w,_=self.probe(boxes=((199,100,240,110),))
        self.assertEqual(note_reference_observation(p,w,200,300)["syntax_state"],"NOTE_GEOMETRY_UNKNOWN")
    def test_note_touches_money(self): self.rejected(("七-59（1）",),boxes=((220,100,300,110),))
    def test_note_crosses_money(self): self.rejected(("七-59（1）",),boxes=((220,100,310,110),))
    def test_missing_explicit_note_column(self):
        p,_,_=self.probe(); c=cell(p,p.words,105,200,450,1)
        self.assertEqual(c["current"]["state"],"AMBIGUOUS_CELL"); self.assertIsNone(c["current"]["value_cny"])
    def test_money_guard_unchanged(self):
        p,_,_=self.probe(); words=tuple(replace(w,box=(330,100,451,110)) if w.text=="-100.25" else w for w in p.words)
        self.assertEqual(cell(replace(p,words=words),words,105,200,450,1,amount_left=300)["current"]["state"],"COLUMN_EDGE_AMBIGUOUS")
    def test_blank_dash_zero_negative_preserved(self):
        p,_,_=self.probe()
        for t,state,value in ((None,"BLANK_NOT_ZERO",None),("—","DASH_NOT_ZERO",None),("0","OBSERVED_NUMERIC","0"),("-8","OBSERVED_NUMERIC","-8")):
            words=tuple(w for w in p.words if w.text!="-100.25")
            if t is not None: words+=(Word(t,(330,100,390,110)),)
            c=cell(replace(p,words=words),words,105,200,450,1,amount_left=300)["current"]
            self.assertEqual((c["state"],c["value_cny"]),(state,value))
    def test_unit_multiplier(self): self.assertEqual(self.probe(multiplier=10000)[2]["current"]["value_cny"],"-1002500.00")
    def test_old_six_forms_preserved(self):
        for t in ("7","—","七、79","七（79）","七（79）3","七、78（1）"):
            self.assertEqual(self.probe((t,))[2]["current"]["state"],"OBSERVED_NUMERIC")
    def test_native_words_boxes_and_false_certifications(self):
        p,w,_=self.probe(); n=note_reference_observation(p,w,200,300)
        self.assertEqual(n["raw_text"],["七-59（1）"]); self.assertEqual(n["boxes"],[[220,100,240,110]])
        self.assertFalse(n["note_target_resolved"]); self.assertFalse(n["note_semantics_certified"])


class HyphenSubitemRealRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads(SCOPE.read_bytes())
        with patch("requests.sessions.Session.request",side_effect=AssertionError("offline")):
            cls.report=regression.build_regression(SCOPE.read_bytes())
        cls.index=regression.public_index(cls.report)
        cls.changes=[c for r in cls.report["observations"] for cs in r["changes"].values() for c in cs]
    def test_fourteen_sources_only_yutong_three_changes(self):
        self.assertEqual(self.report["counts"],{"issuers":11,"PDF_versions":14,"changed_PDFs":1,"changed_rows":3,
            "raw_multilevel_tokens":21,"currency_blocked_PDFs":4,"unchanged_bundles":14})
        self.assertEqual([r["source"]["security_id"] for r in self.report["observations"] if any(r["changes"].values())],["sh.600066"])
    def test_frozen_code_executed_and_old_unknowns_retained(self):
        self.assertEqual(self.report["manifest"]["baseline_code_commit"],"541b8ca737288c4321ee4d666f1f5706e8e464b6")
        self.assertEqual(self.report["manifest"]["baseline_execution"],"ACTUAL_FROZEN_CODE_NOT_SAVED_OUTPUT")
        for c in self.changes:
            for k in ("current","comparative"):
                self.assertEqual(c["before"][k]["state"],"NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
                self.assertIsNone(c["before"][k]["value_cny"])
    def test_three_numeric_comparatives_three_current_column_blocks(self):
        self.assertEqual(Counter(c["after"][k]["state"] for c in self.changes for k in ("current","comparative")),
                         {"OBSERVED_NUMERIC":3,"COLUMN_EDGE_AMBIGUOUS":3})
        for c in self.changes: self.assertIsNone(c["after"]["current"]["value_cny"])
    def test_exact_comparative_values_and_references(self):
        self.assertEqual([c["after"]["comparative"]["value_cny"] for c in self.changes],["716002911.89","2200722817.75","9282499.82"])
        self.assertEqual([c["after"]["note_column_observation"]["raw_text"] for c in self.changes],[["七-59（1）"],["七-59（1）"],["七-59（2）"]])
        self.assertTrue(all(c["after"]["binding"]["physical_page"]==65 for c in self.changes))
    def test_current_native_money_not_filled_across_boundary(self):
        for c in self.changes:
            row=c["after"]; box=row["current"]["boxes"][0]; split=row["binding"]["table_header"]["column_split"]
            self.assertLess(box[0],split); self.assertGreater(box[2],split)
            self.assertEqual(row["current"]["raw_text"],c["before"]["current"]["raw_text"])
            self.assertEqual(row["current"]["boxes"],c["before"]["current"]["boxes"])
    def test_thirteen_tables_all_fourteen_bundles_unchanged(self):
        for r in self.report["observations"]:
            self.assertEqual(r["bundle_content_hash"],content_hash(r["baseline_snapshot"]["bundle"]))
            if r["source"]["security_id"]!="sh.600066": self.assertEqual(r["current_tables"],r["baseline_snapshot"]["tables"])
    def test_parent_tables_match_actual_frozen_baseline(self):
        p=json.loads((ROOT/self.plan["baseline_private_report"]["path"]).read_bytes())
        for r,old in zip(self.report["observations"],p["observations"]):
            self.assertEqual(r["baseline_snapshot"]["tables"],old["current_tables"])
    def test_previous_twelve_rows_preserved_not_new_recoveries(self):
        for security,count in (("sh.600887",6),("sh.600276",6)):
            r=next(r for r in self.report["observations"] if r["source"]["security_id"]==security)
            rows=[row for t in r["current_tables"].values() for row in t["rows"] if row.get("note_column_observation",{}).get("reference_form") in (regression.FORM,regression.DUNHAO_FORM)]
            self.assertEqual(len(rows),count); self.assertTrue(all(row["note_column_observation"]["syntax_state"]=="OBSERVED_SINGLE_REFERENCE_SYNTAX" for row in rows))
    def test_four_currency_blocks_and_gree_unexecuted(self):
        for r in self.report["observations"]:
            if r["currency"] is None: self.assertTrue(all(t["state"]=="CURRENCY_EVIDENCE_UNKNOWN" and not t["rows"] for t in r["current_tables"].values()))
        r=next(r for r in self.report["observations"] if r["source"]["security_id"]=="sz.000651")
        self.assertIsNone(r["currency"]); self.assertEqual(len(r["native_reference_inventory"]),6)
    def test_only_binder_changed_in_parser_whitelist(self):
        m=self.report["manifest"]
        self.assertEqual([p for p,h in m["parser_code_sha256"].items() if h!=m["baseline_parser_code_sha256"][p]],["scripts/parsing/field_binder.py"])
    def test_source_parent_hashes_fixed(self):
        refs=[self.plan[k] for k in regression.REFS]+[{"path":r["source"]["pdf_path"],"sha256":r["source"]["pdf_sha256"]} for r in self.report["observations"]]
        for ref in refs: self.assertEqual(hashlib.sha256((ROOT/ref["path"]).read_bytes()).hexdigest(),ref["sha256"])
    def test_semantics_complete_lease_PIT_gates_unknown(self):
        for r in self.report["observations"]:
            for k in ("full_lease_cash","full_lease_cash_pit","FCF_conservative"): self.assertIsNone(r[k])
            self.assertFalse(r["baseline_snapshot"]["bundle"]["dependency_preview_only"]["admitted_to_hard_gates"])
        for c in self.changes:
            n=c["after"]["note_column_observation"]; self.assertFalse(n["note_target_resolved"]); self.assertFalse(n["note_semantics_certified"])
        with self.assertRaises(ValueError): load_request(canonical_bytes(self.report))
    def test_yutong_OCF_capex_still_unknown_lease_component_not_added(self):
        r=next(r for r in self.report["observations"] if r["source"]["security_id"]=="sh.600066")
        b=r["baseline_snapshot"]["bundle"]
        for k in ("operating_cash_flow","capex"):
            self.assertEqual(b["fields"][k]["state"],"COLUMN_EDGE_AMBIGUOUS"); self.assertIsNone(b["fields"][k]["observed_value_cny"])
        self.assertEqual(b["lease_financing_component"]["observed_value_cny"],"14990744.76")
    def test_canonical_private_index_independent_identity(self):
        self.assertEqual(PRIVATE.read_bytes(),canonical_bytes(self.report)+b"\n")
        self.assertEqual(PUBLIC.read_bytes(),canonical_bytes(self.index)+b"\n")
        self.assertNotEqual(self.index["logical_content_hash"],self.report["logical_content_hash"])
    def test_no_full_text_published(self):
        raw=canonical_bytes(self.index)
        for key in ("raw_text","text","words","native_text","source_label","label_text","table_header","baseline_snapshot","current_tables"):
            self.assertNotIn(('"'+key+'":').encode(),raw)
        self.assertNotIn("支付其他与筹资活动有关的现金".encode(),raw)
    def test_no_semantics_or_permissions_promotion(self):
        for key,value in (("note_target_resolved",True),("note_semantics_certified",True),("screening_input_exported",True),
                          ("pit_admitted_observation_count",False),("diagnostic_available_at","2026-09-30")):
            with self.assertRaises(ValueError): regression.public_index(seal({**deepcopy(self.report),key:value}))
    def test_reference_box_amount_and_semantics_cannot_smuggle(self):
        for mode in ("ref","box","amount","semantics"):
            r=deepcopy(self.report); c=next(c["after"] for o in r["observations"] for cs in o["changes"].values() for c in cs)
            if mode=="ref": c["note_column_observation"]["raw_text"]=["private paragraph"]
            elif mode=="box": c["binding"]["label_box"]=["paragraph",1,2,3]
            elif mode=="amount": c["comparative"]["value_cny"]="paragraph"
            else: c["note_column_observation"]["note_target_resolved"]=True
            with self.assertRaises(ValueError): regression.public_index(seal(r))
    def test_extra_text_not_projected(self):
        r=deepcopy(self.report); r["full_page"]="do not publish this"
        self.assertNotIn(b"do not publish this",canonical_bytes(regression.public_index(seal(r))))
    def test_unknown_form_or_schema_pair_rejected(self):
        for key,value in (("new_reference_form","ANY_REFERENCE"),("schema","annual-note-dunhao-subitem-regression-scope-v1"),
                          ("baseline_code_commit","541b8ca"),("as_of","2026-02-30"),("extra",1)):
            with self.assertRaises(ValueError): regression.read_plan(canonical_bytes({**deepcopy(self.plan),key:value}))
        with self.assertRaises(ValueError): regression.grammar_forms("ANY_REFERENCE")
    def test_whitelist_and_code_drift(self):
        p=deepcopy(self.plan); p["expected_parser_code_sha256"]["other"]="0"*64
        with self.assertRaises(ValueError): regression.read_plan(canonical_bytes(p))
        p=deepcopy(self.plan); p["expected_parser_code_sha256"]["scripts/parsing/field_binder.py"]="0"*64
        with self.assertRaisesRegex(ValueError,"implementation drift"): regression.build_regression(canonical_bytes(p))
    def test_parent_hash_drift(self):
        for k in regression.REFS:
            p=deepcopy(self.plan); p[k]["sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"hash mismatch"): regression.build_regression(canonical_bytes(p))
    def test_frozen_blob_drift(self):
        p=deepcopy(self.plan); p["baseline_parser_code_sha256"]["scripts/parsing/field_binder.py"]="0"*64
        with self.assertRaisesRegex(ValueError,"blob mismatch"): regression.frozen_snapshot(p,[],ROOT)
    def test_actual_baseline_drift_from_parent(self):
        m=self.report["manifest"]
        snap={"observations":[deepcopy(r["baseline_snapshot"]) for r in self.report["observations"]],
              "baseline_python_support_sha256":m["baseline_python_support_sha256"],
              "pdf_backend_version":m["pdf_backend_version"],"python_version":m["python_version"]}
        snap["observations"][0]["tables"]["cashflow"]["state"]="TAMPERED"
        with patch.object(regression,"frozen_snapshot",return_value=snap):
            with self.assertRaisesRegex(ValueError,"approved parent content"): regression.build_regression(SCOPE.read_bytes())
    def test_binding_header_and_order_changes_rejected(self):
        r=next(r for r in self.report["observations"] if any(r["changes"].values()))
        before=r["baseline_snapshot"]["tables"]["cashflow"]; after=r["current_tables"]["cashflow"]
        for mode in ("header","binding","order"):
            changed=deepcopy(after)
            if mode=="header": changed["header"]["fiscal_year"]=2023
            elif mode=="order": changed["rows"]=list(reversed(changed["rows"]))
            else: changed["rows"][0]["binding"]["statement_scope"]="PARENT"
            with self.assertRaises(ValueError): regression.row_changes(before,changed,form=FORM)
    def test_other_grammar_cannot_mask_new_changes(self):
        r=next(r for r in self.report["observations"] if any(r["changes"].values()))
        for form in (regression.FORM,regression.DUNHAO_FORM):
            with self.assertRaises(ValueError): regression.row_changes(r["baseline_snapshot"]["tables"]["cashflow"],r["current_tables"]["cashflow"],form=form)
    def test_no_overwrite_check_writes_nothing(self):
        args=["--scope",str(SCOPE),"--output",str(PRIVATE),"--public-index",str(PUBLIC)]
        with patch.object(regression,"build_regression",return_value=self.report):
            with self.assertRaisesRegex(ValueError,"refusing to overwrite"): regression.main(args)
            self.assertIsNone(regression.main(args+["--check"]))
    def test_full_report_outside_storage_rejected(self):
        with self.assertRaises(SystemExit),patch("sys.stderr"):
            regression.main(["--scope",str(SCOPE),"--output",str(ROOT/"docs/data-pilots/full.json"),"--public-index",str(PUBLIC)])


if __name__ == "__main__":
    unittest.main()
