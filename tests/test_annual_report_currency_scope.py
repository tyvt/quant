"""Issuer currency word order and bounded policy geometry, not PIT admission."""

from dataclasses import replace
import hashlib
import json
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle, read_scope
from scripts.parsing.annual_report_parser import _currency_evidence, parse_annual
from scripts.parsing.generic_extractor import PDFCache, Page, ParsedPDF, Word
from scripts.screening.contracts import canonical_bytes, load_request


def line(text, y, x=60, width=400):
    return Word(text, (x, y, x + width, y + 10))


def synthetic(words=None, *, rotation=0):
    words = tuple(words or (line("五、重要会计政策及会计估计", 50), line("4、记账本位币", 90),
                            line("本公司的记账本位币为人民币。", 112), line("5、重要性标准", 140), line("六、税项", 180)))
    page = Page(1, 600, 800, rotation, "\n".join(word.text for word in words), words)
    return ParsedPDF("a" * 64, "synthetic", "b" * 64, (page,))


class CurrencyScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope_raw = (ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600276-inputs.json").read_bytes()
        cls.source = read_scope(cls.scope_raw)["sources"][0]
        cls.cache = PDFCache()
        cls.report = build_bundle(cls.scope_raw, cache=cls.cache)
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = cls.cache.parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])

    def changed(self, transform):
        pdf = synthetic()
        words = tuple(transform(list(pdf.pages[0].words)))
        return replace(pdf, pages=(replace(pdf.pages[0], words=words, text="\n".join(word.text for word in words)),))

    def declaration(self, text):
        return self.changed(lambda words: [replace(word, text=text) if word.y == 117 else word for word in words])

    def test_reverse_word_order_binds_real_issuer_policy_and_physical_geometry(self):
        self.assertEqual(self.bundle["currency"], "CNY")
        evidence = self.bundle["currency_evidence"][0]
        self.assertEqual(evidence["physical_page"], 157)
        self.assertEqual(evidence["document_sha256"], self.source["pdf_sha256"])
        self.assertEqual(evidence["heading_text"], "4、记账本位币")
        self.assertEqual(evidence["declaration_text"], "本公司的记账本位币为人民币。")
        self.assertEqual(evidence["policy_heading_physical_page"], 157)
        self.assertEqual(evidence["policy_end_physical_page"], 182)
        self.assertEqual(evidence["policy_end_text"], "六、税项")
        self.assertEqual(len(evidence["declaration_box"]), 4)

    def test_currency_repair_recovers_only_five_supported_primary_fields(self):
        expected = {"attributable_equity_end": "45519861860.32", "minority_interest_end": "570388872.99",
                    "total_equity_end": "46090250733.31", "operating_cash_flow": "7422753038.71", "capex": "1969197487.86"}
        for key, value in expected.items():
            self.assertEqual(self.bundle["fields"][key]["observed_value_cny"], value)
            self.assertEqual(self.bundle["fields"][key]["state"], "OBSERVED_NUMERIC")
        self.assertIsNone(self.bundle["fields"]["parent_net_profit"]["observed_value_cny"])
        self.assertEqual(self.bundle["fields"]["total_net_profit"]["state"], "COLUMN_EDGE_AMBIGUOUS")

    def test_comparative_values_not_used_for_target_year(self):
        expected = {"attributable_equity_end": "40465795358.69", "minority_interest_end": "567291082.64",
                    "total_equity_end": "41033086441.33", "operating_cash_flow": "7643665074.52", "capex": "1483791745.29"}
        for key, value in expected.items():
            self.assertEqual(self.bundle["fields"][key]["comparative_not_target_value_cny"], value)

    def test_four_reconciliations_do_not_certify_unidentified_profit(self):
        self.assertEqual({check["difference_cny"] for check in self.bundle["reconciliations"]}, {"0.00"})
        self.assertEqual(len(self.bundle["reconciliations"]), 4)
        self.assertFalse(self.bundle["full_balance_sheet_semantics_certified"])
        self.assertIsNone(self.bundle["fields"]["parent_net_profit"]["observed_value_cny"])

    def test_complex_note_references_still_fail_closed(self):
        row = next(row for row in self.bundle["balance_sheet_row_inventory"] if row["source_label"] == "货币资金")
        self.assertIsNone(row["current"]["value_cny"])
        self.assertEqual(row["current"]["state"], "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
        self.assertIn("七、", "".join(row["note_column_observation"]["raw_text"]))

    def test_original_first_failure_bytes_and_identity_not_rewritten(self):
        raw = (ROOT / "docs/data-pilots/annual-holdout-600276-2026-10-03-v1/diagnostic-only.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "75c9b75d6ef2343351ab4e742aedb0d28c5c42a7aebbdcb1e731b09d7ab65e3f")
        old = json.loads(raw)
        self.assertIsNone(old["bundles"][0]["currency"])
        self.assertNotEqual(self.report["logical_content_hash"], old["logical_content_hash"])

    def test_lease_audit_version_and_PIT_remain_unopened(self):
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertFalse(self.report["screening_input_exported"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_cache_stability_does_not_add_admission(self):
        cache = PDFCache()
        first, second = build_bundle(self.scope_raw, cache=cache), build_bundle(self.scope_raw, cache=cache)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))

    def test_eight_bounded_currency_sentence_forms(self):
        for text in ("本公司的记账本位币为人民币。", "本集团的记账本位币为人民币。",
                     "本公司以人民币为记账本位币。", "本集团以人民币为记账本位币。",
                     "本公司采用人民币为记账本位币。", "本集团采用人民币为记账本位币。",
                     "以人民币为记账本位币。", "采用人民币为记账本位币。"):
            with self.subTest(sentence=text):
                self.assertEqual(len(_currency_evidence(self.declaration(text))), 1)

    def test_subsidiary_or_other_entity_sentence_not_issuer_statement(self):
        for subject in ("子公司", "境外子公司", "甲公司", "母公司", "联营公司", "本公司的子公司"):
            with self.subTest(subject=subject):
                self.assertEqual(_currency_evidence(self.declaration(subject + "的记账本位币为人民币。")), [])

    def test_quoted_conditional_or_example_statement_not_admitted(self):
        statement = "本公司的记账本位币为人民币。"
        for text in ("例如：" + statement, "假设" + statement, "若" + statement, '“' + statement + '”',
                     statement + "仅为示例。", "本公司以人民币为记账本位币，但此处仅为示例。"):
            with self.subTest(sentence=text):
                self.assertEqual(_currency_evidence(self.declaration(text)), [])

    def test_non_RMB_currency_not_normalized_to_CNY(self):
        for currency in ("美元", "港元", "欧元", "CNY", "人民币或美元"):
            with self.subTest(currency=currency):
                self.assertEqual(_currency_evidence(self.declaration(f"本公司的记账本位币为{currency}。")), [])

    def test_sentence_without_terminal_punctuation_is_incomplete(self):
        self.assertEqual(_currency_evidence(self.declaration("本公司的记账本位币为人民币")), [])

    def test_units_and_RMB_anywhere_are_not_policy_declaration(self):
        self.assertEqual(_currency_evidence(self.declaration("单位：元 币种：人民币")), [])

    def test_missing_currency_heading_blocks_forward_and_reverse_forms(self):
        for statement in ("本公司的记账本位币为人民币。", "本公司以人民币为记账本位币。"):
            pdf = self.declaration(statement)
            words = tuple(replace(word, text="4、其他政策") if word.y == 95 else word for word in pdf.pages[0].words)
            self.assertEqual(_currency_evidence(replace(pdf, pages=(replace(pdf.pages[0], words=words),))), [])

    def test_subsidiary_only_or_wrong_root_policy_scope_unknown(self):
        for text in ("五、子公司重要会计政策及会计估计", "五、母公司政策说明", "五、其他说明",
                     "摘录：五、重要会计政策及会计估计"):
            pdf = self.changed(lambda words: [replace(word, text=text) if word.y == 55 else word for word in words])
            self.assertEqual(_currency_evidence(pdf), [])

    def test_main_policy_root_must_be_unique(self):
        pdf = self.changed(lambda words: words + [line("五、重要会计政策及会计估计", 20)])
        self.assertEqual(_currency_evidence(pdf), [])

    def test_missing_policy_end_is_not_open_ended_scan(self):
        pdf = self.changed(lambda words: [word for word in words if word.y != 185])
        self.assertEqual(_currency_evidence(pdf), [])

    def test_currency_heading_outside_policy_interval_not_admitted(self):
        words = [line("五、重要会计政策及会计估计", 50), line("六、税项", 75),
                 line("4、记账本位币", 90), line("本公司的记账本位币为人民币。", 112)]
        self.assertEqual(_currency_evidence(synthetic(words)), [])

    def test_duplicate_currency_headings_never_choose_first(self):
        self.assertEqual(_currency_evidence(self.changed(lambda words: words + [line("4、记账本位币", 70)])), [])

    def test_conflicting_or_repeated_issuer_claim_before_next_heading_unknown(self):
        for statement in ("本集团的记账本位币为美元。", "本公司的记账本位币为人民币。"):
            pdf = self.changed(lambda words: words + [line(statement, 128)])
            with self.subTest(statement=statement):
                self.assertEqual(_currency_evidence(pdf), [])

    def test_foreign_subsidiary_clause_does_not_replace_issuer_currency(self):
        pdf = self.declaration("采用人民币为记账本位币。境外子公司采用美元为记账本位币。")
        self.assertEqual(len(_currency_evidence(pdf)), 1)

    def test_first_line_other_subject_is_not_skipped_for_later_issuer_statement(self):
        pdf = self.changed(lambda words: [replace(word, text="境外子公司采用美元为记账本位币。")
                                          if word.y == 117 else word for word in words] +
                                         [line("本公司的记账本位币为人民币。", 128)])
        self.assertEqual(_currency_evidence(pdf), [])

    def test_single_row_fragmented_words_preserve_geometry(self):
        pdf = self.changed(lambda words: [word for word in words if word.y != 117] +
                           [line("本公司的", 112, 60, 60), line("记账本位币为人民币。", 112, 120, 150)])
        evidence = _currency_evidence(pdf)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["declaration_text"], "本公司的记账本位币为人民币。")

    def test_two_line_declaration_is_not_arbitrarily_joined(self):
        pdf = self.changed(lambda words: [word for word in words if word.y != 117] +
                           [line("本公司的记账本位币为", 112), line("人民币。", 128)])
        self.assertEqual(_currency_evidence(pdf), [])

    def test_clipped_declaration_or_heading_or_policy_boundary_unknown(self):
        for target_y in (55, 95, 117, 185):
            pdf = self.changed(lambda words: [replace(word, box=(*word.box[:2], 650, word.box[3]))
                                               if word.y == target_y else word for word in words])
            with self.subTest(y=target_y):
                self.assertEqual(_currency_evidence(pdf), [])

    def test_rotated_policy_page_unknown(self):
        self.assertEqual(_currency_evidence(synthetic(rotation=90)), [])

    def test_declaration_gap_over_limit_not_searched(self):
        pdf = synthetic([line("五、重要会计政策及会计估计", 50), line("4、记账本位币", 90),
                         line("本公司的记账本位币为人民币。", 149), line("5、其他政策", 210), line("六、税项", 240)])
        self.assertEqual(_currency_evidence(pdf), [])

    def test_declaration_on_next_page_not_joined(self):
        pdf = synthetic()
        page1 = replace(pdf.pages[0], words=pdf.pages[0].words[:2])
        page2 = replace(pdf.pages[0], number=2, words=pdf.pages[0].words[2:])
        self.assertEqual(_currency_evidence(replace(pdf, pages=(page1, page2))), [])

    def test_root_policy_on_previous_page_still_binds_currency_heading(self):
        pdf = synthetic()
        page1 = replace(pdf.pages[0], words=pdf.pages[0].words[:1])
        page2 = replace(pdf.pages[0], number=2, words=pdf.pages[0].words[1:])
        evidence = _currency_evidence(replace(pdf, pages=(page1, page2)))
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["policy_heading_physical_page"], 1)
        self.assertEqual(evidence[0]["physical_page"], 2)

    def test_unsupported_chapter_number_is_unknown(self):
        pdf = self.changed(lambda words: [replace(word, text="十一、重要会计政策及会计估计") if word.y == 55 else word
                                         for word in words])
        self.assertEqual(_currency_evidence(pdf), [])


if __name__ == "__main__":
    unittest.main()
