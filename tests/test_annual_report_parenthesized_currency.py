"""Exact subsection boundaries are raw observations, not issuer/PIT proof."""

from dataclasses import replace
import hashlib
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle, markdown
from scripts.parsing.annual_report_parser import _currency_evidence, _currency_section, _title
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, load_request
from tests.test_annual_report_currency_scope import line, synthetic


HEADING = "(6)记账本位币"
END = "(7)同一控制下和非同一控制下企业合并的会计处理方法"
CLAIM = "本公司的记账本位币为人民币。"


def sample(*, heading=HEADING, end=END, declaration=CLAIM, extra=()):
    return synthetic([line("五、重要会计政策及会计估计", 50), line(heading, 90),
                      line(declaration, 112), line(end, 170), line("六、税项", 250), *extra])


class ParenthesizedCurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600741-inputs.json"
        cls.raw = cls.scope.read_bytes()
        cls.cache = PDFCache()
        cls.report = build_bundle(cls.raw, cache=cls.cache)
        cls.bundle = cls.report["bundles"][0]

    def test_exact_pair_with_existing_statement_admits_only_scoped_currency(self):
        evidence = _currency_evidence(sample())
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["heading_text"], HEADING)
        self.assertEqual(evidence[0]["declaration_text"], CLAIM)

    def test_global_title_does_not_strip_parentheses(self):
        self.assertEqual(_title(HEADING), HEADING)
        self.assertEqual(_title("6、记账本位币"), "记账本位币")

    def test_wrong_heading_number_not_generalized(self):
        for text in ("(5)记账本位币", "(06)记账本位币", "(六)记账本位币", "（6）记账本位币"):
            with self.subTest(text=text):
                self.assertIsNone(_currency_section(sample(heading=text)))

    def test_wrong_or_truncated_heading_not_recovered(self):
        for text in ("(6)其他政策", "(6)记账本位", "(6记账本位币", "例如：(6)记账本位币"):
            with self.subTest(text=text):
                self.assertEqual(_currency_evidence(sample(heading=text)), [])

    def test_wrong_boundary_number_unknown(self):
        for text in (END.replace("(7)", "(8)"), END.replace("(7)", "(07)"), END.replace("(7)", "（7）")):
            with self.subTest(text=text):
                self.assertIsNone(_currency_section(sample(end=text)))

    def test_wrong_boundary_title_or_truncation_unknown(self):
        for text in ("(7)其他政策", END[:-1], "(7)"):
            with self.subTest(text=text):
                self.assertIsNone(_currency_section(sample(end=text)))

    def test_mixed_numeric_boundary_not_bypassed(self):
        self.assertIsNone(_currency_section(sample(end=END.replace("(7)", "7、"))))

    def test_missing_boundary_not_open_ended(self):
        self.assertIsNone(_currency_section(sample(end="正文")))

    def test_intervening_subsection_not_skipped(self):
        for text in ("(8)其他政策", "(7)错误标题", "7、其他政策", "(7错误标题"):
            with self.subTest(text=text):
                self.assertIsNone(_currency_section(sample(extra=(line(text, 140),))))

    def test_duplicate_currency_headings_unknown(self):
        for text in (HEADING, "6、记账本位币", "(8)记账本位币"):
            with self.subTest(text=text):
                self.assertIsNone(_currency_section(sample(extra=(line(text, 70),))))

    def test_duplicate_boundary_not_first_match(self):
        self.assertIsNone(_currency_section(sample(extra=(line(END, 200),))))

    def test_boundary_preceding_heading_rejected(self):
        pdf = sample(end="正文", extra=(line(END, 75),))
        self.assertIsNone(_currency_section(pdf))

    def test_boundary_outside_policy_rejected(self):
        self.assertIsNone(_currency_section(sample(end="正文", extra=(line(END, 280),))))

    def test_other_policy_root_not_accepted(self):
        pdf = sample()
        words = tuple(replace(word, text="五、子公司重要会计政策及会计估计") if word.y == 55 else word
                      for word in pdf.pages[0].words)
        self.assertIsNone(_currency_section(replace(pdf, pages=(replace(pdf.pages[0], words=words),))))

    def test_duplicate_root_or_missing_main_end_unknown(self):
        self.assertIsNone(_currency_section(sample(extra=(line("五、重要会计政策及会计估计", 20),))))
        pdf = sample()
        words = tuple(word for word in pdf.pages[0].words if word.y != 255)
        self.assertIsNone(_currency_section(replace(pdf, pages=(replace(pdf.pages[0], words=words),))))

    def test_title_geometry_clipping_blocks_scope_binding(self):
        for y in (55, 95, 175, 255):
            pdf = sample()
            words = tuple(replace(word, box=(*word.box[:2], 650, word.box[3])) if word.y == y else word
                          for word in pdf.pages[0].words)
            with self.subTest(y=y):
                self.assertIsNone(_currency_section(replace(pdf, pages=(replace(pdf.pages[0], words=words),))))

    def test_rotated_page_not_admitted(self):
        pdf = sample()
        self.assertIsNone(_currency_section(replace(pdf, pages=(replace(pdf.pages[0], rotation=90),))))

    def test_cross_page_boundary_not_supported(self):
        pdf = sample()
        first = replace(pdf.pages[0], words=pdf.pages[0].words[:3])
        second = replace(pdf.pages[0], number=2, words=pdf.pages[0].words[3:])
        self.assertIsNone(_currency_section(replace(pdf, pages=(first, second))))

    def test_split_heading_or_boundary_not_joined(self):
        for which in ("heading", "end"):
            pdf = sample(heading="(6)" if which == "heading" else HEADING,
                         end="(7)" if which == "end" else END,
                         extra=(line("记账本位币" if which == "heading" else END[3:],
                                     100 if which == "heading" else 182),))
            with self.subTest(which=which):
                self.assertIsNone(_currency_section(pdf))

    def test_native_same_row_fragmented_heading_and_end_allowed(self):
        pdf = sample()
        words = tuple(word for word in pdf.pages[0].words if word.y not in (95, 175)) + (
            line("(6)", 90, 60, 25), line("记账本位币", 90, 90, 100),
            line("(7)", 170, 60, 25), line(END[3:], 170, 90, 400))
        self.assertEqual(len(_currency_evidence(replace(pdf, pages=(replace(pdf.pages[0], words=words),)))), 1)

    def test_statement_after_end_not_currency(self):
        pdf = sample(declaration="正文", extra=(line(CLAIM, 200),))
        self.assertEqual(_currency_evidence(pdf), [])

    def test_conflict_inside_subsection_is_vetoed(self):
        self.assertEqual(_currency_evidence(sample(extra=(line("本公司以美元为记账本位币。", 140),))), [])

    def test_after_end_statement_does_not_extend_subsection(self):
        self.assertEqual(len(_currency_evidence(sample(extra=(line("本公司以美元为记账本位币。", 200),)))), 1)

    def test_missing_de_dialect_and_tail_still_unsupported(self):
        for text in ("本公司记账本位币为人民币。", CLAIM + "本公司下属子公司根据其经营环境确定本位币。"):
            with self.subTest(text=text):
                self.assertIsNotNone(_currency_section(sample(declaration=text)))
                self.assertEqual(_currency_evidence(sample(declaration=text)), [])

    def test_non_RMB_or_other_subject_not_promoted(self):
        for text in ("本公司的记账本位币为美元。", "子公司的记账本位币为人民币。", "单位：元币种：人民币"):
            with self.subTest(text=text):
                self.assertEqual(_currency_evidence(sample(declaration=text)), [])

    def test_clipped_or_wrapped_statement_still_unknown(self):
        pdf = sample()
        words = tuple(replace(word, box=(*word.box[:2], 650, word.box[3])) if word.y == 117 else word
                      for word in pdf.pages[0].words)
        self.assertEqual(_currency_evidence(replace(pdf, pages=(replace(pdf.pages[0], words=words),))), [])
        self.assertEqual(_currency_evidence(sample(declaration="本公司的记账本位币为",
                                                   extra=(line("人民币。", 130),))), [])

    def test_real_scope_binds_four_boundaries_not_currency(self):
        observed = self.bundle["currency_subsection_observation"]
        self.assertEqual(observed["document_sha256"], self.bundle["source"]["pdf_sha256"])
        for name, page, text in (("policy_heading", 84, "二、重要会计政策及会计估计"),
                                  ("heading", 85, HEADING), ("subsection_end", 85, END),
                                  ("policy_end", 103, "三、税项")):
            self.assertEqual((observed[name]["physical_page"], observed[name]["text"]), (page, text))
            self.assertEqual(len(observed[name]["box"]), 4)
        self.assertFalse(observed["currency_verified"])
        self.assertFalse(observed["public_availability_verified"])
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual(self.bundle["currency_evidence"], [])

    def test_real_fields_audit_and_lease_not_restored(self):
        self.assertEqual({item["state"] for item in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})
        for field in self.bundle["fields"].values():
            self.assertIsNone(field["observed_value_cny"])
            self.assertIsNone(field["comparative_not_target_value_cny"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])

    def test_new_identity_does_not_modify_first_failure(self):
        result = ROOT / "docs/data-pilots/annual-holdout-600741-2026-10-03-v1"
        replay = replay_frozen_bundle(self.scope, result, "9cf2ed9e5ecdc795b381e6c2016698bfe10a9cd0")
        self.assertEqual(replay["json_sha256"], "3aa09e2f3bbea3ed3f04a4970b736747a9bc374755802235e6d543640388a6ca")
        self.assertEqual(replay["markdown_sha256"], "f95244c62f56476b9a2c7cd44b63e9afad64e66379e6f8f3acf3a041cd9046ce")
        self.assertNotEqual(self.report["logical_content_hash"], replay["report"]["logical_content_hash"])

    def test_cold_warm_bytes_and_unknowns_are_stable(self):
        cache = PDFCache()
        a, b = build_bundle(self.raw, cache=cache), build_bundle(self.raw, cache=cache)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(markdown(a), markdown(b))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))

    def test_no_PIT_reader_or_hard_gate_export(self):
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertIsNone(self.report["diagnostic_available_at"])
        for key in ("screening_input_exported", "production_reader_ready", "real_pit_run_authorized"):
            self.assertFalse(self.report[key])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))


if __name__ == "__main__":
    unittest.main()
