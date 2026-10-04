"""Repaired generic note-column/line-wrap extraction plus fail-closed inversions."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.extract_annual_report_bundle import ROOT, build_bundle, read_scope
from scripts.parsing.annual_report_parser import parse_annual
from scripts.parsing.field_binder import compact
from scripts.parsing.generic_extractor import PDFCache, Word
from scripts.pilots.replay_frozen_annual_bundle import replay_frozen_bundle
from scripts.screening.contracts import canonical_bytes, content_hash, load_request


class AnnualNoteColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope_path = ROOT / "docs/data-pilots/2026-10-03-annual-report-bundle-600900-inputs.json"
        cls.raw_scope = cls.scope_path.read_bytes()
        cls.source = read_scope(cls.raw_scope)["sources"][0]
        cls.cache = PDFCache()
        cls.report = build_bundle(cls.raw_scope, cache=cls.cache)
        cls.bundle = cls.report["bundles"][0]
        cls.pdf = cls.cache.parse((ROOT / cls.source["pdf_path"]).read_bytes(), cls.source["pdf_sha256"])
        cls.frozen = ROOT / "docs/data-pilots/annual-holdout-600900-2026-10-03-v1"
        cls.old = json.loads((cls.frozen / "diagnostic-only.json").read_bytes())

    def changed(self, number, transform=lambda words: words, **changes):
        pages = list(self.pdf.pages)
        pages[number - 1] = replace(pages[number - 1], words=tuple(transform(list(pages[number - 1].words))), **changes)
        return replace(self.pdf, pages=tuple(pages))

    def parsed(self, pdf):
        return parse_annual(pdf, self.source)

    def change_note(self, value):
        page = self.pdf.pages[87]
        y = next(word.y for word in page.words if word.text == "货币资金")
        return self.changed(88, lambda words: [replace(word, text=value)
                                              if word.text == "1" and abs(word.y - y) <= 2 else word for word in words])

    @staticmethod
    def inventory_row(bundle, label):
        return next(row for row in bundle["balance_sheet_row_inventory"] if row["source_label"] == label)

    def test_all_seven_primary_values_match_post_blind_source_review(self):
        expected = {"attributable_equity_end": "210288410895.97", "minority_interest_end": "11667482817.79",
                    "total_equity_end": "221955893713.76", "parent_net_profit": "32496172808.65",
                    "total_net_profit": "32930199395.19", "operating_cash_flow": "59648468284.22",
                    "capex": "14420079512.74"}
        self.assertEqual({key: value["observed_value_cny"] for key, value in self.bundle["fields"].items()}, expected)
        self.assertTrue(all(field["state"] == "OBSERVED_NUMERIC" for field in self.bundle["fields"].values()))

    def test_comparative_columns_remain_not_target_year(self):
        expected = {"attributable_equity_end": "201453338461.43", "minority_interest_end": "11087267355.07",
                    "total_equity_end": "212540605816.50", "parent_net_profit": "27244616815.27",
                    "total_net_profit": "27967470767.28", "operating_cash_flow": "64749448288.66",
                    "capex": "12417112224.11"}
        self.assertEqual({key: value["comparative_not_target_value_cny"] for key, value in self.bundle["fields"].items()}, expected)

    def test_three_tables_bind_explicit_note_header_and_only_two_amount_columns(self):
        for table in self.bundle["table_states"].values():
            header = table["header"]
            self.assertEqual(header["note_column"]["header_text"], "附注七")
            self.assertEqual(len(header["column_boxes"]), 2)
            self.assertLess(header["label_right"], header["note_column"]["header_box"][0])
            self.assertLess(header["note_column"]["header_box"][2], header["note_column"]["amount_left"])
            self.assertLess(header["note_column"]["amount_left"], header["column_boxes"][0][0])

    def test_note_reference_retained_but_not_used_as_amount(self):
        row = self.inventory_row(self.bundle, "货币资金")
        self.assertEqual(row["note_column_observation"]["raw_text"], ["1"])
        self.assertEqual(row["current"]["value_cny"], "6555341578.63")
        self.assertEqual(row["comparative"]["value_cny"], "7823650159.50")
        self.assertEqual(len(row["note_column_observation"]["boxes"]), 1)

    def test_different_note_id_does_not_change_amount(self):
        row = self.inventory_row(self.parsed(self.change_note("99")), "货币资金")
        self.assertEqual(row["current"]["value_cny"], "6555341578.63")
        self.assertEqual(row["note_column_observation"]["raw_text"], ["99"])

    def test_decimal_amount_in_note_region_is_not_silently_discarded(self):
        row = self.inventory_row(self.parsed(self.change_note("12.34")), "货币资金")
        self.assertIsNone(row["current"]["value_cny"])
        self.assertEqual(row["current"]["state"], "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE")
        self.assertEqual(row["note_column_observation"]["raw_text"], ["12.34"])

    def test_signed_note_value_not_treated_as_reference(self):
        row = self.inventory_row(self.parsed(self.change_note("-100")), "货币资金")
        self.assertIsNone(row["current"]["value_cny"])
        self.assertIsNone(row["comparative"]["value_cny"])

    def test_unknown_third_header_is_not_a_note_column(self):
        pdf = self.changed(88, lambda words: [replace(word, text="说明") if word.text == "附注七" else word for word in words])
        result = self.parsed(pdf)
        self.assertEqual(result["table_states"]["balance"]["state"], "HEADER_UNIT_YEAR_OR_COLUMNS_UNKNOWN")
        self.assertIsNone(result["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_third_year_header_never_discarded_by_position(self):
        pdf = self.changed(88, lambda words: [replace(word, text="2022年12月31日") if word.text == "附注七" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["minority_interest_end"]["observed_value_cny"])

    def test_note_plus_three_amount_headers_rejected(self):
        pdf = self.changed(95, lambda words: words + [Word("2022年度", (550, 731.829, 592, 742.279))])
        self.assertIsNone(self.parsed(pdf)["fields"]["operating_cash_flow"]["observed_value_cny"])

    def test_note_after_amount_columns_not_reinterpreted(self):
        pdf = self.changed(88, lambda words: [replace(word, box=(555, word.box[1], 590, word.box[3]))
                                             if word.text == "附注七" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_missing_comparative_year_not_two_columns(self):
        pdf = self.changed(95, lambda words: [word for word in words if word.text != "2023年度"])
        self.assertIsNone(self.parsed(pdf)["fields"]["capex"]["observed_value_cny"])

    def test_wrong_current_year_with_note_still_unknown(self):
        pdf = self.changed(95, lambda words: [replace(word, text="2025年度") if word.text == "2024年度" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["operating_cash_flow"]["observed_value_cny"])

    def test_wrong_comparative_year_with_note_still_unknown(self):
        pdf = self.changed(88, lambda words: [replace(word, text="2022")
                                             if word.text == "2023" and word.box[1] > 160 else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["total_equity_end"]["observed_value_cny"])

    def test_rotated_note_header_not_accepted(self):
        result = self.parsed(self.changed(88, rotation=90))
        self.assertEqual(result["table_states"]["balance"]["state"], "TABLE_TITLE_GEOMETRY_UNKNOWN")

    def test_note_header_outside_page_is_unknown(self):
        # Clip horizontally without moving the token to a different text row.
        pdf = self.changed(88, lambda words: [replace(word, box=(word.box[0], word.box[1], 620, word.box[3]))
                                             if word.text == "附注七" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["minority_interest_end"]["observed_value_cny"])

    def test_unknown_unit_not_overridden_by_note_support(self):
        pdf = self.changed(88, lambda words: [replace(word, text="单位：未知") if word.text == "单位：元" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_note_amount_boundary_overlap_unknown_not_blank(self):
        field = self.bundle["fields"]["attributable_equity_end"]
        y = sum(field["candidates"][0]["current"]["boxes"][0][1::2]) / 2
        boundary = self.bundle["table_states"]["balance"]["header"]["note_column"]["amount_left"]
        pdf = self.changed(90, lambda words: words + [Word("100.00", (boundary - 5, y - 5, boundary + 5, y + 5))])
        observed = self.parsed(pdf)["fields"]["attributable_equity_end"]
        self.assertIsNone(observed["observed_value_cny"])
        self.assertEqual(observed["state"], "NOTE_AMOUNT_BOUNDARY_AMBIGUOUS")

    def test_amount_spanning_current_comparative_boundary_unknown(self):
        split = self.bundle["table_states"]["balance"]["header"]["column_split"]
        pdf = self.changed(90, lambda words: [replace(word, box=(word.box[0], word.box[1], split + 5, word.box[3]))
                                             if word.text == "210,288,410,895.97" else word for word in words])
        field = self.parsed(pdf)["fields"]["attributable_equity_end"]
        self.assertIsNone(field["observed_value_cny"])
        self.assertEqual(field["state"], "COLUMN_EDGE_AMBIGUOUS")

    def test_exact_parenthesized_equity_alias_and_two_line_evidence(self):
        for key in ("attributable_equity_end", "total_equity_end"):
            row = self.bundle["fields"][key]["candidates"][0]
            self.assertIn("（或股东权益）合计", row["source_label"])
            self.assertEqual(len(row["binding"]["label_text"]), 2)

    def test_profit_qualifier_two_line_evidence_not_discarded(self):
        row = self.bundle["fields"]["parent_net_profit"]["candidates"][0]
        self.assertEqual(len(row["binding"]["label_text"]), 2)
        self.assertIn("净亏损", row["source_label"])

    def test_capex_wrap_joins_only_explicit_cash_payment_label(self):
        row = self.bundle["fields"]["capex"]["candidates"][0]
        self.assertEqual(row["source_label"], "购建固定资产、无形资产和其他长期资产支付的现金")
        self.assertEqual(len(row["binding"]["label_text"]), 2)
        self.assertNotEqual(row["current"]["value_cny"], "64643966892.43")

    def test_independent_line_amount_prevents_cross_row_join(self):
        word = next(word for word in self.pdf.pages[89].words if word.text.startswith("归属于母公司所有者权益"))
        pdf = self.changed(90, lambda words: words + [Word("100.00", (350, word.box[1], 400, word.box[3]))])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_wrong_equity_continuation_not_guessed_as_target_alias(self):
        pdf = self.changed(90, lambda words: [replace(word, text="股本合计") if word.text == "东权益）合计" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_large_line_gap_not_joined(self):
        pdf = self.changed(90, lambda words: [replace(word, box=(word.box[0], word.box[1] + 30, word.box[2], word.box[3] + 30))
                                             if word.text == "东权益）合计" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_clipped_continuation_unknown_even_if_text_matches(self):
        pdf = self.changed(90, lambda words: [replace(word, box=(word.box[0], word.box[1], 620, word.box[3]))
                                             if word.text == "东权益）合计" else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_missing_E_amount_not_back_calculated(self):
        pdf = self.changed(90, lambda words: [word for word in words if word.text != "210,288,410,895.97"])
        result = self.parsed(pdf)
        self.assertIsNone(result["fields"]["attributable_equity_end"]["observed_value_cny"])
        self.assertEqual(result["reconciliations"][0]["state"], "UNKNOWN")

    def test_parent_table_never_fills_missing_consolidated_E(self):
        pdf = self.changed(90, lambda words: [replace(word, text="未知权益")
                                             if word.text.startswith("归属于母公司所有者权益") else word for word in words])
        self.assertIsNone(self.parsed(pdf)["fields"]["attributable_equity_end"]["observed_value_cny"])

    def test_missing_parent_boundary_still_blocks_consolidated_scope(self):
        pdf = self.changed(90, lambda words: [replace(word, text="未知报表") if word.text == "母公司资产负债表" else word for word in words])
        result = self.parsed(pdf)
        self.assertEqual(result["table_states"]["balance"]["state"], "CONSOLIDATED_BOUNDARY_UNKNOWN")
        self.assertIsNone(result["fields"]["minority_interest_end"]["observed_value_cny"])

    def test_negative_capex_keeps_source_amount_but_requires_review(self):
        pdf = self.changed(96, lambda words: [replace(word, text="-100.00") if word.text == "14,420,079,512.74" else word for word in words])
        field = self.parsed(pdf)["fields"]["capex"]
        self.assertEqual(field["observed_value_cny"], "-100.00")
        self.assertEqual(field["state"], "NEGATIVE_PAYMENT_REQUIRES_REVIEW")

    def test_both_period_reconciliations_exact(self):
        self.assertEqual(len(self.bundle["reconciliations"]), 4)
        self.assertEqual({check["state"] for check in self.bundle["reconciliations"]}, {"RECONCILED"})
        self.assertEqual({check["difference_cny"] for check in self.bundle["reconciliations"]}, {"0.00"})

    def test_field_bindings_keep_version_hash_physical_page_and_header(self):
        pages = {"attributable_equity_end": (90, 88), "minority_interest_end": (90, 88),
                 "total_equity_end": (90, 88), "parent_net_profit": (93, 92),
                 "total_net_profit": (93, 92), "operating_cash_flow": (96, 95), "capex": (96, 95)}
        for key, (physical, header) in pages.items():
            bound = self.bundle["fields"][key]["candidates"][0]["binding"]
            self.assertEqual(bound["document_sha256"], self.source["pdf_sha256"])
            self.assertEqual(bound["physical_page"], physical)
            self.assertEqual(bound["table_header"]["physical_page"], header)
            self.assertEqual(bound["source_version"], self.source["version"])
            self.assertFalse(bound["pit_admitted"])

    def test_current_lease_component_does_not_solve_complete_lease_or_audit(self):
        self.assertEqual(self.bundle["lease_financing_component"]["observed_value_cny"], "148332535.64")
        self.assertIsNone(self.bundle["lease_financing_component"]["full_lease_cash_not_already_deducted"])
        self.assertIsNone(self.bundle["audit_text_observation"]["raw_opinion_type"])
        self.assertIsNone(self.bundle["audit_text_observation"]["latest_audit_unmodified_pit"])

    def test_source_success_does_not_open_PIT_or_screening(self):
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertEqual(self.report["pit_admitted_observation_count"], 0)
        self.assertFalse(self.report["screening_input_exported"])
        self.assertEqual(self.bundle["version_identity_state"], "DECLARED_ONLY_NOT_VERIFIED")
        with self.assertRaises(ValueError):
            load_request(canonical_bytes(self.report))

    def test_old_unknown_result_preserved_and_new_code_identity_differs(self):
        self.assertTrue(all(field["observed_value_cny"] is None for field in self.old["bundles"][0]["fields"].values()))
        self.assertNotEqual(self.report["logical_content_hash"], self.old["logical_content_hash"])
        self.assertNotEqual(self.report["manifest"]["code_sha256"], self.old["manifest"]["code_sha256"])
        self.assertEqual(hashlib.sha256((self.frozen / "diagnostic-only.json").read_bytes()).hexdigest(),
                         "6f17f20871899d16af3393ad2477bac8a94eb591ab57d92906f8ca951388f9ad")

    def test_cold_warm_canonical_content_remains_identical(self):
        cache = PDFCache()
        first, second = build_bundle(self.raw_scope, cache=cache), build_bundle(self.raw_scope, cache=cache)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual((cache.parsed_documents, cache.cache_hits), (1, 1))

    def test_replay_requires_full_commit_identity(self):
        with self.assertRaisesRegex(ValueError, "complete immutable"):
            replay_frozen_bundle(self.scope_path, self.frozen, "b5216fd")

    def test_replay_rejects_changed_logical_code_backend_and_whitelist(self):
        for kind in ("logical", "code", "backend", "whitelist"):
            report = deepcopy(self.old)
            if kind == "logical":
                report["logical_content_hash"] = "0" * 64
            else:
                if kind == "code":
                    report["manifest"]["code_sha256"]["scripts/parsing/annual_report_parser.py"] = "0" * 64
                elif kind == "backend":
                    report["manifest"]["pdf_backend"]["version"] = "unknown"
                else:
                    report["manifest"]["code_sha256"]["unknown.py"] = "0" * 64
                report["logical_content_hash"] = content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                (target / "diagnostic-only.json").write_bytes(canonical_bytes(report) + b"\n")
                (target / "diagnostic-only.md").write_bytes((self.frozen / "diagnostic-only.md").read_bytes())
                with self.assertRaises(ValueError):
                    replay_frozen_bundle(self.scope_path, target, "b5216fdbc7d3ecd133d048ae1066b1f9606abd51")

    def test_replay_changed_scope_rejected_without_reinterpreting_old_report(self):
        with tempfile.TemporaryDirectory() as directory:
            scope = json.loads(self.raw_scope)
            scope["as_of"] = "2026-10-01"
            path = Path(directory) / "scope.json"
            path.write_bytes(canonical_bytes(scope))
            with self.assertRaisesRegex(ValueError, "scope identity"):
                replay_frozen_bundle(path, self.frozen, "b5216fdbc7d3ecd133d048ae1066b1f9606abd51")


if __name__ == "__main__":
    unittest.main()
