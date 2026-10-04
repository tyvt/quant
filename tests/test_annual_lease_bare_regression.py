"""Bare liability labels only identify cash inside a bounded, reconciled table."""
from copy import deepcopy
from dataclasses import replace
from decimal import localcontext
import hashlib
import json
import unittest
from unittest.mock import patch

from scripts.parsing.annual_report_parser import _lease, _lease_bare_payment, _title, _table, LEASE_LABELS, LEASE_BARE_LABEL
from scripts.parsing.generic_extractor import PDFCache, Page, ParsedPDF, Word
from scripts.pilots import build_annual_lease_bare_regression as regression
from scripts.screening.contracts import canonical_bytes, content_hash, load_request

ROOT = regression.ROOT
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-lease-bare-regression-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-lease-bare-fix-2026-10-04-v3/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-lease-bare-fix-2026-10-04-v3/evidence-index.json"
SOURCE = {"security_id": "sh.600001", "issuer": "测试股份有限公司", "fiscal_year": 2024,
          "version": "original", "pdf_sha256": "a" * 64}
HEADING = "支付的其他与筹资活动有关的现金"
CLOSING = HEADING + "说明："


def w(text, y, x=30, right=230):
    return Word(text, (x, y, right, y + 10))


def payment_words(offset=0):
    words = [w(HEADING, 90), w("√适用□不适用", 110), w("单位：元", 130),
             w("币种：人民币", 130, 470, 550), w("项目", 150, right=65),
             w("本期发生额", 150, 330, 410), w("上期发生额", 150, 470, 550)]
    for y, label, current, comparative in ((170, "手续费", "1.00", "0.50"), (190, "资金支付", "2.00", "1.00"),
            (210, LEASE_BARE_LABEL, "10.00", "5.00"), (230, "其他支付", "3.00", "1.50"), (250, "股票支付", "4.00", "2.00"),
            (270, "合计", "20.00", "10.00")):
        words += [w(label, y), w(current, y, 330, 410), w(comparative, y, 470, 550)]
    words += [w(CLOSING, 295)]
    return [replace(x, box=(x.box[0], x.box[1] + offset, x.box[2], x.box[3] + offset)) for x in words]


def fixture():
    words = [w("七、合并财务报表项目注释", 60), *payment_words(), w("十八、母公司财务报表主要项目注释", 780)]
    page = Page(1, 600, 842, 0, "\n".join(x.text for x in words), tuple(words), (0, 0, 600, 842), (0, 0, 600, 842))
    return ParsedPDF("a" * 64, "synthetic", "b" * 64, (page,))


def alter(pdf, transform):
    page = pdf.pages[0]
    words = tuple(transform(list(page.words)))
    return replace(pdf, pages=(replace(page, words=words, text="\n".join(x.text for x in words)),))


def edit_text(pdf, before, after):
    return alter(pdf, lambda ws: [replace(x, text=after) if x.text == before else x for x in ws])


def seal(report):
    report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
    return report


class BoundedBareParserTests(unittest.TestCase):
    def observe(self, pdf=None):
        return _lease(fixture() if pdf is None else pdf, SOURCE)

    def unknown(self, pdf):
        value = self.observe(pdf)
        self.assertIsNone(value["observed_value_cny"])
        self.assertIsNot(value.get("is_complete_lease_cash"), True)
        return value

    def test_payment_table_reconciles_and_binds_all_five_rows(self):
        value = self.observe()
        self.assertEqual((value["observed_value_cny"], value["comparative_not_target_value_cny"]), ("10.00", "5.00"))
        c = value["candidates"][0]
        e = c["payment_table_evidence"]
        self.assertEqual(len(e["components"]), 5)
        self.assertEqual({r["state"] for r in e["reconciliations"].values()}, {"MATCH"})
        for row in [*e["components"], e["printed_total"]]:
            self.assertEqual(row["binding"]["document_sha256"], SOURCE["pdf_sha256"])
            self.assertEqual(row["binding"]["physical_page"], 1)
            self.assertFalse(row["binding"]["pit_admitted"])
        for key in ("unit_and_header_inherited", "label_or_amount_joined", "note_target_resolved", "complete_lease_cash_certified", "public_availability_verified"):
            self.assertIs(e[key], False)

    def test_component_count_is_not_issuer_specific(self):
        # Only replace the total's current/comparative cells, never the lease row.
        pdf = alter(fixture(), lambda ws: [replace(x, text="11.00") if x.y == 275 and x.box[0] == 330 else
            replace(x, text="5.50") if x.y == 275 and x.box[0] == 470 else x for x in ws if x.y not in (195, 235, 255)])
        self.assertEqual(len(self.observe(pdf)["candidates"][0]["payment_table_evidence"]["components"]), 2)

    def test_bare_label_not_in_general_aliases(self):
        self.assertNotIn(LEASE_BARE_LABEL, LEASE_LABELS)
        self.assertEqual(len(LEASE_LABELS), 5)

    def test_wrong_source_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, "source identity mismatch"):
            _lease(fixture(), {**SOURCE, "pdf_sha256": "0" * 64})

    def test_isolated_and_balance_or_contract_context_rejected(self):
        for text in ("合并资产负债表", "租赁负债到期合同金额", "筹资活动产生的各项负债变动情况", "期末余额"):
            self.unknown(edit_text(fixture(), HEADING, text))

    def test_operating_investing_or_receiving_rejected(self):
        for text in ("支付的其他与经营活动有关的现金", "支付的其他与投资活动有关的现金", "收到的其他与筹资活动有关的现金"):
            self.unknown(edit_text(fixture(), HEADING, text))

    def test_nearer_conflicting_context_not_skipped(self):
        self.unknown(alter(fixture(), lambda ws: ws + [w("收到的其他与筹资活动有关的现金", 160)]))

    def test_heading_and_closing_must_be_complete_native_words(self):
        for target in (HEADING, CLOSING):
            for text in (target[:-1], "例：" + target, " " + target):
                self.unknown(edit_text(fixture(), target, text))

    def test_missing_duplicate_or_early_closing_rejected(self):
        self.unknown(alter(fixture(), lambda ws: [x for x in ws if x.text != CLOSING]))
        self.unknown(alter(fixture(), lambda ws: ws + [w(CLOSING, 305)]))
        self.unknown(alter(fixture(), lambda ws: [replace(x, box=(30, 155, 230, 165)) if x.text == CLOSING else x for x in ws]))

    def test_multiple_complete_payment_tables_remain_ambiguous(self):
        value = self.unknown(alter(fixture(), lambda ws: ws + payment_words(350)))
        self.assertEqual(value["state"], "AMBIGUOUS_LABEL")

    def test_orphan_duplicate_heading_is_not_skipped_for_nearest_heading(self):
        for y in (75, 80, 85, 95, 105):
            self.unknown(alter(fixture(), lambda ws: ws + [w(HEADING, y)]))

    def test_same_line_duplicate_heading_remains_unknown(self):
        self.unknown(alter(fixture(), lambda ws: ws + [w(HEADING, 90, 240, 450)]))

    def test_unrelated_same_name_outside_table_is_not_duplicate_payment(self):
        pdf = alter(fixture(), lambda ws: ws + [w(LEASE_BARE_LABEL, 40), w(LEASE_BARE_LABEL, 350)])
        self.assertEqual(self.observe(pdf)["observed_value_cny"], "10.00")
        self.assertEqual(len(self.observe(pdf)["candidates"]), 1)

    def test_duplicate_payment_rows_never_summed_or_selected(self):
        value = self.unknown(edit_text(fixture(), "其他支付", LEASE_BARE_LABEL))
        self.assertEqual(value["state"], "AMBIGUOUS_LABEL")

    def test_other_supported_lease_row_never_summed_or_selected(self):
        for label in LEASE_LABELS:
            self.unknown(edit_text(fixture(), "其他支付", label))

    def test_mother_company_and_scope_duplicates_rejected(self):
        self.unknown(alter(fixture(), lambda ws: [replace(x, box=(30, 80, 230, 90)) if "母公司" in x.text else x for x in ws]))
        self.unknown(alter(fixture(), lambda ws: ws + [w("七、合并财务报表项目注释", 50)]))

    def test_unit_and_currency_must_be_independent_and_unique(self):
        for text in ("单位：千元", "单位：美元", "未知"):
            self.unknown(edit_text(fixture(), "单位：元", text))
        for text in ("单位：元", "币种：人民币"):
            self.unknown(alter(fixture(), lambda ws: [x for x in ws if x.text != text]))
            self.unknown(alter(fixture(), lambda ws: ws + [w(text, 120)]))
        self.unknown(edit_text(fixture(), "币种：人民币", "币种：美元"))

    def test_unit_not_borrowed_before_payment_heading(self):
        self.unknown(alter(fixture(), lambda ws: [replace(x, box=(30, 70, 230, 80)) if x.text == "单位：元" else x for x in ws]))

    def test_unit_conversion_and_original_negative_payment_retained(self):
        pdf = alter(fixture(), lambda ws: [replace(x, text="-10.00") if x.y == 215 and x.box[0] == 330 else
            replace(x, text="0.00") if x.y == 275 and x.box[0] == 330 else x for x in ws])
        pdf = edit_text(pdf, "单位：元", "单位：万元")
        self.assertEqual(self.observe(pdf)["observed_value_cny"], "-100000.00")

    def test_low_ambient_decimal_precision_does_not_round_reconciliation(self):
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(self.observe()["observed_value_cny"], "10.00")

    def test_wrong_or_swapped_periods_and_extra_column_rejected(self):
        for text in ("期末余额", "期初余额", "2023年度", "2024年度", "上期发生额"):
            self.unknown(edit_text(fixture(), "本期发生额", text))
        self.unknown(alter(fixture(), lambda ws: ws + [w("2022年度", 150, 180, 240)]))

    def test_first_or_duplicate_header_not_bypassed(self):
        for y in (140, 200):
            self.unknown(alter(fixture(), lambda ws: ws + [w("项目", y, right=65)]))

    def test_missing_or_duplicate_total_rejected(self):
        self.unknown(alter(fixture(), lambda ws: [x for x in ws if x.y != 275]))
        self.unknown(alter(fixture(), lambda ws: ws + [w("合计", 260)]))

    def test_rows_after_total_and_intervening_paragraph_rejected(self):
        for text in ("未披露的新事项", "60、其他附注", "支付的其他与投资活动有关的现金"):
            self.unknown(alter(fixture(), lambda ws: ws + [w(text, 280)]))

    def test_current_or_comparative_total_mismatch_blocks_both_values(self):
        for x in (330, 470):
            pdf = alter(fixture(), lambda ws: [replace(z, text="99.00") if z.y == 275 and z.box[0] == x else z for z in ws])
            value = self.unknown(pdf)
            self.assertEqual(value["state"], "PAYMENT_TABLE_RECONCILIATION_MISMATCH")
            self.assertIsNone(value["comparative_not_target_value_cny"])
            self.assertIn("MISMATCH", {v["state"] for v in value["candidates"][0]["payment_table_evidence"]["reconciliations"].values()})

    def test_missing_component_amount_is_not_zero_even_if_known_sum_matches(self):
        pdf = alter(fixture(), lambda ws: [replace(x, text="19.00") if x.y == 275 and x.box[0] == 330 else x
            for x in ws if not (x.y == 175 and x.box[0] == 330)])
        value = self.unknown(pdf)
        e = value["candidates"][0]["payment_table_evidence"]
        self.assertEqual(e["components"][0]["current"]["state"], "BLANK_NOT_ZERO")
        self.assertEqual(e["reconciliations"]["current"]["state"], "UNKNOWN_INCOMPLETE_COMPONENTS")

    def test_explicit_zero_component_is_an_observation(self):
        pdf = alter(fixture(), lambda ws: [replace(x, text="0.00") if x.y == 175 and x.box[0] == 330 else
            replace(x, text="19.00") if x.y == 275 and x.box[0] == 330 else x for x in ws])
        self.assertEqual(self.observe(pdf)["observed_value_cny"], "10.00")

    def test_blank_dash_and_comparative_missing_never_backfilled(self):
        for x in (330, 470):
            for text in (None, "—", "-"):
                pdf = alter(fixture(), lambda ws: [replace(z, text=text) if z.y == 215 and z.box[0] == x else z
                    for z in ws if not (z.y == 215 and z.box[0] == x and text is None)])
                self.unknown(pdf)

    def test_unparseable_scientific_and_positive_signed_amount_rejected(self):
        for text in ("+10.00", "1e2", "NaN", "(10.00)", "10.00元"):
            self.unknown(alter(fixture(), lambda ws: [replace(x, text=text) if x.y == 215 and x.box[0] == 330 else x for x in ws]))

    def test_cross_column_duplicate_or_clipped_amount_remains_unknown(self):
        for box in ((430, 210, 445, 220), (330, 210, 610, 220)):
            self.unknown(alter(fixture(), lambda ws: [replace(x, box=box) if x.y == 215 and x.box[0] == 330 else x for x in ws]))
        self.unknown(alter(fixture(), lambda ws: ws + [w("1.00", 210, 300, 320)]))

    def test_split_or_partial_bare_label_and_geometry_rejected(self):
        for text in ("租赁负", "租赁负债余额", "租赁 負债", " 租赁负债"):
            self.unknown(edit_text(fixture(), LEASE_BARE_LABEL, text))
        for box in ((30, 210, 340, 220), (-1, 210, 230, 220)):
            self.unknown(alter(fixture(), lambda ws: [replace(x, box=box) if x.text == LEASE_BARE_LABEL else x for x in ws]))
        self.unknown(alter(fixture(), lambda ws: [replace(x, text="租赁") if x.text == LEASE_BARE_LABEL else x for x in ws] + [w("负债", 210, 100, 130)]))

    def test_rotated_cropped_shifted_or_missing_page_geometry_rejected(self):
        for changes in ({"rotation":90}, {"cropbox":None}, {"mediabox":None}, {"cropbox":(10,0,600,842)},
                        {"cropbox":(10,0,610,842),"mediabox":(10,0,610,842)}):
            pdf=fixture()
            self.unknown(replace(pdf,pages=(replace(pdf.pages[0],**changes),)))

    def test_no_cross_page_context_inheritance_for_bare_label(self):
        pdf=fixture()
        one=replace(pdf.pages[0],words=tuple(w for w in pdf.pages[0].words if w.text==HEADING or "合并财务" in w.text))
        two=replace(pdf.pages[0],number=2,words=tuple(w for w in pdf.pages[0].words if w.text!=HEADING and "合并财务" not in w.text))
        self.unknown(replace(pdf,pages=(one,two)))


class BareRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=SCOPE.read_bytes()
        cls.plan=json.loads(cls.raw)
        with patch("requests.sessions.Session.request",side_effect=AssertionError("offline")):
            cls.report=regression.build_regression(cls.raw)
        cls.index=regression.public_index(cls.report)
        cls.rows={r["source"]["security_id"]:r for r in cls.report["observations"]}

    def test_fourteen_sources_only_yili_component_changes(self):
        self.assertEqual(self.report["counts"],{"issuers":11,"PDF_versions":14,"component_changed_PDFs":1,
            "component_observed_PDFs":10,"component_observed_issuers":7,"evaluated_unknown_PDFs":0,"currency_blocked_PDFs":4})
        self.assertEqual([r["source"]["security_id"] for r in self.report["observations"] if r["component_changed"]],["sh.600887"])
        c=self.rows["sh.600887"]["current_component"]
        self.assertEqual((c["observed_value_cny"],c["comparative_not_target_value_cny"]),("174129885.66","258206679.23"))

    def test_five_rows_and_two_totals_come_from_native_source(self):
        row=self.rows["sh.600887"]
        source=row["source"]
        pdf=PDFCache().parse((ROOT/source["pdf_path"]).read_bytes(),source["pdf_sha256"])
        c=row["current_component"]["candidates"][0]
        e=c["payment_table_evidence"]
        self.assertEqual(len(e["components"]),5)
        self.assertEqual(e["physical_page"],216)
        native={(w.text,w.box) for w in pdf.pages[215].words}
        for item in [*e["components"],e["printed_total"]]:
            self.assertIn((item["source_label"],tuple(item["binding"]["label_box"])),native)
            for k in ("current","comparative"):
                for text,box in zip(item[k]["raw_text"],item[k]["boxes"]):
                    self.assertIn((text,tuple(box)),native)
        self.assertEqual(e["reconciliations"]["current"]["component_sum_cny"],"965171650.04")
        self.assertEqual(e["reconciliations"]["comparative"]["component_sum_cny"],"1045156845.45")

    def test_other_five_real_same_name_rows_do_not_become_payments(self):
        row=self.rows["sh.600887"]
        s=row["source"]
        pdf=PDFCache().parse((ROOT/s["pdf_path"]).read_bytes(),s["pdf_sha256"])
        start=next((p.number,w.y) for p in pdf.pages for w in p.words if _title(w.text)=="合并财务报表项目注释")
        end=next((p.number,w.y) for p in pdf.pages for w in p.words if _title(w.text)=="母公司财务报表主要项目注释")
        matches=[(p,w) for p in pdf.pages for w in p.words if w.text==LEASE_BARE_LABEL]
        self.assertEqual(len(matches),6)
        self.assertEqual([p.number for p,w in matches if _lease_bare_payment(pdf,s,p,w,start,end) is not None],[216])

    def test_multilevel_main_table_note_is_still_blocked(self):
        s=self.rows["sh.600887"]["source"]
        pdf=PDFCache().parse((ROOT/s["pdf_path"]).read_bytes(),s["pdf_sha256"])
        row=next(r for r in _table(pdf,s,"cashflow")["rows"] if r["source_label"]=="支付其他与筹资活动有关的现金")
        self.assertEqual(row["note_column_observation"]["raw_text"],["七（79）3"])
        self.assertEqual(row["current"]["state"],"NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
        self.assertIsNone(row["current"]["value_cny"])

    def test_other_thirteen_components_and_all_non_lease_hashes_unchanged(self):
        old=json.loads((ROOT/self.plan["baseline_private_report"]["path"]).read_bytes())
        previous={regression.source_key(r["source"]):r for r in old["observations"]}
        for row in self.report["observations"]:
            before=previous[regression.source_key(row["source"])]
            self.assertEqual(row["non_lease_bundle_content_hash"],before["non_lease_bundle_content_hash"])
            if row["source"]["security_id"]!="sh.600887":
                self.assertEqual(row["current_component"],before["current_component"])

    def test_parent_refs_and_five_support_parser_files_not_modified(self):
        for n in regression.REFS:
            ref=self.plan[n]
            self.assertEqual(hashlib.sha256((ROOT/ref["path"]).read_bytes()).hexdigest(),ref["sha256"])
        old=json.loads((ROOT/self.plan["baseline_private_report"]["path"]).read_bytes())
        for p,h in old["manifest"]["parser_code_sha256"].items():
            if p!="scripts/parsing/annual_report_parser.py":
                self.assertEqual(self.report["manifest"]["parser_code_sha256"][p],h)

    def test_development_v1_and_v2_are_preserved_not_final_reports(self):
        for version,digest in (("v1","d289ffd7971f63a2ad831efd3df765785c7b8a2ce83a07059adda59e77a85833"),
                ("v2","6580be3c25a25f0f7e62ff0a214f43a58a183479095849b73f848eb5e2c224ef")):
            directory=ROOT/f"storage/pilots/annual-lease-bare-fix-2026-10-04-{version}"
            self.assertEqual(hashlib.sha256((directory/"diagnostic-only.json").read_bytes()).hexdigest(),digest)
            for file in ("development-parser.py","development-tool.py","development-scope.json","development-evidence-index.json"):
                self.assertTrue((directory/file).is_file())

    def test_full_lease_FCF_and_PIT_never_promoted(self):
        for row in self.report["observations"]:
            self.assertIsNone(row["FCF_conservative"])
            self.assertIsNone(row["full_lease_cash"])
            self.assertIsNone(row["current_component"]["pit_value"])
            self.assertFalse(row["current_component"]["is_complete_lease_cash"])
        self.assertEqual(self.report["pit_admitted_observation_count"],0)
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_canonical_artifacts_match_fresh_execution(self):
        self.assertEqual(PRIVATE.read_bytes(),canonical_bytes(self.report)+b"\n")
        self.assertEqual(PUBLIC.read_bytes(),canonical_bytes(self.index)+b"\n")
        self.assertNotEqual(self.report["logical_content_hash"],self.index["logical_content_hash"])

    def test_public_index_has_no_original_text_channels(self):
        raw=canonical_bytes(self.index)
        for key in (b'"text":',b'"words":',b'"raw_text":',b'"native_text":',b'"table_header":',b'"label_text":'):
            self.assertNotIn(key,raw)
        for text in (HEADING,CLOSING,"购买子公司少数股东权益"):
            self.assertNotIn(text.encode("utf-8"),raw)

    def test_unexpected_original_text_is_not_projected(self):
        r=deepcopy(self.report)
        r["entire_original_page"]="private original text"
        self.assertNotIn(b"private original text",canonical_bytes(regression.public_index(seal(r))))

    def test_numeric_boxes_and_cells_cannot_leak_text(self):
        for target in ("label_box","amount"):
            r=deepcopy(self.report)
            c=next(x for x in r["observations"] if x["component_changed"])["current_component"]["candidates"][0]
            if target=="label_box":
                c["binding"]["label_box"]=["text",1,2,3]
            else:
                c["payment_table_evidence"]["components"][0]["current"]["value_cny"]="original paragraph"
            with self.assertRaises(ValueError):
                regression.public_index(seal(r))

    def test_public_label_and_permissions_or_evidence_promotion_rejected(self):
        for k,v in (("screening_input_exported",True),("diagnostic_available_at","2026-09-30"),("pit_admitted_observation_count",False)):
            with self.assertRaises(ValueError):
                regression.public_index(seal({**deepcopy(self.report),k:v}))
        r=deepcopy(self.report)
        c=next(x for x in r["observations"] if x["component_changed"])["current_component"]["candidates"][0]
        c["payment_table_evidence"]["complete_lease_cash_certified"]=True
        with self.assertRaises(ValueError):
            regression.public_index(seal(r))

    def test_bad_scope_commit_label_policy_and_unknown_keys_rejected(self):
        for k,v in (("implementation_base_commit","27ada95"),("bare_label","租赁负债余额"),("extra",1),
                    ("as_of","2026-02-30"),("reconciliation_policy","IGNORE_BLANKS")):
            with self.assertRaises(ValueError):
                regression.read_plan(canonical_bytes({**deepcopy(self.plan),k:v}))

    def test_parent_and_parser_hash_drift_rejected(self):
        for n in regression.REFS:
            plan=deepcopy(self.plan)
            plan[n]["sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"hash mismatch"):
                regression.build_regression(canonical_bytes(plan))
        plan=deepcopy(self.plan)
        plan["expected_parser_code_sha256"]["scripts/parsing/annual_report_parser.py"]="0"*64
        with self.assertRaisesRegex(ValueError,"implementation drift"):
            regression.build_regression(canonical_bytes(plan))

    def test_CLI_no_overwrite_and_check_does_not_write(self):
        args=["--scope",str(SCOPE),"--output",str(PRIVATE),"--public-index",str(PUBLIC)]
        with patch.object(regression,"build_regression",return_value=self.report):
            with self.assertRaisesRegex(ValueError,"refusing to overwrite"):
                regression.main(args)
            self.assertIsNone(regression.main(args+["--check"]))

    def test_private_output_outside_storage_rejected(self):
        with self.assertRaises(SystemExit),patch("sys.stderr"):
            regression.main(["--scope",str(SCOPE),"--output",str(ROOT/"docs/data-pilots/full.json"),"--public-index",str(PUBLIC)])


if __name__=="__main__":
    unittest.main()
