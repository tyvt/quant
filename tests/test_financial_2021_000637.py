"""2021 independent source values do not open a five-year PIT FCF window."""

from __future__ import annotations

import copy
from decimal import ROUND_DOWN, localcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import fitz

from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import capture_financial_2021_000637 as capture
from scripts.pilots import verify_financial_2021_000637 as pilot

ROOT = Path(__file__).resolve().parents[1]


def replace(words, old, new):
    return [(*word[:4], new, *word[5:]) if word[4] == old else word for word in words]


class Financial2021CatalogueTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = base._json((ROOT / "storage/pilots/financial-000637-2021-chain-2026-10-02/capture.json").read_bytes())
        cls.raw = [(ROOT / item["local_path"]).read_bytes() for item in cls.audit["resources"][:3]]

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def test_filtered_counts_do_not_claim_historical_completeness(self):
        rows = [capture.previous.parse_catalogue(raw) for raw in self.raw]
        self.assertEqual([len(row) for row in rows], [2, 24, 0])
        found = capture.merge_catalogues(rows)
        for _, identifier, day, title in capture.TARGETS:
            self.assertEqual(found[identifier]["announcementTitle"], title)
            self.assertEqual(found[identifier]["adjunctUrl"], f"finalpage/{day}/{identifier}.PDF")
        self.assertFalse(self.audit["complete_revision_chain_verified"])
        self.assertTrue(all(item["empty_result_proves_no_withdrawal"] is False for item in self.audit["catalogues"]))

    def test_empty_rows_require_explicit_zero_counters(self):
        value = capture.previous.strict_json(self.raw[2])
        value["announcements"] = None
        self.assertEqual(capture.previous.parse_catalogue(self.encode(value)), {})
        for key in ("totalAnnouncement", "totalRecordNum", "totalpages"):
            new = copy.deepcopy(value)
            new[key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(new))

    def test_boolean_counters_pagination_and_truncation_fail(self):
        for key, new in (("totalAnnouncement", True), ("totalRecordNum", True), ("totalpages", False),
                         ("totalpages", 1), ("hasMore", True), ("totalAnnouncement", 31)):
            value = capture.previous.strict_json(self.raw[0])
            value[key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(value))

    def test_duplicate_json_keys_nonfinite_and_duplicate_rows_fail(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(raw)
        value = capture.previous.strict_json(self.raw[0])
        value["announcements"][1] = value["announcements"][0]
        with self.assertRaises(ValueError):
            capture.previous.parse_catalogue(self.encode(value))

    def test_security_clock_url_drift_and_missing_rows_fail(self):
        for key, new in (("secCode", "002570"), ("orgId", "other"), ("announcementTime", True),
                         ("announcementId", ""), ("adjunctUrl", "https://example.com/file.PDF")):
            value = capture.previous.strict_json(self.raw[0])
            value["announcements"][0][key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(value))
        value = capture.previous.strict_json(self.raw[0])
        value["announcements"].pop()
        with self.assertRaises(ValueError):
            capture.previous.parse_catalogue(self.encode(value))

    def test_summary_substitution_and_cross_query_drift_fail(self):
        rows = capture.merge_catalogues([capture.previous.parse_catalogue(raw) for raw in self.raw])
        changed = copy.deepcopy(rows)
        changed[capture.ANNUAL[1]]["announcementTime"] += 1
        with self.assertRaisesRegex(ValueError, "cross-query"):
            capture.merge_catalogues([rows, changed])
        for key, new in (("announcementTitle", "2021年年度报告摘要"), ("adjunctUrl", "finalpage/2022-03-31/1212743934.PDF")):
            changed = copy.deepcopy(rows)
            changed[capture.ANNUAL[1]][key] = new
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity drift"):
                capture.merge_catalogues([changed])

    def test_existing_capture_refused_before_network(self):
        with TemporaryDirectory() as folder, patch.object(capture.previous.requests, "request") as network:
            with self.assertRaises(FileExistsError):
                capture.capture(Path(folder))
            network.assert_not_called()

    def test_errors_and_redirects_have_no_retry_or_fallback(self):
        for status in (302, 500):
            with self.subTest(status=status), TemporaryDirectory() as folder:
                with patch.object(capture.previous.requests, "request", return_value=Mock(status_code=status)) as network:
                    with self.assertRaises(ValueError):
                        capture.capture(Path(folder) / "new")
                    self.assertEqual(network.call_count, 1)
                    self.assertIs(network.call_args.kwargs["allow_redirects"], False)

    def test_html_cannot_become_legal_pdf(self):
        replies = [Mock(status_code=200, content=raw) for raw in self.raw]
        replies.append(Mock(status_code=200, content=b"<html>error</html>"))
        with TemporaryDirectory() as folder, patch.object(capture.previous.requests, "request", side_effect=replies) as network:
            with self.assertRaisesRegex(ValueError, "signature"):
                capture.capture(Path(folder) / "new")
            self.assertEqual(network.call_count, 4)


class Financial2021SourceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = pilot.build_review(ROOT)
        cls.scope = base._json((ROOT / pilot.INPUTS).read_bytes())
        plan = cls.scope["annual"]
        doc = cls.report["source_documents"][0]
        with fitz.open(stream=base.verified_bytes(ROOT, doc["path"], doc["sha256"]), filetype="pdf") as pdf:
            def combined(pages):
                return [(*word[:1], word[1] + i * 1000, word[2], word[3] + i * 1000, *word[4:])
                        for i, page in enumerate(pages) for word in pdf[page - 1].get_text("words")]
            cls.assets, cls.cash, cls.notes = [combined(plan[key]) for key in ("asset_pages", "cashflow_pages", "lease_note_pages")]

    def tables(self, assets=None, cash=None):
        return pilot.extract_tables(self.assets if assets is None else assets, self.cash if cash is None else cash)

    def lease(self, notes=None):
        return pilot.extract_lease_component(self.notes if notes is None else notes, self.tables()["rows"]["financing_other_total"])

    def reject_resealed(self, value):
        value["logical_content_hash"] = base.logical_content_hash(value)
        with self.assertRaises(ValueError):
            pilot.validate_review(value)

    def test_independent_source_values_and_ordinary_arithmetic(self):
        b = self.report["version_bundles"][0]
        for name in ("E", "N", "OCF", "Capex"):
            self.assertEqual(b["observations"][name]["observed_value"], pilot.EXPECTED[name])
        self.assertEqual(b["ordinary_source_arithmetic"], {
            "alpha_observed": "0.8892752789626617479024459557", "ocf_minus_capex_cny": "-228382484.30",
            "FCF_ordinary_source_arithmetic_cny": "-203094897.4360682169265409214", "status": "SOURCE_ARITHMETIC_ONLY_NOT_PIT"})
        self.assertEqual(self.report["source_documents"][0]["sha256"], pilot.ANNUAL_HASH)

    def test_current_and_comparative_subtotals_reconcile(self):
        for column in ("current_cny", "prior_comparative_cny"):
            for check in self.tables()["checks"][column].values():
                self.assertEqual(check, {"difference_cny": "0.00", "status": "RECONCILED"})

    def test_word_order_does_not_change_row_selection(self):
        self.assertEqual(self.tables(list(reversed(self.assets)), list(reversed(self.cash))), self.tables())
        self.assertEqual(self.lease(list(reversed(self.notes))), self.lease())

    def test_annual_year_date_unit_and_consolidated_scope_fail_closed(self):
        for old, new, target in (("2021", "2022", "assets"), ("2020", "2021", "assets"),
                                 ("2021", "2022", "cash"), ("单位：元", "单位：万元", "assets"),
                                 ("单位：元", "单位：万元", "cash"), ("1、合并资产负债表", "1、母公司资产负债表", "assets"),
                                 ("6、母公司现金流量表", "6、其他现金流量表", "cash")):
            with self.subTest(old=old, target=target), self.assertRaises(ValueError):
                self.tables(**{target: replace(getattr(self, target), old, new)})

    def test_missing_cell_and_dash_stay_unknown_not_zero(self):
        for new in (None, "—"):
            words = [w for w in self.assets if w[4] != "129,012,380.05"] if new is None else replace(self.assets, "129,012,380.05", new)
            tables = self.tables(assets=words)
            self.assertIsNone(tables["rows"]["N"]["current_cny"])
            self.assertEqual(tables["checks"]["current_cny"]["equity"]["status"], "UNKNOWN")

    def test_duplicate_money_labels_and_nonfinite_fail(self):
        for label in ("1,036,150,908.16", pilot.equity.E_LABEL):
            duplicate = [w for w in self.assets if w[4] == label][0]
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.tables(assets=self.assets + [duplicate])
        for new in ("1,036,150,908.1", "NaN", "1,036,150,908.160"):
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.tables(assets=replace(self.assets, "1,036,150,908.16", new))

    def test_one_cent_subtotal_changes_fail(self):
        for target, old, new in (("assets", "1,036,150,908.16", "1,036,150,908.17"),
                                 ("cash", "61,218,330.54", "61,218,330.55"),
                                 ("cash", "69,341,087.47", "69,341,087.48")):
            with self.subTest(target=target, old=old), self.assertRaises(ValueError):
                self.tables(**{target: replace(getattr(self, target), old, new)})

    def test_current_not_comparative_and_mother_rows_not_mixed(self):
        r = self.tables()["rows"]
        self.assertEqual(r["E"]["prior_comparative_cny"], "908906417.88")
        self.assertEqual(r["OCF"]["prior_comparative_cny"], "69341087.47")
        self.assertEqual(r["Capex"]["prior_comparative_cny"], "570274332.74")
        self.assertNotEqual(r["OCF"]["current_cny"], "143140321.35")
        self.assertNotEqual(r["Capex"]["current_cny"], "44247.79")

    def test_split_capex_label_geometry_and_payment_nature(self):
        for old, new in (("他长期资产支付的现金", "他长期资产收回的现金"),
                         ("购建固定资产、无形资产和其", "投资活动现金流出小计")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.tables(cash=replace(self.cash, old, new))
        shifted = [(*w[:1], w[1] + 5, w[2], w[3] + 5, *w[4:]) if w[4] == "他长期资产支付的现金" else w for w in self.cash]
        with self.assertRaisesRegex(ValueError, "adjacent"):
            self.tables(cash=shifted)
        self.assertNotEqual(self.tables()["rows"]["Capex"]["current_cny"], "6651094760.34")

    def test_negative_capex_or_lease_payments_fail(self):
        with self.assertRaises(ValueError):
            self.tables(cash=replace(self.cash, "289,600,814.84", "-289,600,814.84"))
        with self.assertRaises(ValueError):
            self.lease(replace(self.notes, "12,134,633.45", "-12,134,633.45"))

    def test_financing_split_label_requires_its_own_adjacent_continuation(self):
        first = pilot.minority._one(self.cash, "支付其他与筹资活动有关的现")
        shifted = [(*w[:1], w[1] + 6, w[2], w[3] + 6, *w[4:]) if w[4] == "金"
                   and 0 < w[1] - first[3] < 10 else w for w in self.cash]
        with self.assertRaisesRegex(ValueError, "adjacent"):
            self.tables(cash=shifted)

    def test_lease_blank_comparison_is_unknown_not_reconciled_zero(self):
        c = self.lease()
        self.assertEqual(c["current_cny"], "12134633.45")
        self.assertIsNone(c["prior_comparative_cny"])
        self.assertIsNone(c["note_total"]["prior_comparative_cny"])
        self.assertEqual(c["checks"]["prior_comparative_cny"], {"difference_cny": None, "status": "UNKNOWN"})
        self.assertEqual(c["prior_comparative_state"], "BLANK_NOT_ZERO")
        self.assertIsNone(c["full_lease_cash_not_already_deducted"])

    def test_lease_note_subsection_unit_and_one_cent_difference_fail(self):
        for old, new in (("（6）支付的其他与筹资活动有关的现金", "（6）支付的其他与投资活动有关的现金"),
                         ("上期发生额", "期初余额"), ("偿还租赁负债支付的金额", "租赁负债余额")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.lease(replace(self.notes, old, new))
        # Only the financing note's first unit, not the subsequent supplement.
        heading = pilot.minority._one(self.notes, "（6）支付的其他与筹资活动有关的现金")
        altered = [(*w[:4], "单位：万元", *w[5:]) if w[4] == "单位：元" and 0 < w[1] - heading[3] < 30 else w for w in self.notes]
        with self.assertRaises(ValueError):
            self.lease(altered)
        changed = False
        words = []
        for w in self.notes:
            if w[4] == "12,134,633.45" and not changed:
                w = (*w[:4], "12,134,633.46", *w[5:]); changed = True
            words.append(w)
        with self.assertRaises(ValueError):
            self.lease(words)

    def test_missing_lease_component_is_not_filled_from_total(self):
        anchor = pilot.minority._one(self.notes, "偿还租赁负债支付的金额")
        words = [w for w in self.notes if not (w[4] == "12,134,633.45"
                 and abs(pilot.geometry.centre(w) - pilot.geometry.centre(anchor)) < 1)]
        component = self.lease(words)
        self.assertIsNone(component["current_cny"])
        self.assertEqual(component["note_total"]["current_cny"], "12134633.45")
        self.assertEqual(component["checks"]["current_cny"]["status"], "UNKNOWN")

    def test_arithmetic_uses_fixed_decimal_context_and_same_pdf(self):
        observations = self.report["version_bundles"][0]["observations"]
        expected = pilot.source_arithmetic(observations)
        with localcontext() as context:
            context.prec = 6; context.rounding = ROUND_DOWN
            self.assertEqual(pilot.source_arithmetic(observations), expected)
        for key in ("security_id", "period_end", "statement_scope", "unit", "version", "document_sha256", "period_start", "field"):
            new = copy.deepcopy(observations)
            new["OCF"][key] = "different"
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.source_arithmetic(new)

    def test_missing_arithmetic_input_remains_unknown(self):
        for name in ("E", "N", "OCF", "Capex"):
            observations = copy.deepcopy(self.report["version_bundles"][0]["observations"])
            observations[name]["observed_value"] = None
            with self.subTest(name=name):
                self.assertIsNone(pilot.source_arithmetic(observations)["FCF_ordinary_source_arithmetic_cny"])

    def test_corroboration_is_equal_but_never_replaces_original(self):
        comparison = self.report["comparative_corroboration"]
        self.assertFalse(comparison["used_to_replace_2021_source"])
        self.assertNotEqual(comparison["document"]["sha256"], self.report["source_documents"][0]["sha256"])
        for row in comparison["rows"].values():
            self.assertEqual(row["independent_2021_source_cny"], row["2022_original_comparative_cny"])
            self.assertEqual(row["check"]["status"], "RECONCILED")

    def test_event_address_correction_not_financial_version_or_audit(self):
        notice = self.report["event_correction"]
        self.assertEqual(notice["interpretation"], pilot.NOTICE_INTERPRETATION)
        self.assertFalse(notice["used_as_annual_field_version"])
        self.assertEqual(notice["audit_gate_conclusion"], "UNKNOWN")
        for key, new in (("used_as_annual_field_version", True), ("audit_gate_conclusion", "PASS"), ("interpretation", "ANNUAL_CORRECTION")):
            report = copy.deepcopy(self.report); report["event_correction"][key] = new
            self.reject_resealed(report)

    def test_fixed_scope_rejects_identity_year_pages_expectations_or_assumptions(self):
        for key, new in (("as_of", "2026-10-01"), ("period_end", "2020-12-31"), ("unit", "CNY_THOUSAND"),
                         ("timing_policy", "NEXT_TRADING_DAY"), ("diagnostic_only", 1)):
            scope = copy.deepcopy(self.scope); scope[key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.fixed_scope(scope)
        for key, new in (("asset_pages", [154, 155, 156]), ("pdf_sha256", "0" * 64), ("expected", {})):
            scope = copy.deepcopy(self.scope); scope["annual"][key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.fixed_scope(scope)

    def test_window_completion_does_not_admit_pit_or_standard_fcf(self):
        self.assertEqual(self.report["original_source_window"]["independently_bound_original_years"], [2021, 2022, 2023, 2024, 2025])
        self.assertFalse(self.report["original_source_window"]["historical_pit_complete"])
        self.assertFalse(self.report["original_source_window"]["five_year_standard_fcf_complete"])
        self.assertEqual(self.report["historical_pit_observations_admitted"], 0)
        self.assertIsNone(self.report["diagnostic_available_at"])
        self.assertTrue(all(v is None for v in self.report["version_bundles"][0]["pit_and_standard_outputs"].values()))

    def test_resealed_timing_and_authority_promotions_fail(self):
        for key, new in (("diagnostic_available_at", "2022-03-31"), ("official_selection", True), ("production_reader_ready", True),
                         ("historical_pit_observations_admitted", True), ("complete_revision_chain_verified", True), ("full_amended_audit_status", "PASS")):
            report = copy.deepcopy(self.report); report[key] = new
            with self.subTest(key=key): self.reject_resealed(report)
        for key in ("historical_pit_complete", "five_year_standard_fcf_complete"):
            report = copy.deepcopy(self.report); report["original_source_window"][key] = True
            self.reject_resealed(report)

    def test_resealed_blank_fill_partial_promotion_and_strategy_outputs_fail(self):
        for key, new in (("prior_comparative_cny", "0.00"), ("full_lease_cash_not_already_deducted", "12134633.45"),
                         ("full_lease_cash_coverage", "COMPLETE"), ("Lease_cash", "12134633.45")):
            report = copy.deepcopy(self.report); report["version_bundles"][0]["lease_financing_component"][key] = new
            with self.subTest(key=key): self.reject_resealed(report)
        for key in ("ranking", "top_n", "orders", "holdings", "nav", "F1", "F5"):
            report = copy.deepcopy(self.report); report["added"] = {key: []}
            with self.subTest(key=key): self.reject_resealed(report)

    def test_resealed_source_page_value_and_corroboration_drift_fail(self):
        for kind in ("pages", "value", "comparison", "replacement", "prior", "version", "field"):
            report = copy.deepcopy(self.report)
            if kind == "pages": report["source_documents"][0]["evidence_pages"] = [156]
            if kind == "value": report["version_bundles"][0]["observations"]["E"]["observed_value"] = "1.00"
            if kind == "comparison": report["comparative_corroboration"]["rows"]["OCF"]["2022_original_comparative_cny"] = "1.00"
            if kind == "replacement": report["comparative_corroboration"]["used_to_replace_2021_source"] = True
            if kind == "prior": report["version_bundles"][0]["tables"]["rows"]["financing_other_total"]["prior_comparative_cny"] = "0.00"
            if kind == "version": report["version_bundles"][0]["observations"]["N"]["document_sha256"] = "0" * 64
            if kind == "field": report["version_bundles"][0]["observations"]["E"]["evidence_refs"] = []
            with self.subTest(kind=kind): self.reject_resealed(report)

    def test_filtered_empty_result_cannot_be_promoted_to_no_withdrawal(self):
        for key, new in (("empty_result_proves_no_withdrawal", True), ("completeness_scope", "ALL_HISTORY"), ("reported_total", True)):
            report = copy.deepcopy(self.report); report["catalogue_queries"][2][key] = new
            with self.subTest(key=key): self.reject_resealed(report)

    def test_all_bound_resource_and_code_hashes_and_previous_file_stay_fixed(self):
        for resource in self.report["manifest"]["raw_resources"]:
            raw = base.verified_bytes(ROOT, resource["local_path"], resource["sha256"])
            self.assertEqual(len(raw), resource["bytes"])
        for path, sha in self.report["manifest"]["code_hashes"].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), sha)
        old = self.report["manifest"]["previous_2022_review"]
        self.assertEqual(hashlib.sha256((ROOT / old["path"]).read_bytes()).hexdigest(), "64edebf28344c736c2b72a807ad736d5138cbde67f610cf2e3494ace8db71eb2")
        self.assertEqual(old["logical_content_hash"], "6243613599088a3dfadf925f2cf3288faf7323033a1b099c3bb3e7aa254848d8")

    def test_offline_build_canonical_and_markdown_order_are_stable(self):
        with patch.object(capture.previous.requests, "request", side_effect=AssertionError("network forbidden")):
            again = pilot.build_review(ROOT)
        self.assertEqual(base.canonical_bytes(again), base.canonical_bytes(self.report))
        reread = base._json(base.canonical_bytes(self.report))
        self.assertEqual(pilot.render_markdown(reread), pilot.render_markdown(self.report))

    def test_cli_two_runs_equal_and_overwrite_is_refused(self):
        with TemporaryDirectory() as folder:
            outputs = [Path(folder) / name for name in ("a", "b")]
            for output in outputs:
                result = subprocess.run([sys.executable, "-X", "utf8", pilot.TOOL, "--output-dir", str(output)], cwd=ROOT, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            for name in ("diagnostic-only.json", "diagnostic-only.md"):
                self.assertEqual((outputs[0] / name).read_bytes(), (outputs[1] / name).read_bytes())
            result = subprocess.run([sys.executable, "-X", "utf8", pilot.TOOL, "--output-dir", str(outputs[0])], cwd=ROOT, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"refusing to overwrite", result.stderr)

    def test_cli_frozen_check_and_path_hash_guard(self):
        result = subprocess.run([sys.executable, "-X", "utf8", pilot.TOOL, "--check"], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        raw = (ROOT / pilot.INPUTS).read_bytes()
        with self.assertRaises(ValueError): base.verified_bytes(ROOT, pilot.INPUTS, "0" * 64)
        with self.assertRaises(ValueError): base.verified_bytes(ROOT, "../outside.json", hashlib.sha256(raw).hexdigest())
