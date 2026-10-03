"""An economic-environment introduction is not a currency declaration."""

from dataclasses import replace
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle, markdown
from scripts.parsing.annual_report_parser import (
    CURRENCY_INTRO, _currency_evidence, _currency_intro_observation, _currency_section,
)
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, load_request
from tests.test_annual_report_currency_scope import line, synthetic


CLAIM = "本公司及境内子公司记账本位币为人民币。"


def sample(text=None, *, following=(), extra=()):
    return synthetic([line("五、重要会计政策及会计估计", 50), line("4、记账本位币", 90),
                      line(text if text is not None else CURRENCY_INTRO + "，" + CLAIM, 112),
                      *following, line("5、重要性标准", 180), line("六、税项", 250), *extra])


def observation(pdf):
    return _currency_intro_observation(pdf, _currency_section(pdf))


class CurrencyIntroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600309-inputs.json"
        cls.raw = cls.scope.read_bytes()
        cls.report = build_bundle(cls.raw)
        cls.bundle = cls.report["bundles"][0]

    def test_same_native_row_requires_complete_existing_joint_declaration(self):
        evidence = _currency_evidence(sample())
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["matched_sentence"], CLAIM)
        self.assertFalse(evidence[0]["intro_context"]["currency_verified"])

    def test_full_stop_intro_and_adjacent_complete_row_can_bind(self):
        evidence = _currency_evidence(sample(CURRENCY_INTRO + "。", following=(line(CLAIM, 130),)))
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["declaration_text"], CLAIM)
        self.assertEqual(evidence[0]["declaration_box"][1], 130)
        self.assertEqual(evidence[0]["intro_context"]["box"][1], 112)

    def test_legacy_declaration_does_not_require_intro(self):
        pdf = sample(CLAIM)
        self.assertIsNone(observation(pdf))
        self.assertEqual(len(_currency_evidence(pdf)), 1)

    def test_intro_alone_observed_but_never_currency(self):
        pdf = sample(CURRENCY_INTRO + "。")
        self.assertIsNotNone(observation(pdf))
        self.assertEqual(_currency_evidence(pdf), [])

    def test_partial_subject_preserved_not_joined(self):
        pdf = sample(CURRENCY_INTRO + "，本公司及境内", following=(line("子公司记账本位币为人民币。", 130),))
        self.assertIsNotNone(observation(pdf))
        self.assertEqual(_currency_evidence(pdf), [])

    def test_new_with_currency_word_order_not_added(self):
        pdf = sample(CURRENCY_INTRO + "，本公司及境内子公司以人民币为记账本位币。")
        self.assertEqual(_currency_evidence(pdf), [])

    def test_same_row_foreign_tail_not_supported(self):
        pdf = sample(CURRENCY_INTRO + "，" + CLAIM + "本公司之境外子公司采用美元。")
        self.assertEqual(_currency_evidence(pdf), [])

    def test_next_row_tail_not_supported(self):
        pdf = sample(CURRENCY_INTRO + "。", following=(line(CLAIM + "境外子公司采用美元。", 130),))
        self.assertEqual(_currency_evidence(pdf), [])

    def test_extra_narrative_not_part_of_new_path(self):
        pdf = sample(following=(line("境外子公司采用美元为记账本位币。", 130),))
        self.assertEqual(_currency_evidence(pdf), [])

    def test_duplicate_or_conflicting_declarations_rejected(self):
        for claim in (CLAIM, "本公司以美元为记账本位币。"):
            with self.subTest(claim=claim):
                self.assertEqual(_currency_evidence(sample(following=(line(claim, 130),))), [])

    def test_other_currencies_and_mixed_currency_intros_not_recognized(self):
        for intro in (CURRENCY_INTRO.replace("人民币", "美元"), CURRENCY_INTRO.replace("人民币", "人民币和美元")):
            with self.subTest(intro=intro):
                pdf = sample(intro + "，" + CLAIM)
                self.assertIsNone(observation(pdf))
                self.assertEqual(_currency_evidence(pdf), [])

    def test_other_subjects_not_recognized(self):
        for subject in ("境外子公司", "其他公司", "本公司及境外子公司", "本集团"):
            pdf = sample(CURRENCY_INTRO.replace("本公司及境内子公司", subject) + "，" + CLAIM)
            with self.subTest(subject=subject):
                self.assertIsNone(observation(pdf))
                self.assertEqual(_currency_evidence(pdf), [])

    def test_example_quote_or_condition_not_recognized(self):
        for prefix in ("例如：", "如果", "摘录：", "“"):
            pdf = sample(prefix + CURRENCY_INTRO + "，" + CLAIM)
            with self.subTest(prefix=prefix):
                self.assertIsNone(observation(pdf))
                self.assertEqual(_currency_evidence(pdf), [])

    def test_missing_or_wrong_punctuation_not_inferred(self):
        for punctuation in ("", ",", ";", "：", "；"):
            pdf = sample(CURRENCY_INTRO + punctuation + CLAIM)
            with self.subTest(punctuation=punctuation):
                self.assertIsNone(observation(pdf))
                self.assertEqual(_currency_evidence(pdf), [])

    def test_truncated_intro_not_recognized(self):
        for text in ("人民币为本公司及境内子", CURRENCY_INTRO[:-1] + "，" + CLAIM):
            self.assertIsNone(observation(sample(text)))
            self.assertEqual(_currency_evidence(sample(text)), [])

    def test_split_intro_not_joined(self):
        pdf = sample(CURRENCY_INTRO[:16], following=(line(CURRENCY_INTRO[16:] + "，" + CLAIM, 130),))
        self.assertIsNone(observation(pdf))
        self.assertEqual(_currency_evidence(pdf), [])

    def test_fragmented_words_on_same_native_row_bind_one_intro(self):
        pdf = sample()
        words = tuple(w for w in pdf.pages[0].words if w.y != 117) + (
            line(CURRENCY_INTRO + "，", 112, 60, 210), line(CLAIM, 112, 275, 200))
        pdf = replace(pdf, pages=(replace(pdf.pages[0], words=words),))
        self.assertEqual(len(_currency_evidence(pdf)), 1)
        self.assertEqual(observation(pdf)["box"], [60, 112, 475, 122])

    def test_cross_page_intro_or_declaration_not_admitted(self):
        pdf = sample(CURRENCY_INTRO + "。", following=(line(CLAIM, 130),))
        for split in (2, 3):
            first = replace(pdf.pages[0], words=pdf.pages[0].words[:split])
            second = replace(pdf.pages[0], number=2, words=pdf.pages[0].words[split:])
            with self.subTest(split=split):
                self.assertEqual(_currency_evidence(replace(pdf, pages=(first, second))), [])

    def test_intro_and_heading_clipping_or_rotation_not_admitted(self):
        pdf = sample()
        for y in (95, 117):
            words = tuple(replace(w, box=(*w.box[:2], 650, w.box[3])) if w.y == y else w for w in pdf.pages[0].words)
            changed = replace(pdf, pages=(replace(pdf.pages[0], words=words),))
            self.assertIsNone(observation(changed))
            self.assertEqual(_currency_evidence(changed), [])
        self.assertIsNone(observation(replace(pdf, pages=(replace(pdf.pages[0], rotation=90),))))

    def test_clipped_complete_declaration_not_admitted(self):
        pdf = sample(CURRENCY_INTRO + "。", following=(line(CLAIM, 130, 60, 650),))
        self.assertIsNotNone(observation(pdf))
        self.assertEqual(_currency_evidence(pdf), [])

    def test_wide_gap_or_intervening_line_not_skipped(self):
        for following in ((line(CLAIM, 135),), (line("其他说明", 128), line(CLAIM, 145))):
            self.assertEqual(_currency_evidence(sample(CURRENCY_INTRO + "。", following=following)), [])

    def test_broken_or_different_subject_declaration_not_accepted(self):
        for claim in (CLAIM[:-1], "本公司以人民币为记账本位币。", "境内子公司记账本位币为人民币。"):
            self.assertEqual(_currency_evidence(sample(CURRENCY_INTRO + "。", following=(line(claim, 130),))), [])

    def test_declaration_after_next_subsection_not_admitted(self):
        pdf = sample(CURRENCY_INTRO + "。", extra=(line(CLAIM, 200),))
        self.assertEqual(_currency_evidence(pdf), [])

    def test_wrong_policy_or_currency_heading_not_observed(self):
        for y, text in ((55, "五、子公司重要会计政策及会计估计"), (95, "4、其他政策")):
            pdf = sample()
            words = tuple(replace(w, text=text) if w.y == y else w for w in pdf.pages[0].words)
            changed = replace(pdf, pages=(replace(pdf.pages[0], words=words),))
            self.assertIsNone(observation(changed))
            self.assertEqual(_currency_evidence(changed), [])

    def test_missing_or_duplicate_policy_boundaries_unknown(self):
        for extra in ((line("五、重要会计政策及会计估计", 20),), (line("4、记账本位币", 70),)):
            self.assertIsNone(observation(sample(extra=extra)))
        pdf = sample()
        pdf = replace(pdf, pages=(replace(pdf.pages[0], words=pdf.pages[0].words[:-1]),))
        self.assertIsNone(observation(pdf))

    def test_real_intro_bound_to_raw_row_and_policy_geometry_only(self):
        obs = self.bundle["currency_intro_observation"]
        self.assertEqual(obs["document_sha256"], self.bundle["source"]["pdf_sha256"])
        self.assertEqual((obs["physical_page"], obs["matched_intro"]), (95, CURRENCY_INTRO))
        self.assertTrue(obs["text"].endswith("，本公司及境内"))
        self.assertEqual(obs["policy_heading"]["physical_page"], 94)
        self.assertEqual(obs["policy_end"]["physical_page"], 116)
        self.assertEqual(obs["subsection_end"]["physical_page"], 95)
        self.assertFalse(obs["currency_verified"])
        self.assertFalse(obs["public_availability_verified"])

    def test_real_split_declaration_still_blocks_every_table(self):
        self.assertIsNone(self.bundle["currency"])
        self.assertEqual(self.bundle["currency_evidence"], [])
        self.assertEqual({t["state"] for t in self.bundle["table_states"].values()}, {"CURRENCY_EVIDENCE_UNKNOWN"})
        for field in self.bundle["fields"].values():
            self.assertIsNone(field["observed_value_cny"])
            self.assertEqual(field["candidates"], [])

    def test_first_failure_replayed_with_original_code_not_overwritten(self):
        replay = replay_frozen_bundle(self.scope, ROOT / "docs/data-pilots/annual-holdout-600309-2026-10-03-v1",
                                      "9d160ad945a6237d844f08b5da28d670e4856512")
        self.assertEqual(replay["json_sha256"], "421502a95c67414f67d9e8890e16f6088815731ada947f461b0c63bef97bff9c")
        self.assertNotIn("currency_intro_observation", replay["report"]["bundles"][0])
        self.assertNotEqual(replay["logical_content_hash"], self.report["logical_content_hash"])

    def test_cold_warm_canonical_json_and_markdown_stable(self):
        cache = PDFCache()
        a, b = build_bundle(self.raw, cache=cache), build_bundle(self.raw, cache=cache)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(markdown(a), markdown(b))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))

    def test_lease_audit_PIT_and_real_screening_not_opened(self):
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["screening_input_exported"])
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))


if __name__ == "__main__":
    unittest.main()
