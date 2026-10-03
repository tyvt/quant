"""One explicit joint subject, bounded context, and conflict veto regression."""

from dataclasses import replace
import hashlib
import json
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle, read_scope
from scripts.parsing.annual_report_parser import _currency_evidence
from scripts.parsing.generic_extractor import PDFCache
from scripts.screening.contracts import canonical_bytes, load_request
from tests.test_annual_report_currency_scope import line, synthetic


JOINT = "本公司及境内子公司记账本位币为人民币。"
PREFIX = "本公司下属子公司根据其经营所处的主要经济环境确定其记账本位币，境外子公司"


def policy(statement=JOINT, *, following=()):
    return synthetic([line("五、重要会计政策及会计估计", 50), line("4、记账本位币", 90),
                      line(statement, 112), *following, line("5、重要性标准", 180), line("六、税项", 220)])


class JointCurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-601012-inputs.json").read_bytes()
        cls.source = read_scope(cls.scope_raw)["sources"][0]
        cls.report = build_bundle(cls.scope_raw)
        cls.bundle = cls.report["bundles"][0]

    def test_only_exact_new_joint_sentence_is_positive_evidence(self):
        evidence = _currency_evidence(policy())
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["matched_sentence"], JOINT)
        self.assertNotIn("continuation_context", evidence[0])

    def test_real_statement_and_qualifying_context_have_page_and_boxes(self):
        self.assertEqual(self.bundle["currency"], "CNY")
        e = self.bundle["currency_evidence"][0]
        self.assertEqual((e["physical_page"], e["policy_heading_physical_page"], e["policy_end_physical_page"]), (140, 139, 168))
        self.assertEqual(e["matched_sentence"], JOINT)
        self.assertEqual(e["document_sha256"], self.source["pdf_sha256"])
        self.assertTrue(e["declaration_text"].startswith(JOINT))
        self.assertIn(PREFIX, e["continuation_context"]["text"])
        self.assertEqual(len(e["continuation_context"]["boxes"]), 2)

    def test_seven_real_fields_without_new_amount_or_table_rules(self):
        expected = {"attributable_equity_end": "60895314122.52", "minority_interest_end": "505365076.35",
                    "total_equity_end": "61400679198.87", "parent_net_profit": "-8617528506.44",
                    "total_net_profit": "-8677451528.22", "operating_cash_flow": "-4724978931.84", "capex": "8013068271.53"}
        for key, value in expected.items():
            self.assertEqual(self.bundle["fields"][key]["observed_value_cny"], value)
            self.assertEqual(self.bundle["fields"][key]["state"], "OBSERVED_NUMERIC")

    def test_comparative_values_remain_comparative(self):
        expected = {"attributable_equity_end": "70492311268.60", "minority_interest_end": "219703583.92",
                    "total_equity_end": "70712014852.52", "parent_net_profit": "10751425556.38",
                    "total_net_profit": "10686657614.81", "operating_cash_flow": "8117363683.48", "capex": "9255563996.45"}
        for key, value in expected.items():
            self.assertEqual(self.bundle["fields"][key]["comparative_not_target_value_cny"], value)

    def test_four_column_reconciliations_not_statement_certification(self):
        self.assertEqual(len(self.bundle["reconciliations"]), 4)
        self.assertEqual({c["difference_cny"] for c in self.bundle["reconciliations"]}, {"0.00"})
        self.assertFalse(self.bundle["full_balance_sheet_semantics_certified"])

    def test_new_note_syntax_separate_from_frozen_joint_currency_result(self):
        row = next(r for r in self.bundle["balance_sheet_row_inventory"] if r["source_label"] == "货币资金")
        old = json.loads((ROOT / "docs/data-pilots/annual-joint-currency-601012-2026-10-03-v2/diagnostic-only.json").read_bytes())
        previous = next(r for r in old["bundles"][0]["balance_sheet_row_inventory"] if r["source_label"] == "货币资金")
        self.assertEqual(previous["current"]["state"], "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
        self.assertIsNone(previous["current"]["value_cny"])
        self.assertEqual(row["current"]["state"], "OBSERVED_NUMERIC")
        self.assertFalse(row["note_column_observation"]["note_target_resolved"])

    def test_first_failure_bytes_and_logical_identity_preserved(self):
        raw = (ROOT / "docs/data-pilots/annual-holdout-601012-2026-10-03-v1/diagnostic-only.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "7d7c1072d3b4fb2a18efd845084a57f11e1a053e13aafc00182403ea2d73029f")
        old = json.loads(raw)
        self.assertIsNone(old["bundles"][0]["currency"])
        self.assertNotEqual(old["logical_content_hash"], self.report["logical_content_hash"])

    def test_cache_stability_one_parse_does_not_add_pit_admission(self):
        cache = PDFCache()
        a, b = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))

    def test_lease_audit_pit_and_screening_still_unopened(self):
        self.assertIsNone(self.bundle["lease_financing_component"]["observed_value_cny"])
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["screening_input_exported"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_arbitrary_joint_subjects_not_supported(self):
        for subject in ("本公司及境外子公司", "本公司及所有子公司", "本公司和境内子公司", "本集团及境内子公司",
                        "母公司及境内子公司", "本公司及联营公司", "本公司及部分境内子公司"):
            with self.subTest(subject=subject):
                self.assertEqual(_currency_evidence(policy(subject + "记账本位币为人民币。")), [])

    def test_joint_sentence_grammar_not_fuzzy_expanded(self):
        for sentence in ("本公司及境内子公司的记账本位币为人民币。", "本公司及境内子公司以人民币为记账本位币。",
                         "本公司及境内子公司采用人民币为记账本位币。", "本公司及境内子公司记账本位币为CNY。"):
            self.assertEqual(_currency_evidence(policy(sentence)), [])

    def test_mixed_currency_subjects_not_reduced_to_issuer_rmb(self):
        for sentence in ("本公司以人民币、境内子公司以美元为记账本位币。", "本公司及境内子公司记账本位币分别为人民币、美元。",
                         "本公司及境内子公司记账本位币为人民币或美元。"):
            self.assertEqual(_currency_evidence(policy(sentence)), [])

    def test_joint_non_rmb_currencies_rejected(self):
        for currency in ("美元", "港元", "欧元", "人民币及美元"):
            self.assertEqual(_currency_evidence(policy(JOINT.replace("人民币", currency))), [])

    def test_joint_missing_sentence_end_rejected(self):
        self.assertEqual(_currency_evidence(policy(JOINT[:-1])), [])

    def test_joint_declaration_itself_cannot_be_joined_across_rows(self):
        self.assertEqual(_currency_evidence(policy("本公司及境内子公司", following=(line("记账本位币为人民币。", 128),))), [])
        self.assertEqual(_currency_evidence(policy("本公司及境内子公司", following=(line("的记账本位币为人民币。", 128),))), [])

    def test_examples_conditionals_or_disclaimers_not_admitted(self):
        for sentence in ("例如：" + JOINT, "若" + JOINT, "假设" + JOINT, '“' + JOINT + '”', JOINT + "仅为示例。", JOINT + "但此处不是实际政策。"):
            self.assertEqual(_currency_evidence(policy(sentence)), [])

    def test_inline_conflict_after_old_supported_foreign_clause_rejected(self):
        sentence = "采用人民币为记账本位币。境外子公司采用美元为记账本位币。本公司以美元为记账本位币。"
        self.assertEqual(_currency_evidence(policy(sentence)), [])

    def test_joint_continuation_with_inline_issuer_conflict_rejected(self):
        sentence = JOINT + PREFIX + "采用美元为记账本位币。本公司以美元为记账本位币。"
        self.assertEqual(_currency_evidence(policy(sentence)), [])

    def test_later_claim_of_old_or_joint_subject_rejected(self):
        for claim in ("本公司以美元为记账本位币。", "本公司的记账本位币为美元。", "本集团的记账本位币为美元。",
                      "本公司及境内子公司记账本位币为美元。"):
            self.assertEqual(_currency_evidence(policy(following=(line(claim, 150),))), [])

    def test_repeated_rmb_is_ambiguity_even_when_values_match(self):
        self.assertEqual(_currency_evidence(policy(following=(line(JOINT, 150),))), [])

    def test_incomplete_conflicting_claim_is_not_ignored(self):
        self.assertEqual(_currency_evidence(policy(following=(line("本公司的记账本位币为美元", 150),))), [])

    def test_wrapped_conflict_is_veto_only_not_positive_evidence(self):
        self.assertEqual(_currency_evidence(policy(following=(line("本公司以美元为", 140), line("记账本位币。", 155)))), [])

    def test_exact_subsidiary_context_can_continue_one_adjacent_row(self):
        part = "本公司下属子公司根据其经营所处的主要经济环"
        e = _currency_evidence(policy(JOINT + part, following=(line(PREFIX[len(part):] + "采用美元。", 128),)))
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["matched_sentence"], JOINT)
        self.assertEqual(len(e[0]["continuation_context"]["boxes"]), 2)

    def test_unknown_or_split_joint_subject_tail_not_arbitrarily_joined(self):
        for tail in ("境外子公司采用美元。", "本公司下属子公司采用美元。", "本公司下属子公司根据未知标准", "本公司以美元"):
            self.assertEqual(_currency_evidence(policy(JOINT + tail, following=(line(PREFIX, 128),))), [])

    def test_context_requires_matching_prefix_geometry_and_gap(self):
        part = "本公司下属子公司根据其经营所处的主要经济环"
        for word in (line(PREFIX[len(part):], 150), line(PREFIX[len(part):], 128, width=600), line("未知" + PREFIX[len(part):], 128)):
            self.assertEqual(_currency_evidence(policy(JOINT + part, following=(word,))), [])

    def test_subsidiary_context_never_joined_across_pages(self):
        part = "本公司下属子公司根据其经营所处的主要经济环"
        pdf = policy(JOINT + part, following=(line(PREFIX[len(part):], 128),))
        page = pdf.pages[0]
        first = replace(page, words=page.words[:3])
        second = replace(page, number=2, words=page.words[3:])
        self.assertEqual(_currency_evidence(replace(pdf, pages=(first, second))), [])

    def test_full_single_row_subsidiary_context_does_not_change_currency(self):
        e = _currency_evidence(policy(JOINT + PREFIX + "采用美元为记账本位币。"))
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["matched_sentence"], JOINT)
        self.assertEqual(len(e[0]["continuation_context"]["boxes"]), 1)

    def test_policy_scope_and_rotation_guards_still_apply(self):
        pdf = policy()
        for page in (replace(pdf.pages[0], rotation=90),
                     replace(pdf.pages[0], words=tuple(replace(w, text="五、子公司政策") if w.y == 55 else w for w in pdf.pages[0].words))):
            self.assertEqual(_currency_evidence(replace(pdf, pages=(page,))), [])


if __name__ == "__main__":
    unittest.main()
