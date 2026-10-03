"""Only the exact Chinese ordinal pair; geometry and currency remain separate."""

from dataclasses import replace
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle, markdown
from scripts.parsing.annual_report_parser import _currency_evidence, _currency_section, _title
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, load_request
from tests.test_annual_report_currency_scope import line, synthetic


HEAD = "(四)记账本位币"
END = "(五)重要性标准确定方法和选择依据"
CLAIM = "本公司的记账本位币为人民币。"


def sample(*, head=HEAD, end=END, claim=CLAIM, extra=()):
    return synthetic([line("五、重要会计政策及会计估计", 50), line(head, 90), line(claim, 112),
                      line(end, 170), line("六、税项", 250), *extra])


class ChineseSubsectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600066-inputs.json"
        cls.raw = cls.scope.read_bytes()
        cls.report = build_bundle(cls.raw)
        cls.bundle = cls.report["bundles"][0]

    def test_exact_chinese_pair_accepts_existing_statement_only(self):
        result = _currency_evidence(sample())
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]["heading_text"], result[0]["declaration_text"]), (HEAD, CLAIM))

    def test_global_title_and_Arabic_parenthesized_pair_unchanged(self):
        self.assertEqual(_title(HEAD), HEAD)
        old = sample(head="(6)记账本位币", end="(7)同一控制下和非同一控制下企业合并的会计处理方法")
        self.assertEqual(len(_currency_evidence(old)), 1)

    def test_other_ordinals_and_parentheses_not_generalized(self):
        for head in ("(三)记账本位币", "(五)记账本位币", "(肆)记账本位币", "（四）记账本位币",
                     "(4)记账本位币", "(四四)记账本位币"):
            with self.subTest(head=head):
                self.assertIsNone(_currency_section(sample(head=head)))

    def test_wrong_title_or_truncated_heading_unknown(self):
        for head in ("(四)其他政策", "(四)记账本位", "(四记账本位币", "摘录：(四)记账本位币"):
            with self.subTest(head=head):
                self.assertIsNone(_currency_section(sample(head=head)))

    def test_other_boundary_ordinals_not_accepted(self):
        for end in (END.replace("(五)", "(六)"), END.replace("(五)", "(伍)"), END.replace("(五)", "（五）")):
            with self.subTest(end=end):
                self.assertIsNone(_currency_section(sample(end=end)))

    def test_boundary_title_must_be_exact_and_complete(self):
        for end in ("(五)其他政策", END[:-1], "(五)"):
            with self.subTest(end=end):
                self.assertIsNone(_currency_section(sample(end=end)))

    def test_two_approved_pairs_cannot_exchange_boundaries(self):
        self.assertIsNone(_currency_section(sample(end="(7)同一控制下和非同一控制下企业合并的会计处理方法")))
        self.assertIsNone(_currency_section(sample(head="(6)记账本位币")))

    def test_mixed_styles_not_used_as_fallback(self):
        for end in (END.replace("(五)", "5、"), END.replace("(五)", "五、"), END.replace("(五)", "5.")):
            with self.subTest(end=end):
                self.assertIsNone(_currency_section(sample(end=end)))

    def test_intervening_numbered_section_prevents_skipping(self):
        for text in ("(五)错误标题", "(六)其他政策", "(五错误标题", "5、其他政策"):
            with self.subTest(text=text):
                self.assertIsNone(_currency_section(sample(extra=(line(text, 140),))))

    def test_missing_boundary_not_main_chapter_fallback(self):
        self.assertIsNone(_currency_section(sample(end="正文")))

    def test_duplicate_headings_or_boundary_ambiguous(self):
        for text, y in ((HEAD, 70), ("4、记账本位币", 70), ("(6)记账本位币", 70), (END, 200)):
            with self.subTest(text=text):
                self.assertIsNone(_currency_section(sample(extra=(line(text, y),))))

    def test_head_or_boundary_outside_policy_not_admitted(self):
        for extra in ((line(HEAD, 30),), (line(END, 280),)):
            pdf = sample(head="其他政策" if extra[0].text == HEAD else HEAD,
                         end="正文" if extra[0].text == END else END, extra=extra)
            self.assertIsNone(_currency_section(pdf))

    def test_reversed_boundary_unknown(self):
        self.assertIsNone(_currency_section(sample(end="正文", extra=(line(END, 75),))))

    def test_wrong_policy_scope_or_duplicate_root_unknown(self):
        pdf = sample()
        for root in ("五、子公司重要会计政策及会计估计", "五、其他说明"):
            words = tuple(replace(w, text=root) if w.y == 55 else w for w in pdf.pages[0].words)
            with self.subTest(root=root):
                self.assertIsNone(_currency_section(replace(pdf, pages=(replace(pdf.pages[0], words=words),))))
        self.assertIsNone(_currency_section(sample(extra=(line("五、重要会计政策及会计估计", 20),))))

    def test_clipped_title_or_boundary_unknown(self):
        for y in (55, 95, 175, 255):
            pdf = sample()
            words = tuple(replace(w, box=(*w.box[:2], 650, w.box[3])) if w.y == y else w for w in pdf.pages[0].words)
            with self.subTest(y=y):
                self.assertIsNone(_currency_section(replace(pdf, pages=(replace(pdf.pages[0], words=words),))))

    def test_rotated_or_empty_native_page_unknown(self):
        pdf = sample()
        for page in (replace(pdf.pages[0], rotation=90), replace(pdf.pages[0], text="")):
            self.assertIsNone(_currency_section(replace(pdf, pages=(page,))))

    def test_cross_page_boundary_not_supported(self):
        pdf = sample()
        first = replace(pdf.pages[0], words=pdf.pages[0].words[:3])
        second = replace(pdf.pages[0], number=2, words=pdf.pages[0].words[3:])
        self.assertIsNone(_currency_section(replace(pdf, pages=(first, second))))

    def test_split_heading_and_boundary_not_joined(self):
        for which in ("head", "end"):
            pdf = sample(head="(四)" if which == "head" else HEAD, end="(五)" if which == "end" else END,
                         extra=(line(HEAD[3:] if which == "head" else END[3:], 100 if which == "head" else 182),))
            with self.subTest(which=which):
                self.assertIsNone(_currency_section(pdf))

    def test_fragmented_same_native_row_supported_not_cross_row(self):
        pdf = sample()
        words = tuple(w for w in pdf.pages[0].words if w.y not in (95, 175)) + (
            line("(四)", 90, 60, 25), line(HEAD[3:], 90, 90, 100),
            line("(五)", 170, 60, 25), line(END[3:], 170, 90, 400))
        self.assertEqual(len(_currency_evidence(replace(pdf, pages=(replace(pdf.pages[0], words=words),)))), 1)

    def test_declaration_grammar_not_expanded(self):
        for text in ("本公司记账本位币为人民币。", "子公司的记账本位币为人民币。",
                     "本公司的记账本位币为美元。", "本公司的记账本位币为人民币", "单位：元币种：人民币"):
            with self.subTest(text=text):
                self.assertEqual(_currency_evidence(sample(claim=text)), [])

    def test_conflict_inside_but_not_after_boundary_veto(self):
        self.assertEqual(_currency_evidence(sample(extra=(line("本公司以美元为记账本位币。", 140),))), [])
        self.assertEqual(len(_currency_evidence(sample(extra=(line("本公司以美元为记账本位币。", 200),)))), 1)

    def test_cross_page_or_clipped_declaration_not_admitted(self):
        pdf = sample()
        words = tuple(replace(w, box=(*w.box[:2], 650, w.box[3])) if w.y == 117 else w for w in pdf.pages[0].words)
        self.assertEqual(_currency_evidence(replace(pdf, pages=(replace(pdf.pages[0], words=words),))), [])
        first = replace(pdf.pages[0], words=pdf.pages[0].words[:2])
        second = replace(pdf.pages[0], number=2, words=pdf.pages[0].words[2:])
        self.assertEqual(_currency_evidence(replace(pdf, pages=(first, second))), [])

    def test_real_currency_separately_binds_declaration_and_subsection(self):
        self.assertEqual(self.bundle["currency"], "CNY")
        evidence = self.bundle["currency_evidence"][0]
        self.assertEqual((evidence["heading_text"], evidence["declaration_text"], evidence["physical_page"]),
                         (HEAD, CLAIM, 71))
        self.assertEqual(evidence["document_sha256"], self.bundle["source"]["pdf_sha256"])
        scope = self.bundle["currency_subsection_observation"]
        # This flag says the boundary observation alone is not currency proof.
        self.assertFalse(scope["currency_verified"])
        self.assertEqual((scope["subsection_end"]["text"], scope["subsection_end"]["physical_page"]), (END, 71))
        self.assertEqual(scope["policy_end"]["physical_page"], 98)

    def test_only_two_supported_target_profit_values_observed(self):
        expected = {"parent_net_profit": "4116194422.50", "total_net_profit": "4153925766.34"}
        for key, value in expected.items():
            self.assertEqual(self.bundle["fields"][key]["observed_value_cny"], value)
            self.assertEqual(self.bundle["fields"][key]["state"], "OBSERVED_NUMERIC")
            for row in self.bundle["fields"][key]["candidates"]:
                self.assertEqual(row["binding"]["document_sha256"], self.bundle["source"]["pdf_sha256"])

    def test_missing_equity_fields_remain_unknown(self):
        for key in ("attributable_equity_end", "minority_interest_end", "total_equity_end"):
            self.assertIsNone(self.bundle["fields"][key]["observed_value_cny"])
            self.assertEqual(self.bundle["fields"][key]["state"], "NOT_IDENTIFIED")

    def test_cashflow_column_edges_not_repaired_or_comparative_filled(self):
        for key, prior in (("operating_cash_flow", "4716697728.17"), ("capex", "567039081.24")):
            field = self.bundle["fields"][key]
            self.assertIsNone(field["observed_value_cny"])
            self.assertEqual(field["state"], "COLUMN_EDGE_AMBIGUOUS")
            self.assertEqual(field["comparative_not_target_value_cny"], prior)

    def test_one_comparative_reconciliation_not_current_year_certification(self):
        known = [r for r in self.bundle["reconciliations"] if r["state"] == "RECONCILED"]
        self.assertEqual(len(known), 1)
        self.assertEqual((known[0]["check"], known[0]["column"], known[0]["difference_cny"]),
                         ("OCF_subtotals", "comparative_not_target_value_cny", "0.00"))

    def test_first_v1_actual_frozen_replay_is_unchanged(self):
        old = replay_frozen_bundle(self.scope, ROOT / "docs/data-pilots/annual-holdout-600066-2026-10-03-v1",
                                   "d08668ab0aadf84b9925a08adbeda8148f13710a")
        self.assertEqual(old["json_sha256"], "f079521b6c017b45ae4c89e8a5c275308f1a92bd2dcde3e552f9b29d20ef57e9")
        self.assertEqual(old["markdown_sha256"], "de2f366b8be1e6249f6c5b568441a5da1468a6102b24be039051a53510ee6d93")
        self.assertIsNone(old["report"]["bundles"][0]["currency"])
        self.assertNotEqual(old["logical_content_hash"], self.report["logical_content_hash"])

    def test_cold_warm_cache_and_markdown_stable(self):
        cache = PDFCache()
        a, b = build_bundle(self.raw, cache=cache), build_bundle(self.raw, cache=cache)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(markdown(a), markdown(b))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))

    def test_lease_audit_PIT_and_hard_gates_not_opened(self):
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        for key in ("screening_input_exported", "real_pit_run_authorized", "production_reader_ready"):
            self.assertFalse(self.report[key])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))


if __name__ == "__main__":
    unittest.main()
