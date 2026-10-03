"""Label assessment boundaries, literal source binding, and safe public projection."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.parsing.generic_extractor import Page, ParsedPDF, Word
from scripts.pilots import assess_annual_lease_labels as lease
from scripts.screening.contracts import canonical_bytes, content_hash

ROOT = lease.ROOT
SCOPE = ROOT / "docs/data-pilots/2026-10-04-annual-lease-assessment-scope.json"
PRIVATE = ROOT / "storage/pilots/annual-lease-assessment-2026-10-04-v2/diagnostic-only.json"
PUBLIC = ROOT / "docs/data-pilots/annual-lease-assessment-2026-10-04-v2/evidence-index.json"


def seal(report):
    report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
    return report


class LeaseFormTests(unittest.TestCase):
    def test_existing_supported_forms_not_expanded(self):
        for label in lease.SUPPORTED:
            self.assertEqual(lease.form_state(label), "EXISTING_PAYMENT_LABEL_SYNTAX")

    def test_five_new_payment_forms_are_only_syntax(self):
        self.assertEqual(len(lease.PAYMENT_VARIANTS), 5)
        for label in lease.PAYMENT_VARIANTS:
            self.assertEqual(lease.form_state(label), "UNSUPPORTED_PAYMENT_LABEL_SYNTAX")

    def test_bare_liability_requires_context(self):
        self.assertEqual(lease.form_state("租赁负债"), "BARE_LIABILITY_LABEL_CONTEXT_REQUIRED")

    def test_expenses_are_not_paid_cash(self):
        for label in lease.EXPENSES:
            self.assertEqual(lease.form_state(label), "EXPENSE_LABEL_NOT_PAID_CASH_PROOF")

    def test_aggregate_is_not_non_duplicated_input(self):
        for label in lease.AGGREGATES:
            self.assertEqual(lease.form_state(label), "AGGREGATE_CASH_LABEL_NOT_NON_DUPLICATED_INPUT")

    def test_inflow_and_lessor_receipts_not_payment_forms(self):
        for label in ("租赁收入", "收到租赁款", "售后租回交易现金流入"):
            self.assertEqual(lease.form_state(label), "OTHER_LEASE_TEXT_NOT_CLASSIFIED")

    def test_whitespace_and_punctuation_not_silently_removed(self):
        for label in ("支付 租赁款", "支付租赁款。", "支付租赁款\n", "租赁 支付的现金"):
            self.assertEqual(lease.form_state(label), "OTHER_LEASE_TEXT_NOT_CLASSIFIED")

    def test_partial_and_conditional_labels_not_payment_forms(self):
        for label in ("支付租赁", "未支付租赁款", "如支付租赁款", "应付租赁款"):
            self.assertEqual(lease.form_state(label), "OTHER_LEASE_TEXT_NOT_CLASSIFIED")

    def test_search_is_literal_and_bounded_not_all_events(self):
        texts = ("支付租赁款", "长期租赁付款", "租金", "租赁" + "长" * 49, "应付利息")
        words = tuple(Word(t, (10, i * 20, 300, i * 20 + 10)) for i, t in enumerate(texts))
        pdf = ParsedPDF("a" * 64, "test", "b" * 64, (Page(1, 600, 800, 0, "", words),))
        rows = lease.inventory(pdf)
        self.assertEqual([r["raw_text"] for r in rows], list(texts[:3]))
        self.assertTrue(all(not r["cash_classification_certified"] for r in rows))
        self.assertTrue(all(not r["is_complete_lease_cash"] for r in rows))

    def test_rotated_label_keeps_literal_but_not_geometry_proof(self):
        page = Page(1, 600, 800, 90, "", (Word("支付租赁款", (10, 10, 100, 20)),))
        row = lease.inventory(ParsedPDF("a" * 64, "test", "b" * 64, (page,)))[0]
        self.assertFalse(row["geometry_observed"])
        self.assertEqual(row["raw_text"], "支付租赁款")

    def test_clipped_label_not_geometry_proof(self):
        page = Page(1, 600, 800, 0, "", (Word("支付租赁款", (10, 10, 610, 20)),))
        self.assertFalse(lease.inventory(ParsedPDF("a" * 64, "t", "b" * 64, (page,)))[0]["geometry_observed"])

    def test_currency_block_not_claimed_as_label_failure(self):
        result = lease.branch_state(None, {"observed_value_cny": None, "candidates": []})
        self.assertEqual(result, "NOT_EVALUATED_CURRENCY_BLOCKED")

    def test_currency_block_with_observation_rejected(self):
        with self.assertRaises(ValueError):
            lease.branch_state(None, {"observed_value_cny": "1", "candidates": []})

    def test_currency_qualified_unknown_not_claimed_as_label_gap(self):
        self.assertEqual(lease.branch_state("CNY", {"observed_value_cny": None, "candidates": []}),
                         "EVALUATED_COMPONENT_UNKNOWN_NOT_AUTOMATIC_LABEL_GAP")

    def test_known_component_is_not_full_lease(self):
        self.assertEqual(lease.branch_state("CNY", {"observed_value_cny": "1", "candidates": []}),
                         "EXISTING_COMPONENT_OBSERVED_NOT_FULL_LEASE")

    def test_public_boxes_only_numeric_ordered_finite(self):
        self.assertEqual(lease.numeric_box([1, 2, 3, 4]), [1, 2, 3, 4])
        for box in ([1, 2, "source text", 4], [True, 2, 3, 4], [1, 2, float("inf"), 4],
                    [1, 2, float("nan"), 4], [5, 2, 3, 4], [-1, 2, 3, 4], [1, 2, 3]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                lease.numeric_box(box)


class LeaseScopeTests(unittest.TestCase):
    def setUp(self):
        self.scope = json.loads(SCOPE.read_text(encoding="utf-8"))

    def parse(self):
        return lease.read_lease_scope(canonical_bytes(self.scope))

    def test_fixed_scope_has_eighteen_review_pages(self):
        self.assertEqual(sum(len(r["physical_pages"]) for r in self.parse()["review_pages"]), 18)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):
            lease.read_lease_scope(b'{"schema":1,"schema":2}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(ValueError):
            lease.read_lease_scope(b'{"schema":NaN}')

    def test_extra_fields_rejected(self):
        self.scope["currency_override"] = "CNY"
        with self.assertRaises(ValueError):
            self.parse()

    def test_duplicate_review_identity_rejected(self):
        self.scope["review_pages"].append(self.scope["review_pages"][0])
        with self.assertRaises(ValueError):
            self.parse()

    def test_nonpositive_duplicate_or_bool_pages_rejected(self):
        for pages in ([0], [1, 1], [True], [2, 1]):
            with self.subTest(pages=pages):
                self.scope["review_pages"][0]["physical_pages"] = pages
                with self.assertRaises(ValueError):
                    self.parse()

    def test_bridge_wrong_identity_rejected(self):
        self.scope["source_bridges"][0]["fiscal_year"] = 2023
        with self.assertRaises(ValueError):
            self.parse()

    def test_bridge_money_must_be_exact_finite_decimal(self):
        for value in (None, "NaN", "1e3", "1", "1,000.00"):
            with self.subTest(value=value):
                self.scope["source_bridges"][0]["total_current_cny"] = value
                with self.assertRaises(ValueError):
                    self.parse()

    def test_scope_reference_hash_drift_rejected(self):
        self.scope["input_refs_scope"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            lease.build_assessment(canonical_bytes(self.scope))

    def test_as_of_drift_rejected(self):
        self.scope["as_of"] = "2026-08-31"
        with self.assertRaisesRegex(ValueError, "as_of drift"):
            lease.build_assessment(canonical_bytes(self.scope))

    def test_parser_identity_drift_rejected(self):
        self.scope["parser_code_sha256"]["scripts/parsing/annual_report_parser.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "parser drift"):
            lease.build_assessment(canonical_bytes(self.scope))

    def test_full_report_refused_outside_storage(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit) as caught:
            lease.main(["--scope", str(SCOPE), "--output", str(ROOT / "docs/leak.json"),
                        "--public-index", str(PUBLIC)])
        self.assertEqual(caught.exception.code, 2)


class LeaseActualEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(PRIVATE.read_text(encoding="utf-8"))
        cls.public = json.loads(PUBLIC.read_text(encoding="utf-8"))
        cls.rows = {r["source"]["security_id"]: r for r in cls.report["observations"]}
        cls.plan = json.loads(SCOPE.read_text(encoding="utf-8"))["source_bridges"][0]
        record = cls.rows["sh.600741"]["selected_pages"][0]
        cls.page = Page(record["physical_page"], record["page_width"], record["page_height"], record["rotation"],
                        record["native_text"], tuple(Word(w["text"], tuple(w["box"])) for w in record["native_words"]))

    def test_counts_are_fourteen_sources_not_old_thirteen(self):
        self.assertEqual(self.report["counts"], {"issuers": 11, "PDF_versions": 14,
                         "existing_component_observed_PDFs": 5, "evaluated_component_unknown_PDFs": 5,
                         "not_evaluated_currency_blocked_PDFs": 4, "selected_pages": 18,
                         "source_dedup_bridges_observed": 1})

    def test_actual_offline_execution_reproduces_both_files(self):
        report = lease.build_assessment(SCOPE.read_bytes())
        self.assertEqual(canonical_bytes(report) + b"\n", PRIVATE.read_bytes())
        self.assertEqual(canonical_bytes(lease.public_index(report)) + b"\n", PUBLIC.read_bytes())

    def test_all_full_inputs_PIT_and_standard_FCF_stay_unknown(self):
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertIsNone(self.report["diagnostic_available_at"])
        for r in self.report["observations"]:
            for k in ("full_lease_cash", "full_lease_cash_pit", "FCF_conservative", "audit_gate"):
                self.assertIsNone(r[k])

    def test_same_parser_and_rule_identity_not_modified(self):
        self.assertFalse(self.report["parser_modified"])
        lease.verify_parser(json.loads(SCOPE.read_text(encoding="utf-8")))
        self.assertEqual(self.report["manifest"]["rule_sha256"], lease.RULE_SHA256)
        for p, digest in self.report["manifest"]["support_code_sha256"].items():
            self.assertEqual(lease.sha((ROOT / p).read_bytes()), digest)

    def test_new_payment_labels_are_bound_to_physical_pages(self):
        expected = {"sh.600900": (200, "支付租赁款"), "sh.600276": (220, "长期租赁付款"),
                    "sh.601012": (246, "支付租赁负债"), "sh.600309": (173, "偿还租赁负债款"),
                    "sh.600066": (126, "偿还租赁负债本金和利息所支付的现金"),
                    "sh.600585": (206, "偿还租赁负债本金和利息所支付的现金")}
        for sec, (page, label) in expected.items():
            self.assertTrue(any(r["physical_page"] == page and r["raw_text"] == label
                                for r in self.rows[sec]["literal_inventory"]))

    def test_yili_bare_label_does_not_certify_liability_or_payment(self):
        rows = [r for r in self.rows["sh.600887"]["literal_inventory"]
                if r["physical_page"] == 216 and r["raw_text"] == "租赁负债"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["form_state"], "BARE_LIABILITY_LABEL_CONTEXT_REQUIRED")
        self.assertFalse(rows[0]["cash_classification_certified"])

    def test_page_text_and_word_hashes_bound_to_source(self):
        for row in self.report["observations"]:
            for page in row["selected_pages"]:
                self.assertEqual(page["document_sha256"], row["source"]["pdf_sha256"])
                self.assertEqual(lease.sha(page["native_text"].encode("utf-8")), page["native_text_sha256"])
            for item in row["literal_inventory"]:
                self.assertEqual(lease.sha(item["raw_text"].encode("utf-8")), item["raw_text_sha256"])

    def test_source_statement_dedup_bridge_is_recorded_not_claimed_missing(self):
        bridge = self.rows["sh.600741"]["source_bridge"]
        self.assertTrue(bridge["source_dedup_statement_observed"])
        self.assertEqual(bridge["state"], "OBSERVED_SOURCE_DEDUP_BRIDGE_NOT_RULE_INPUT")
        self.assertEqual(bridge["operating_remainder_current_cny_observed_arithmetic"], "665859752.58")
        self.assertEqual(bridge["operating_remainder_comparative_cny_observed_arithmetic"], "654367754.44")
        self.assertIsNone(bridge["full_lease_cash_rule_input"])

    def test_bridge_is_same_page_statement_plus_row_not_inferred_difference(self):
        self.assertEqual(lease.observed_bridge(self.page, self.plan), self.rows["sh.600741"]["source_bridge"])

    def test_bridge_statement_hash_or_total_drift_rejected(self):
        for name, value in (("statement_words_sha256", "0" * 64), ("total_current_cny", "1.00")):
            plan = {**self.plan, name: value}
            with self.subTest(name=name), self.assertRaises(ValueError):
                lease.observed_bridge(self.page, plan)

    def test_bridge_cannot_use_duplicate_total_row_or_changed_money(self):
        for name, value in (("component_row_y", 513.91), ("financing_current_cny", "1.00")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                lease.observed_bridge(self.page, {**self.plan, name: value})

    def test_bridge_rotation_rejected(self):
        with self.assertRaises(ValueError):
            lease.observed_bridge(replace(self.page, rotation=90), self.plan)

    def test_currency_block_with_supported_source_label_not_label_gap(self):
        row = self.rows["sh.600741"]
        self.assertEqual(row["existing_lease_branch"], "NOT_EVALUATED_CURRENCY_BLOCKED")
        self.assertTrue(any(i["raw_text"] == "偿还租赁负债支付的金额" and i["physical_page"] == 169
                            for i in row["literal_inventory"]))

    def test_public_projection_matches_saved_bytes(self):
        self.assertEqual(canonical_bytes(lease.public_index(self.report)) + b"\n", PUBLIC.read_bytes())
        self.assertEqual(self.public["private_report_file_sha256"], lease.sha(PRIVATE.read_bytes()))

    def test_index_has_its_own_identity_not_private_logical_hash(self):
        self.assertNotEqual(self.public["logical_content_hash"], self.report["logical_content_hash"])
        for r in (self.report, self.public):
            self.assertEqual(r["logical_content_hash"], content_hash({k: v for k, v in r.items() if k != "logical_content_hash"}))

    def test_public_projection_has_no_page_words_or_source_statement(self):
        raw = PUBLIC.read_text(encoding="utf-8")
        for forbidden in ("native_words", '"native_text":', '"raw_text":', "statement_native_words",
                          "financing_row_native_words", "除计入筹资活动", "其余现金流出均计入"):
            self.assertNotIn(forbidden, raw)

    def test_unlisted_text_channels_are_not_exported(self):
        report = deepcopy(self.report)
        report["observations"][0]["full_page_text"] = "SECRET"
        report["observations"][0]["source"]["native_text"] = "SECRET"
        report["observations"][0]["literal_inventory"].append(
            {"raw_text": "SECRET租赁", "box": [1, 2, 3, 4]})
        self.assertNotIn("SECRET", canonical_bytes(lease.public_index(seal(report))).decode("utf-8"))

    def test_coordinate_text_channel_cannot_leak(self):
        report = deepcopy(self.report)
        word = next(r for row in report["observations"] for r in row["literal_inventory"] if r["raw_text"] in lease.PUBLIC_LABELS)
        word["box"][0] = "SECRET"
        with self.assertRaises(ValueError):
            lease.public_index(seal(report))

    def test_unknown_fields_not_transformed_to_zero(self):
        self.assertTrue(all(r["full_lease_cash"] is None for r in self.public["observations"]))
        self.assertTrue(all(r["full_lease_cash_pit"] is None for r in self.public["observations"]))

    def test_no_reader_screening_or_true_strategy_permission(self):
        for name in ("production_reader_ready", "screening_input_exported", "real_pit_run_authorized", "official_selection"):
            self.assertFalse(self.report[name])
            self.assertFalse(self.public[name])


if __name__ == "__main__":
    unittest.main()
