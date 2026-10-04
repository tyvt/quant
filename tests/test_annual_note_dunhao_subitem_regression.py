"""One dunhao/subitem grammar; no note target, semantics or gate certification."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import re
import unittest
from unittest.mock import patch

from scripts.parsing.field_binder import cell, note_reference_observation
from scripts.parsing.generic_extractor import Page, Word
from scripts.pilots import build_annual_note_suffix_regression as regression
from scripts.screening.contracts import canonical_bytes, content_hash, load_request

ROOT = regression.ROOT
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-note-dunhao-subitem-regression-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-note-dunhao-subitem-fix-2026-10-04-v1/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-note-dunhao-subitem-fix-2026-10-04-v1/evidence-index.json"
FORM = regression.DUNHAO_FORM


def seal(report):
    report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
    return report


class DunhaoSubitemSyntaxTests(unittest.TestCase):
    def probe(self, texts=("七、78（1）",), *, boxes=None, rotation=0, multiplier=1):
        notes = tuple(Word(t, boxes[i] if boxes else (220+i*30,100,240+i*30,110)) for i,t in enumerate(texts))
        words = notes + (Word("-100.25",(330,100,390,110)),Word("90.50",(480,100,540,110)))
        page = Page(1,600,800,rotation,"synthetic",words)
        return page, notes, cell(page,words,105,200,450,multiplier,amount_left=300)

    def rejected(self, texts, **kwargs):
        page, notes, observed = self.probe(texts,**kwargs)
        self.assertNotEqual(note_reference_observation(page,notes,200,300)["reference_form"],FORM)
        self.assertIsNone(observed["current"]["value_cny"])
        self.assertIsNone(observed["comparative"]["value_cny"])

    def test_complete_single_token(self):
        page,notes,amount=self.probe(); proof=note_reference_observation(page,notes,200,300)
        self.assertEqual((proof["reference_form"],proof["syntax_state"]),(FORM,"OBSERVED_SINGLE_REFERENCE_SYNTAX"))
        self.assertEqual((amount["current"]["value_cny"],amount["comparative"]["value_cny"]),("-100.25","90.50"))
    def test_all_ninety_nine_canonical_chapters(self):
        digits="一二三四五六七八九"
        for n in range(1,100):
            chapter=digits[n-1] if n<10 else ("" if n<20 else digits[n//10-1])+"十"+(digits[n%10-1] if n%10 else "")
            with self.subTest(n=n):
                p,w,_=self.probe((chapter+"、78（1）",))
                self.assertEqual(note_reference_observation(p,w,200,300)["reference_form"],FORM)
    def test_noncanonical_chapters(self):
        for c in ("零","〇","百","一百","两","甲","九九","一十","七八",""):
            self.rejected((c+"、78（1）",))
    def test_large_positive_ASCII_items(self):
        self.assertEqual(self.probe(("九十九、12345（67890）",))[2]["current"]["state"],"OBSERVED_NUMERIC")
    def test_zero_item(self): self.rejected(("七、0（1）",))
    def test_zero_subitem(self): self.rejected(("七、78（0）",))
    def test_leading_zero_item(self): self.rejected(("七、078（1）",))
    def test_leading_zero_subitem(self): self.rejected(("七、78（01）",))
    def test_signed_item(self):
        for t in ("七、-78（1）","七、+78（1）"): self.rejected((t,))
    def test_signed_subitem(self):
        for t in ("七、78（-1）","七、78（+1）"): self.rejected((t,))
    def test_fullwidth_and_chinese_digits(self):
        for t in ("七、７８（1）","七、78（１）","七、七十八（1）","七、78（一）"): self.rejected((t,))
    def test_decimal(self):
        for t in ("1.2","七、78.1（1）","七、78（1.2）"): self.rejected((t,))
    def test_scientific(self):
        for t in ("1e2","七、78e1（1）","七、78（1e2）"): self.rejected((t,))
    def test_money_signs(self):
        for t in ("-1","+1","-100.25"): self.rejected((t,))
    def test_ASCII_brackets(self): self.rejected(("七、78(1)",))
    def test_half_brackets(self):
        for t in ("七、78（1","七、78（1)","七、78(1）","七、781）"): self.rejected((t,))
    def test_lists_multiple_references(self):
        for t in ("七、78（1）、（2）","七、78（1）/2","七、78（1）七、79（2）"): self.rejected((t,))
    def test_hyphen_family_remains_unsupported(self):
        for t in ("七-59（1）","七－59（1）","七—59（1）","五-70（3）"): self.rejected((t,))
    def test_commas_and_dotted_not_dunhao(self):
        for t in ("七,78（1）","七，78（1）","七、78.1","七.78（1）"): self.rejected((t,))
    def test_prefix_or_suffix_or_nested_reference(self):
        for t in ("附注七、78（1）","七、78（1）现金","七、78（1）（2）","七、78（1）2"): self.rejected((t,))
    def test_no_whitespace_deletion(self):
        for t in (" 七、78（1）","七、78（1） ","七、 78（1）","七、78（ 1）","七、78\n（1）"): self.rejected((t,))
    def test_no_same_line_join(self): self.rejected(("七、78","（1）"))
    def test_no_cross_line_join_and_old_fragment_not_new_form(self):
        p,w,_=self.probe(("七、78","（1）"),boxes=((220,100,240,110),(220,115,240,125)))
        self.assertEqual(note_reference_observation(p,w,200,300)["syntax_state"],"NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
        self.assertEqual(note_reference_observation(p,w[:1],200,300)["reference_form"],"CHAPTER_DUNHAO_POSITIVE_ITEM")
    def test_no_cross_page_import(self):
        p,w,_=self.probe(); p=replace(p,words=p.words[1:])
        self.assertEqual(note_reference_observation(p,w,200,300)["syntax_state"],"NOTE_GEOMETRY_UNKNOWN")
    def test_rotation(self): self.rejected(("七、78（1）",),rotation=90)
    def test_truncated_page(self):
        p,w,_=self.probe(); p=replace(p,height=105)
        self.assertEqual(note_reference_observation(p,w,200,300)["syntax_state"],"NOTE_GEOMETRY_UNKNOWN")
        self.assertIsNone(cell(p,p.words,105,200,450,1,amount_left=300)["current"]["value_cny"])
    def test_left_boundary(self):
        p,w,_=self.probe(boxes=((199,100,240,110),))
        self.assertEqual(note_reference_observation(p,w,200,300)["syntax_state"],"NOTE_GEOMETRY_UNKNOWN")
    def test_note_touches_money(self): self.rejected(("七、78（1）",),boxes=((220,100,300,110),))
    def test_note_crosses_money(self): self.rejected(("七、78（1）",),boxes=((220,100,310,110),))
    def test_absent_explicit_note_column(self):
        p,_,_=self.probe(); c=cell(p,p.words,105,200,450,1)
        self.assertEqual(c["current"]["state"],"AMBIGUOUS_CELL")
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
    def test_five_old_forms_preserved(self):
        for t in ("7","—","七、79","七（79）","七（79）3"):
            self.assertEqual(self.probe((t,))[2]["current"]["state"],"OBSERVED_NUMERIC")
    def test_original_words_boxes_false_certifications(self):
        p,w,_=self.probe(); n=note_reference_observation(p,w,200,300)
        self.assertEqual(n["raw_text"],["七、78（1）"]); self.assertEqual(n["boxes"],[[220,100,240,110]])
        self.assertFalse(n["note_target_resolved"]); self.assertFalse(n["note_semantics_certified"])


class DunhaoSubitemRealRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads(SCOPE.read_bytes())
        with patch("requests.sessions.Session.request",side_effect=AssertionError("offline")):
            cls.report=regression.build_regression(SCOPE.read_bytes())
        cls.index=regression.public_index(cls.report)
        cls.changes=[c for r in cls.report["observations"] for cs in r["changes"].values() for c in cs]

    def test_fourteen_PDFs_only_hengrui_six_changes(self):
        self.assertEqual(self.report["counts"],{"issuers":11,"PDF_versions":14,"changed_PDFs":1,"changed_rows":6,
            "raw_multilevel_tokens":21,"currency_blocked_PDFs":4,"unchanged_bundles":14})
        self.assertEqual([r["source"]["security_id"] for r in self.report["observations"] if any(r["changes"].values())],["sh.600276"])
    def test_frozen_baseline_executed_not_copied(self):
        m=self.report["manifest"]
        self.assertEqual(m["baseline_code_commit"],"9b2be0fd137d422fddce183b9b69cba1039b3cfe")
        self.assertEqual(m["baseline_execution"],"ACTUAL_FROZEN_CODE_NOT_SAVED_OUTPUT")
        for c in self.changes:
            for k in ("current","comparative"):
                self.assertEqual(c["before"][k]["state"],"NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
                self.assertIsNone(c["before"][k]["value_cny"])
    def test_twelve_numeric_cells(self):
        self.assertEqual(Counter(c["after"][k]["state"] for c in self.changes for k in ("current","comparative")),{"OBSERVED_NUMERIC":12})
        self.assertTrue(all(c["after"]["binding"]["physical_page"]==149 for c in self.changes))
    def test_exact_source_cashflow_values(self):
        self.assertEqual([(c["after"]["current"]["value_cny"],c["after"]["comparative"]["value_cny"]) for c in self.changes],
            [("1322070742.88","1295530285.40"),("11190382126.13","9249239088.77"),("605485304.68","2607501921.22"),
             ("2591877899.36","1500877315.29"),("275801751.83","861599151.46"),("24239102117.66","20271524269.72")])
    def test_thirteen_tables_all_fourteen_bundles_identical(self):
        for r in self.report["observations"]:
            self.assertEqual(r["bundle_content_hash"],content_hash(r["baseline_snapshot"]["bundle"]))
            if r["source"]["security_id"]!="sh.600276": self.assertEqual(r["current_tables"],r["baseline_snapshot"]["tables"])
    def test_approved_parent_tables_actually_match_baseline(self):
        p=json.loads((ROOT/self.plan["baseline_private_report"]["path"]).read_bytes())
        for r,old in zip(self.report["observations"],p["observations"]):
            self.assertEqual(r["baseline_snapshot"]["tables"],old["current_tables"])
    def test_hyphen_three_rows_still_unknown(self):
        rows=[r for source in self.report["observations"] for t in source["current_tables"].values() for r in t["rows"]]
        other=[r for r in rows if len(r.get("note_column_observation",{}).get("raw_text",[]))==1 and
               re.fullmatch(regression.FORMS["HYPHEN_PARENS_SUBITEM_NOT_IMPLEMENTED"],r["note_column_observation"]["raw_text"][0])]
        self.assertEqual(len(other),3)
        self.assertTrue(all(r["current"]["state"]=="NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE" for r in other))
    def test_yili_six_restored_rows_preserved_including_blank(self):
        r=next(r for r in self.report["observations"] if r["source"]["security_id"]=="sh.600887")
        rows=[row for t in r["current_tables"].values() for row in t["rows"] if row.get("note_column_observation",{}).get("reference_form")==regression.FORM]
        self.assertEqual(len(rows),6)
        self.assertEqual(Counter(row[k]["state"] for row in rows for k in ("current","comparative")),{"OBSERVED_NUMERIC":11,"BLANK_NOT_ZERO":1})
    def test_four_currency_blocks_do_not_execute_note_guard(self):
        for r in self.report["observations"]:
            if r["currency"] is None: self.assertTrue(all(t["state"]=="CURRENCY_EVIDENCE_UNKNOWN" and not t["rows"] for t in r["current_tables"].values()))
    def test_only_binder_changed_in_parser_whitelist(self):
        m=self.report["manifest"]
        self.assertEqual([p for p,h in m["parser_code_sha256"].items() if h!=m["baseline_parser_code_sha256"][p]],["scripts/parsing/field_binder.py"])
    def test_sources_and_frozen_parents_hashes(self):
        for ref in [self.plan[k] for k in regression.REFS]+[{'path':r['source']['pdf_path'],'sha256':r['source']['pdf_sha256']} for r in self.report['observations']]:
            self.assertEqual(hashlib.sha256((ROOT/ref['path']).read_bytes()).hexdigest(),ref['sha256'])
    def test_semantics_lease_PIT_gates_still_unavailable(self):
        for r in self.report["observations"]:
            for k in ("full_lease_cash","full_lease_cash_pit","FCF_conservative"): self.assertIsNone(r[k])
            self.assertFalse(r["baseline_snapshot"]["bundle"]["dependency_preview_only"]["admitted_to_hard_gates"])
        for c in self.changes:
            self.assertFalse(c["after"]["note_column_observation"]["note_target_resolved"])
            self.assertFalse(c["after"]["note_column_observation"]["note_semantics_certified"])
        with self.assertRaises(ValueError): load_request(canonical_bytes(self.report))
    def test_current_profit_and_lease_gaps_not_lifted(self):
        r=next(r for r in self.report["observations"] if r["source"]["security_id"]=="sh.600276")
        b=r["baseline_snapshot"]["bundle"]
        self.assertEqual(b["lease_financing_component"]["observed_value_cny"],"47375294.97")
        for field in ("parent_net_profit","total_net_profit"):
            self.assertIsNone(b["fields"][field]["observed_value_cny"])
    def test_canonical_independent_public_identity(self):
        self.assertEqual(PRIVATE.read_bytes(),canonical_bytes(self.report)+b"\n")
        self.assertEqual(PUBLIC.read_bytes(),canonical_bytes(self.index)+b"\n")
        self.assertNotEqual(self.index["logical_content_hash"],self.report["logical_content_hash"])
    def test_no_full_text_channels_published(self):
        raw=canonical_bytes(self.index)
        for key in ("raw_text","text","words","native_text","source_label","label_text","table_header","baseline_snapshot","current_tables"):
            self.assertNotIn(('"'+key+'":').encode(),raw)
        self.assertNotIn("支付其他与筹资活动有关的现金".encode(),raw)
    def test_no_permission_or_semantics_promotion(self):
        for key,value in (("note_target_resolved",True),("note_semantics_certified",True),("screening_input_exported",True),
                          ("pit_admitted_observation_count",False),("diagnostic_available_at","2026-09-30")):
            with self.assertRaises(ValueError): regression.public_index(seal({**deepcopy(self.report),key:value}))
    def test_no_reference_box_or_amount_text_smuggling(self):
        for mode in ("ref","box","amount","semantics"):
            r=deepcopy(self.report); c=next(c["after"] for o in r["observations"] for cs in o["changes"].values() for c in cs)
            if mode=="ref": c["note_column_observation"]["raw_text"]=["private paragraph"]
            elif mode=="box": c["binding"]["label_box"]=["paragraph",1,2,3]
            elif mode=="amount": c["current"]["value_cny"]="paragraph"
            else: c["note_column_observation"]["note_semantics_certified"]=True
            with self.assertRaises(ValueError): regression.public_index(seal(r))
    def test_extra_text_not_projected(self):
        r=deepcopy(self.report); r["full_page"]="do not publish this"
        self.assertNotIn(b"do not publish this",canonical_bytes(regression.public_index(seal(r))))
    def test_unknown_form_and_schema_pair_rejected(self):
        for key,value in (("new_reference_form","ANY_REFERENCE"),("schema","annual-note-suffix-regression-scope-v1"),
                          ("baseline_code_commit","9b2be0f"),("as_of","2026-02-30"),("extra",1)):
            with self.assertRaises(ValueError): regression.read_plan(canonical_bytes({**deepcopy(self.plan),key:value}))
        with self.assertRaises(ValueError): regression.grammar_forms("ANY_REFERENCE")
    def test_whitelist_and_current_code_drift_rejected(self):
        p=deepcopy(self.plan); p["expected_parser_code_sha256"]["other"]="0"*64
        with self.assertRaises(ValueError): regression.read_plan(canonical_bytes(p))
        p=deepcopy(self.plan); p["expected_parser_code_sha256"]["scripts/parsing/field_binder.py"]="0"*64
        with self.assertRaisesRegex(ValueError,"implementation drift"): regression.build_regression(canonical_bytes(p))
    def test_parent_hash_drift_rejected(self):
        for k in regression.REFS:
            p=deepcopy(self.plan); p[k]["sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"hash mismatch"): regression.build_regression(canonical_bytes(p))
    def test_baseline_blob_hash_drift_rejected(self):
        p=deepcopy(self.plan); p["baseline_parser_code_sha256"]["scripts/parsing/field_binder.py"]="0"*64
        with self.assertRaisesRegex(ValueError,"blob mismatch"): regression.frozen_snapshot(p,[],ROOT)
    def test_actual_baseline_table_drift_from_parent_rejected(self):
        m=self.report["manifest"]
        snap={"observations":[deepcopy(r["baseline_snapshot"]) for r in self.report["observations"]],
              "baseline_python_support_sha256":m["baseline_python_support_sha256"],
              "pdf_backend_version":m["pdf_backend_version"],"python_version":m["python_version"]}
        next(r for r in snap["observations"] if r["source"]["security_id"]=="sh.600276")["tables"]["cashflow"]["state"]="TAMPERED"
        with patch.object(regression,"frozen_snapshot",return_value=snap):
            with self.assertRaisesRegex(ValueError,"approved parent content"): regression.build_regression(SCOPE.read_bytes())
    def test_actual_baseline_bundle_drift_from_parent_rejected(self):
        m=self.report["manifest"]
        snap={"observations":[deepcopy(r["baseline_snapshot"]) for r in self.report["observations"]],
              "baseline_python_support_sha256":m["baseline_python_support_sha256"],
              "pdf_backend_version":m["pdf_backend_version"],"python_version":m["python_version"]}
        next(r for r in snap["observations"] if r["source"]["security_id"]=="sh.600276")["bundle"]["currency"]="USD"
        with patch.object(regression,"frozen_snapshot",return_value=snap):
            with self.assertRaisesRegex(ValueError,"approved parent content"): regression.build_regression(SCOPE.read_bytes())
    def test_binding_header_order_outside_grammar_rejected(self):
        r=next(r for r in self.report["observations"] if any(r["changes"].values()))
        before=r["baseline_snapshot"]["tables"]["cashflow"]; after=r["current_tables"]["cashflow"]
        for mode in ("header","binding","order"):
            changed=deepcopy(after)
            if mode=="header": changed["header"]["fiscal_year"]=2023
            elif mode=="order": changed["rows"]=list(reversed(changed["rows"]))
            else: changed["rows"][0]["binding"]["statement_scope"]="PARENT"
            with self.assertRaises(ValueError): regression.row_changes(before,changed,form=FORM)
    def test_other_form_cannot_be_used_to_mask_changes(self):
        r=next(r for r in self.report["observations"] if any(r["changes"].values()))
        with self.assertRaises(ValueError): regression.row_changes(r["baseline_snapshot"]["tables"]["cashflow"],r["current_tables"]["cashflow"])
    def test_no_overwrite_and_check_no_writes(self):
        args=["--scope",str(SCOPE),"--output",str(PRIVATE),"--public-index",str(PUBLIC)]
        with patch.object(regression,"build_regression",return_value=self.report):
            with self.assertRaisesRegex(ValueError,"refusing to overwrite"): regression.main(args)
            self.assertIsNone(regression.main(args+["--check"]))
    def test_full_report_outside_storage_rejected(self):
        with self.assertRaises(SystemExit),patch("sys.stderr"):
            regression.main(["--scope",str(SCOPE),"--output",str(ROOT/"docs/data-pilots/full.json"),"--public-index",str(PUBLIC)])


if __name__ == "__main__":
    unittest.main()
