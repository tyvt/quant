"""Literal comma-form observations cannot become currency or screening proof."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
import unittest
from unittest.mock import patch

from scripts.parsing.annual_report_parser import _currency_evidence
from scripts.parsing.generic_extractor import Word
from scripts.pilots import assess_annual_currency_comma as assessment
from scripts.screening.contracts import canonical_bytes, content_hash, load_request
from tests.test_annual_report_currency_scope import line, synthetic

ROOT = assessment.ROOT
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-currency-comma-assessment-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-currency-comma-assessment-2026-10-04-v2/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-currency-comma-assessment-2026-10-04-v2/evidence-index.json"


def sample(text=assessment.EXACT, *, following=(), before=(), extra=()):
    p = synthetic([line("五、重要会计政策及会计估计", 50), line("4、记账本位币", 90),
        *before, line(text, 112), *following, line("5、重要性标准", 180), line("六、税项", 250), *extra])
    page = p.pages[0]
    return replace(p, pages=(replace(page, cropbox=(0, 0, 600, 800), mediabox=(0, 0, 600, 800)),))


def seal(r):
    r["logical_content_hash"] = content_hash({k: v for k, v in r.items() if k != "logical_content_hash"})
    return r


class CurrencyCommaFormTests(unittest.TestCase):
    def test_exact_native_form_is_not_currency(self):
        o=assessment.inspect_section(sample()); f=o["native_form_observations"][0]
        self.assertEqual(f["surface_form"],assessment.TARGET_FORM); self.assertTrue(f["future_exact_form_candidate"])
        self.assertFalse(f["currency_verified"]); self.assertFalse(o["currency_verified"])
        self.assertEqual(_currency_evidence(sample()),[])
    def test_period_control_is_distinct_not_repaired(self):
        text=assessment.EXACT.replace("，","。",1)
        self.assertEqual(assessment.surface_form(text),"PERIOD_BEFORE_SUBSIDIARY_CONTEXT_LITERAL_NOT_PROOF")
    def test_subsidiary_comma_context_distinct(self):
        self.assertEqual(assessment.surface_form("境外子公司以美元为记账本位币，编制报表时折算为人民币。"),
                         "OTHER_SUBSIDIARY_OR_SPLIT_COMMA_CONTEXT_NOT_PROOF")
    def test_issuer_only_has_no_comma(self):
        self.assertEqual(assessment.surface_form("本公司以人民币为记账本位币。"),"CURRENCY_TEXT_WITHOUT_CHINESE_COMMA")
    def test_generic_comma_not_supported(self):
        self.assertEqual(assessment.surface_form("记账本位币，未明确主体。"),"OTHER_COMMA_CURRENCY_TEXT_NOT_PROOF")
    def test_other_subject(self):
        for s in ("本集团","其他公司","境外子公司","母公司"):
            self.assertNotEqual(assessment.surface_form(assessment.EXACT.replace("本公司以",s+"以",1)),assessment.TARGET_FORM)
    def test_non_RMB(self):
        self.assertNotEqual(assessment.surface_form(assessment.EXACT.replace("人民币", "美元", 1)),assessment.TARGET_FORM)
    def test_mixed_currency(self):
        self.assertNotEqual(assessment.surface_form(assessment.EXACT.replace("人民币", "人民币及美元", 1)),assessment.TARGET_FORM)
    def test_example_quote_condition(self):
        for t in ("例如："+assessment.EXACT,"若"+assessment.EXACT,"“"+assessment.EXACT+"”"):
            self.assertFalse(any(f["future_exact_form_candidate"] for f in assessment.inspect_section(sample(t))["native_form_observations"]))
    def test_changed_subsidiary_tail(self):
        self.assertNotEqual(assessment.surface_form(assessment.EXACT.replace("个别子公司", "全部子公司")),assessment.TARGET_FORM)
    def test_ASCII_comma_not_normalized(self):
        self.assertNotEqual(assessment.surface_form(assessment.EXACT.replace("，", ",")),assessment.TARGET_FORM)
    def test_missing_final_period(self):
        self.assertNotEqual(assessment.surface_form(assessment.EXACT[:-1]),assessment.TARGET_FORM)
    def test_whitespace_not_deleted(self):
        for t in (" "+assessment.EXACT,assessment.EXACT+" ",assessment.EXACT.replace("人民币","人民 币",1)):
            self.assertNotEqual(assessment.surface_form(t),assessment.TARGET_FORM)
    def test_tokens_not_joined(self):
        p=sample(); page=p.pages[0]; original=page.words[2]
        words=page.words[:2]+(replace(original,text=assessment.EXACT[:15],box=(60,112,200,122)),
            Word(assessment.EXACT[15:],(210,112,460,122)))+page.words[3:]
        o=assessment.inspect_section(replace(p,pages=(replace(page,words=words),)))
        self.assertFalse(any(f["future_exact_form_candidate"] for f in o["native_form_observations"]))
    def test_rows_not_joined(self):
        o=assessment.inspect_section(sample(assessment.EXACT[:15],following=(line(assessment.EXACT[15:],130),)))
        self.assertFalse(any(f["future_exact_form_candidate"] for f in o["native_form_observations"]))
    def test_wrong_policy_not_scanned(self):
        p=sample(); page=p.pages[0]; words=tuple(replace(w,text="五、示例") if w.box[1]==50 else w for w in page.words)
        self.assertEqual(assessment.inspect_section(replace(p,pages=(replace(page,words=words),)))["state"],
                         "NOT_SCANNED_SUBSECTION_NOT_IDENTIFIED")
    def test_missing_chapter_end_not_scanned(self):
        p=sample(); page=p.pages[0]
        self.assertEqual(assessment.inspect_section(replace(p,pages=(replace(page,words=page.words[:-1]),)))["native_form_observations"],[])
    def test_next_subsection_not_scanned(self):
        self.assertFalse(any(f["native_word"]==assessment.EXACT for f in assessment.inspect_section(
            sample("本公司的记账本位币为人民币。",extra=(line(assessment.EXACT,205),)))["native_form_observations"]))
    def test_later_row_not_first_row_candidate(self):
        o=assessment.inspect_section(sample("本公司的记账本位币为人民币。",following=(line(assessment.EXACT,130),)))
        f=next(f for f in o["native_form_observations"] if f["native_word"]==assessment.EXACT)
        self.assertFalse(f["future_exact_form_candidate"])
    def test_rotation_not_admitted(self):
        p=sample(); o=assessment.inspect_section(replace(p,pages=(replace(p.pages[0],rotation=90),)))
        self.assertFalse(any(f["future_exact_form_candidate"] for f in o["native_form_observations"]))
    def test_crop_not_admitted(self):
        p=sample(); o=assessment.inspect_section(replace(p,pages=(replace(p.pages[0],cropbox=(1,0,600,800)),)))
        self.assertFalse(o["native_form_observations"][0]["future_exact_form_candidate"])
    def test_overlength_excluded_not_absent_evidence(self):
        o=assessment.inspect_section(sample(assessment.EXACT+"文"*180))
        self.assertEqual(o["excluded_overlength_words"],1); self.assertEqual(o["native_form_observations"],[])
    def test_extra_claim_does_not_turn_assessment_into_certification(self):
        o=assessment.inspect_section(sample(following=(line("本公司以美元为记账本位币。",130),)))
        self.assertEqual(len(o["native_form_observations"]),2); self.assertFalse(o["currency_verified"])
        self.assertEqual(_currency_evidence(sample(following=(line("本公司以美元为记账本位币。",130),))),[])
    def test_native_text_boxes_and_bounds_retained(self):
        o=assessment.inspect_section(sample()); f=o["native_form_observations"][0]
        self.assertEqual(f["native_word"],assessment.EXACT); self.assertEqual(f["box"],[60,112,460,122])
        self.assertEqual(set(o["bounds"]),{"start","index","section_end","end"})


class CurrencyCommaRealAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads(SCOPE.read_bytes())
        with patch("requests.sessions.Session.request",side_effect=AssertionError("offline")):
            cls.report=assessment.build_assessment(SCOPE.read_bytes())
        cls.index=assessment.public_index(cls.report)
    def changed(self, mutate):
        r=deepcopy(self.report); mutate(r)
        with self.assertRaises(ValueError): assessment.public_index(seal(r))
    def test_fourteen_PDFs_eleven_issuers_no_existing_changes(self):
        self.assertEqual(self.report["counts"]["PDF_versions"],14); self.assertEqual(self.report["counts"]["issuers"],11)
        self.assertEqual(self.report["counts"]["unchanged_bundles_and_tables"],14)
    def test_thirteen_scanned_one_unscanned(self):
        unscanned=[r for r in self.report["observations"] if r["subsection_observation"]["state"]=="NOT_SCANNED_SUBSECTION_NOT_IDENTIFIED"]
        self.assertEqual([r["source"]["security_id"] for r in unscanned],["sh.600585"])
        self.assertEqual(unscanned[0]["subsection_observation"]["native_form_observations"],[])
    def test_twenty_one_native_words_not_coverage_rate(self):
        self.assertEqual(self.report["counts"]["native_currency_words"],21)
        self.assertEqual(sorted(self.report["counts"]["literal_surface_forms"].values()),[1,2,6,12])
    def test_only_Gree_candidate_on_physical_124(self):
        f=[(r["source"]["security_id"],f) for r in self.report["observations"]
           for f in r["subsection_observation"]["native_form_observations"] if f["future_exact_form_candidate"]]
        self.assertEqual(len(f),1); self.assertEqual(f[0][0],"sz.000651"); self.assertEqual(f[0][1]["physical_page"],124)
        self.assertEqual(f[0][1]["native_word"],assessment.EXACT); self.assertFalse(f[0][1]["currency_verified"])
    def test_legacy_currency_ten_four_still_unchanged(self):
        self.assertEqual((self.report["counts"]["legacy_currency_identified"],self.report["counts"]["legacy_currency_blocked"]),(10,4))
        self.assertIsNone(next(r["legacy_currency"] for r in self.report["observations"] if r["source"]["security_id"]=="sz.000651"))
    def test_Gree_scope_bounds_not_global_fulltext(self):
        o=next(r for r in self.report["observations"] if r["source"]["security_id"]=="sz.000651")
        self.assertEqual([o["subsection_observation"]["bounds"][k]["physical_page"] for k in ("start","index","section_end","end")],[124,124,124,152])
        self.assertEqual([p["physical_page"] for p in o["selected_page_observations"]],[124])
    def test_parser_code_equals_frozen_commit(self):
        assessment.verify_parser(self.plan)
        self.assertEqual(self.report["manifest"]["parser_commit"],"f74cc1716daa65c2877c59919c9ede23c5adcacb")
    def test_parent_and_all_PDF_hashes(self):
        for ref in [self.plan[k] for k in assessment.REFS]+[{"path":r["source"]["pdf_path"],"sha256":r["source"]["pdf_sha256"]} for r in self.report["observations"]]:
            self.assertEqual(hashlib.sha256((ROOT/ref["path"]).read_bytes()).hexdigest(),ref["sha256"])
    def test_actual_bundles_tables_equal_parent_hashes(self):
        old=json.loads((ROOT/self.plan["baseline_private_report"]["path"]).read_bytes())
        for r,p in zip(self.report["observations"],old["observations"]):
            self.assertEqual(r["legacy_bundle_sha256"],content_hash(p["baseline_snapshot"]["bundle"]))
            self.assertEqual(r["legacy_tables_sha256"],content_hash(p["current_tables"]))
    def test_canonical_bytes_and_separate_index_identity(self):
        self.assertEqual(PRIVATE.read_bytes(),canonical_bytes(self.report)+b"\n")
        self.assertEqual(PUBLIC.read_bytes(),canonical_bytes(self.index)+b"\n")
        self.assertNotEqual(self.report["logical_content_hash"],self.index["logical_content_hash"])
    def test_no_full_text_channels_in_public_index(self):
        raw=canonical_bytes(self.index)
        for k in ("native_word","native_words","words","text","native_text","declaration_text","table_header"):
            self.assertNotIn(('"'+k+'":').encode(),raw)
        self.assertNotIn(assessment.EXACT.encode(),raw)
    def test_no_currency_or_permissions_promotion(self):
        for k,v in (("currency_verified_by_assessment",True),("currency_support_implemented",True),
            ("production_reader_ready",True),("screening_input_exported",True),("official_selection",True),
            ("diagnostic_available_at","2026-09-30"),("pit_admitted_observation_count",False)):
            self.changed(lambda r,k=k,v=v:r.update({k:v}))
    def test_no_inferred_currency_or_full_lease(self):
        for k in ("currency_inferred","rule_input","full_lease_cash","full_lease_cash_pit","FCF_conservative"):
            self.changed(lambda r,k=k:r["observations"][0].update({k:"CNY"}))
        with self.assertRaises(ValueError): load_request(canonical_bytes(self.report))
    def test_unknown_guard_key_cannot_carry_text(self):
        self.changed(lambda r:r["observations"][0]["subsection_observation"]["native_form_observations"][0]["observed_guards"].update({"private paragraph":True}))
    def test_guard_value_cannot_carry_text(self):
        self.changed(lambda r:r["observations"][0]["subsection_observation"]["native_form_observations"][0]["observed_guards"].update({"same_page_as_subsection_heading":"paragraph"}))
    def test_bound_key_cannot_carry_text(self):
        self.changed(lambda r:r["observations"][0]["subsection_observation"]["bounds"].update({"private paragraph":{}}))
    def test_count_key_or_value_cannot_carry_text(self):
        self.changed(lambda r:r["counts"].update({"private paragraph":1}))
        self.changed(lambda r:r["counts"].update({"native_currency_words":"private paragraph"}))
    def test_surface_form_cannot_carry_text(self):
        self.changed(lambda r:r["counts"]["literal_surface_forms"].update({"private paragraph":1}))
    def test_numeric_boxes_reject_strings_and_nan(self):
        for v in ("private paragraph",math.nan):
            self.changed(lambda r,v=v:r["observations"][0]["subsection_observation"]["native_form_observations"][0].update({"box":[v,1,2,3]}))
    def test_selected_page_hash_rejects_text(self):
        self.changed(lambda r:next(o for o in r["observations"] if o["selected_page_observations"])["selected_page_observations"][0].update({"native_text_sha256":"paragraph"}))
    def test_candidate_flag_not_for_other_forms(self):
        self.changed(lambda r:r["observations"][0]["subsection_observation"]["native_form_observations"][0].update({"future_exact_form_candidate":True}))
    def test_extra_private_fields_not_copied(self):
        r=deepcopy(self.report); r["full_page"]="private paragraph"
        self.assertNotIn(b"private paragraph",canonical_bytes(assessment.public_index(seal(r))))
    def test_invalid_scope_method_search_commit_or_date(self):
        for k,v in (("method","REPAIR"),("search",{**assessment.SEARCH,"join_tokens_or_rows":True}),
            ("parser_commit","f74cc17"),("as_of","2026-02-30"),("extra",True)):
            with self.assertRaises(ValueError): assessment.read_plan(canonical_bytes({**self.plan,k:v}))
    def test_duplicate_or_invalid_reviews(self):
        p=deepcopy(self.plan); p["review_pages"]*=2
        with self.assertRaises(ValueError): assessment.read_plan(canonical_bytes(p))
        for pages in ([True],[0],[124,124],[125,124]):
            p=deepcopy(self.plan); p["review_pages"][0]["physical_pages"]=pages
            with self.assertRaises(ValueError): assessment.read_plan(canonical_bytes(p))
    def test_parser_code_drift(self):
        p=deepcopy(self.plan); p["parser_code_sha256"]["scripts/parsing/field_binder.py"]="0"*64
        with self.assertRaises(ValueError): assessment.build_assessment(canonical_bytes(p))
    def test_parent_hash_drift(self):
        for k in assessment.REFS:
            p=deepcopy(self.plan); p[k]["sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"hash mismatch"): assessment.build_assessment(canonical_bytes(p))
    def test_unknown_review_identity(self):
        p=deepcopy(self.plan); p["review_pages"][0]["security_id"]="sz.999999"
        with self.assertRaisesRegex(ValueError,"missing currency assessment source"): assessment.build_assessment(canonical_bytes(p))
    def test_changed_current_bundle_refused(self):
        original=assessment.parse_annual
        def changed(pdf,source):
            b=original(pdf,source); b["currency"]="USD"; return b
        with patch.object(assessment,"parse_annual",side_effect=changed):
            with self.assertRaisesRegex(ValueError,"changed existing bundle or tables"): assessment.build_assessment(SCOPE.read_bytes())
    def test_no_overwrite_and_check(self):
        args=["--scope",str(SCOPE),"--output",str(PRIVATE),"--public-index",str(PUBLIC)]
        with patch.object(assessment,"build_assessment",return_value=self.report):
            with self.assertRaisesRegex(ValueError,"refusing to overwrite"): assessment.main(args)
            self.assertIsNone(assessment.main(args+["--check"]))
    def test_full_report_outside_storage_rejected(self):
        with patch("sys.stderr"),self.assertRaises(SystemExit):
            assessment.main(["--scope",str(SCOPE),"--output",str(ROOT/"docs/data-pilots/full.json"),"--public-index",str(PUBLIC)])
    def test_development_v1_bytes_preserved(self):
        d=ROOT/"storage/pilots/annual-currency-comma-assessment-2026-10-04-v1"
        for name,h in (("diagnostic-only.json","9185b52da349dc50e2d8e52381040d89884c42b0e27d9fdf9b3256412f1cec9e"),
            ("assessment-tool.py","833b068b098465a96fc698f5bf3073c26448d00c3c9e9cf536c414ea7ec546d2"),
            ("development-evidence-index.json","8023868093555bc3a072516429d4dabde1a50a082708f2d166321a4202b2875a")):
            self.assertEqual(hashlib.sha256((d/name).read_bytes()).hexdigest(),h)


if __name__ == "__main__":
    unittest.main()
