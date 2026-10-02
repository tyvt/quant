"""Single 2022 annual and a later policy bridge cannot become a PIT window."""

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
from scripts.pilots import capture_financial_2022_000637 as capture
from scripts.pilots import verify_financial_2022_000637 as pilot

ROOT = Path(__file__).resolve().parents[1]


def replace(words, old, new):
    return [(*word[:4], new, *word[5:]) if word[4] == old else word for word in words]


class Financial2022CatalogueTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = base._json((ROOT / "storage/pilots/financial-000637-2022-chain-2026-10-02/capture.json").read_bytes())
        cls.raw = [(ROOT / item["local_path"]).read_bytes() for item in cls.audit["resources"][:3]]

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def test_filtered_counts_bind_one_full_annual_and_separate_supplement(self):
        parsed = [capture.previous.parse_catalogue(raw) for raw in self.raw]
        self.assertEqual([len(rows) for rows in parsed], [3, 23, 0])
        found = capture.merge_catalogues(parsed)
        for _, identifier, day, title in capture.TARGETS:
            self.assertEqual(found[identifier]["announcementTitle"], title)
            self.assertEqual(found[identifier]["adjunctUrl"], f"finalpage/{day}/{identifier}.PDF")
        self.assertTrue(any("摘要" in row["announcementTitle"] for row in parsed[0].values()))
        self.assertTrue(all(row["empty_result_proves_no_withdrawal"] is False for row in self.audit["catalogues"]))

    def test_null_empty_rows_require_explicit_zero_counters(self):
        value = capture.previous.strict_json(self.raw[2])
        value["announcements"] = None
        self.assertEqual(capture.previous.parse_catalogue(self.encode(value)), {})
        for key in ("totalRecordNum", "totalAnnouncement", "totalpages"):
            changed = copy.deepcopy(value)
            changed[key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(changed))

    def test_boolean_counters_pagination_or_truncation_fail(self):
        for key, new in (("totalRecordNum", True), ("totalAnnouncement", True), ("totalpages", False),
                         ("totalpages", 1), ("hasMore", True), ("totalAnnouncement", 31)):
            value = capture.previous.strict_json(self.raw[0])
            value[key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(value))

    def test_duplicate_json_keys_and_nonfinite_fail(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                capture.previous.strict_json(raw)

    def test_security_url_clock_identity_and_duplicate_rows_fail(self):
        for key, new in (("secCode", "002570"), ("orgId", "other"), ("announcementTime", True),
                         ("announcementId", ""), ("adjunctUrl", "https://example.com/file.PDF")):
            value = capture.previous.strict_json(self.raw[0])
            value["announcements"][0][key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(value))
        for duplicate in (True, False):
            value = capture.previous.strict_json(self.raw[0])
            if duplicate:
                value["announcements"][1] = value["announcements"][0]
            else:
                value["announcements"].pop()
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(value))

    def test_cross_query_drift_and_summary_substitution_fail(self):
        rows = capture.merge_catalogues([capture.previous.parse_catalogue(raw) for raw in self.raw])
        changed = copy.deepcopy(rows)
        changed[capture.ANNUAL[1]]["announcementTime"] += 1
        with self.assertRaisesRegex(ValueError, "cross-query"):
            capture.merge_catalogues([rows, changed])
        for key, value in (("announcementTitle", "2022年年度报告摘要"), ("adjunctUrl", "finalpage/2023-04-29/1216687778.PDF")):
            changed = copy.deepcopy(rows)
            changed[capture.ANNUAL[1]][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity drift"):
                capture.merge_catalogues([changed])

    def test_existing_capture_directory_refused_before_network(self):
        with TemporaryDirectory() as folder, patch.object(capture.previous.requests, "request") as network:
            with self.assertRaises(FileExistsError):
                capture.capture(Path(folder))
            network.assert_not_called()

    def test_error_and_redirect_have_no_retry_or_fallback(self):
        for status in (302, 500):
            with self.subTest(status=status), TemporaryDirectory() as folder:
                with patch.object(capture.previous.requests, "request", return_value=Mock(status_code=status)) as network:
                    with self.assertRaises(ValueError):
                        capture.capture(Path(folder) / "new")
                    self.assertEqual(network.call_count, 1)
                    self.assertIs(network.call_args.kwargs["allow_redirects"], False)

    def test_html_not_accepted_as_pdf(self):
        replies = [Mock(status_code=200, content=raw) for raw in self.raw]
        replies.append(Mock(status_code=200, content=b"<html>error</html>"))
        with TemporaryDirectory() as folder, patch.object(capture.previous.requests, "request", side_effect=replies) as network:
            with self.assertRaisesRegex(ValueError, "signature"):
                capture.capture(Path(folder) / "new")
            self.assertEqual(network.call_count, 4)


class Financial2022SourceTests(TestCase):
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
        doc = cls.report["policy_bridge"]["document"]
        with fitz.open(stream=base.verified_bytes(ROOT, doc["path"], doc["sha256"]), filetype="pdf") as pdf:
            cls.policy_words = pdf[86].get_text("words")

    def tables(self, assets=None, cash=None):
        return pilot.extract_tables(self.assets if assets is None else assets, self.cash if cash is None else cash)

    def lease(self, notes=None):
        return pilot.extract_lease_component(self.notes if notes is None else notes, self.tables()["rows"]["financing_other_total"])

    def reject_resealed(self, report):
        report["logical_content_hash"] = base.logical_content_hash(report)
        with self.assertRaises(ValueError):
            pilot.validate_review(report)

    def test_independent_2022_source_not_later_adjusted_comparison(self):
        rows = self.tables()["rows"]
        for name, value in (("E", "879714239.26"), ("N", "151932084.12"), ("OCF", "435473652.17"), ("Capex", "169336831.83")):
            self.assertEqual(rows[name]["current_cny"], value)
        self.assertEqual(len(self.report["source_documents"]), 1)
        self.assertEqual(self.report["source_documents"][0]["page_count"], 241)
        self.assertNotEqual(rows["E"]["current_cny"], self.report["policy_bridge"]["later_2023_opening"]["E"])

    def test_word_order_independence_for_tables_lease_and_policy(self):
        self.assertEqual(self.tables(), pilot.extract_tables(list(reversed(self.assets)), list(reversed(self.cash))))
        self.assertEqual(self.lease(), self.lease(list(reversed(self.notes))))
        self.assertEqual(pilot.extract_policy_table(self.policy_words), pilot.extract_policy_table(list(reversed(self.policy_words))))

    def test_both_columns_equity_and_ocf_reconcile(self):
        for checks in self.tables()["checks"].values():
            for check in checks.values():
                self.assertEqual(check, {"status": "RECONCILED", "difference_cny": "0.00"})
        self.assertEqual(self.tables()["rows"]["E"]["prior_comparative_cny"], "1036150908.16")
        self.assertEqual(self.tables()["rows"]["N"]["prior_comparative_cny"], "129012380.05")

    def test_date_headers_scope_and_year_are_required(self):
        for group, old, new in (("assets", "2022", "2023"), ("assets", "单位：元", "单位：万元"),
                                ("assets", "1、合并资产负债表", "1、母公司资产负债表"),
                                ("cash", "2022", "2023"), ("cash", "年度", "季度"),
                                ("cash", "6、母公司现金流量表", "未知边界")):
            with self.subTest(group=group, old=old), self.assertRaises(ValueError):
                self.tables(**{group: replace(getattr(self, group), old, new)})

    def test_2021_comparatives_not_original_window(self):
        rows = self.tables()["rows"]
        self.assertEqual(rows["OCF"]["prior_comparative_cny"], "61218330.54")
        self.assertEqual(rows["Capex"]["prior_comparative_cny"], "289600814.84")
        self.assertIn("2021_original_window", self.report["remaining_gaps"])
        self.assertTrue(all(item["period_end"] == "2022-12-31" for item in self.report["version_bundles"][0]["observations"].values()))

    def test_missing_or_dash_does_not_become_zero_or_other_column(self):
        for name, group, amount in (("E", "assets", "879,714,239.26"), ("OCF", "cash", "435,473,652.17"), ("Capex", "cash", "169,336,831.83")):
            for mode in ("remove", "dash"):
                original = getattr(self, group)
                words = [word for word in original if word[4] != amount] if mode == "remove" else replace(original, amount, "—")
                with self.subTest(name=name, mode=mode):
                    row = self.tables(**{group: words})["rows"][name]
                    self.assertIsNone(row["current_cny"])
                    self.assertIsNotNone(row["prior_comparative_cny"])
        self.assertEqual(pilot.minority.parse_money_cell("0.00"), "0.00")

    def test_duplicate_row_and_amount_fail(self):
        for label in ("经营活动产生的现金流量净额", "435,473,652.17"):
            word = next(word for word in self.cash if word[4] == label)
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.tables(cash=[*self.cash, word])

    def test_malformed_nonfinite_negative_capex_fail(self):
        for value in ("NaN", "Infinity", "169,336,831.8", "-1.00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.tables(cash=replace(self.cash, "169,336,831.83", value))

    def test_one_cent_equity_and_ocf_drift_fail(self):
        for group, old, new in (("assets", "879,714,239.26", "879,714,239.27"), ("cash", "435,473,652.17", "435,473,652.18")):
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, "reconcile"):
                self.tables(**{group: replace(getattr(self, group), old, new)})

    def test_split_capex_adjacency_and_payment_identity(self):
        words = [(*word[:1], word[1] + 5, word[2], word[3] + 5, *word[4:])
                 if word[4] == "期资产支付的现金" else word for word in self.cash]
        with self.assertRaisesRegex(ValueError, "adjacent"):
            self.tables(cash=words)
        with self.assertRaises(ValueError):
            self.tables(cash=replace(self.cash, "期资产支付的现金", "期资产收回的现金净额"))

    def test_financing_lease_component_matches_both_columns_not_complete_cash(self):
        component = self.lease()
        self.assertEqual(component["current_cny"], "14537724.60")
        self.assertEqual(component["prior_comparative_cny"], "12134633.45")
        self.assertEqual(component["note_total"], self.tables()["rows"]["financing_other_total"])
        self.assertEqual(component["full_lease_cash_coverage"], "UNKNOWN")
        self.assertIsNone(component["full_lease_cash_not_already_deducted"])

    def test_lease_heading_unit_and_each_total_required(self):
        for old, new in (("（5）", "（4）"), ("单位：元", "单位：万元"),
                         ("14,537,724.60", "14,537,724.61"), ("12,134,633.45", "12,134,633.46"),
                         ("14,537,724.60", "-1.00")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.lease(replace(self.notes, old, new))

    def test_missing_lease_component_not_backfilled_from_total(self):
        anchor = next(word for word in self.notes if word[4] == "偿还租赁负债支付的金额")
        words = [word for word in self.notes if not (word[4] == "14,537,724.60"
                 and abs(pilot.geometry.centre(word) - pilot.geometry.centre(anchor)) < 1)]
        component = self.lease(words)
        self.assertIsNone(component["current_cny"])
        self.assertEqual(component["note_total"]["current_cny"], "14537724.60")

    def test_same_version_source_arithmetic_and_decimal_context(self):
        bundle = self.report["version_bundles"][0]
        with localcontext() as context:
            context.prec = 4
            context.rounding = ROUND_DOWN
            self.assertEqual(pilot.source_arithmetic(bundle["observations"]), bundle["ordinary_source_arithmetic"])
        self.assertEqual(bundle["ordinary_source_arithmetic"]["alpha_observed"], "0.8527285168600975700789299700")
        self.assertEqual(bundle["ordinary_source_arithmetic"]["FCF_ordinary_source_arithmetic_cny"], "226942456.0903904479229667450")
        values = copy.deepcopy(bundle["observations"])
        values["Capex"]["observed_value"] = None
        self.assertEqual(pilot.source_arithmetic(values)["status"], "UNKNOWN")

    def test_cross_version_pdf_period_scope_and_field_math_fail(self):
        for name, key, value in (("N", "document_sha256", "f" * 64), ("N", "statement_scope", "PARENT"),
                                 ("E", "period_start", "2023-01-01"), ("OCF", "version", "original_2023_annual_report"),
                                 ("Capex", "field", "investment_outflow_total"), ("Capex", "unit", "CNY_10K")):
            values = copy.deepcopy(self.report["version_bundles"][0]["observations"])
            values[name][key] = value
            with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                pilot.source_arithmetic(values)

    def test_policy_table_binds_december_not_january_or_income_statement(self):
        table = pilot.extract_policy_table(self.policy_words)
        self.assertEqual(table["rows"]["N"], {"before_cny": "151932084.12", "after_cny": "151931979.46", "observed_impact_cny": "-104.66"})
        self.assertEqual(table["rows"]["retained_earnings"]["observed_impact_cny"], "1966829.87")
        self.assertEqual(table["rows"]["deferred_tax_asset"]["observed_impact_cny"], "38460514.69")
        self.assertEqual(table["rows"]["deferred_tax_liability"]["observed_impact_cny"], "36493789.48")
        for old, new in (("年12", "年1"), ("合并资产负债表", "母公司资产负债表"), ("合并利润表", "未知边界"), ("调整前", "调整后")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                pilot.extract_policy_table(replace(self.policy_words, old, new))

    def test_policy_blank_impact_stays_unknown_not_observed_zero(self):
        table = pilot.extract_policy_table(self.policy_words)
        row = table["rows"]["surplus_reserve"]
        self.assertEqual(row["before_cny"], row["after_cny"])
        self.assertIsNone(row["observed_impact_cny"])
        self.assertEqual(table["checks"]["surplus_reserve"], {"difference_cny": None, "status": "UNKNOWN"})
        report = copy.deepcopy(self.report)
        report["policy_bridge"]["tables"]["rows"]["surplus_reserve"]["observed_impact_cny"] = "0.00"
        report["policy_bridge"]["tables"]["checks"] = pilot.policy_checks(report["policy_bridge"]["tables"]["rows"])
        self.reject_resealed(report)

    def test_policy_duplicate_money_malformed_and_one_cent_drift_fail(self):
        word = next(word for word in self.policy_words if word[4] == "1,966,829.87")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            pilot.extract_policy_table([*self.policy_words, word])
        for value in ("NaN", "1,966,829.8", "1,966,829.88"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pilot.extract_policy_table(replace(self.policy_words, "1,966,829.87", value))

    def test_cross_year_bridge_reconciles_without_replacing_original(self):
        policy = self.report["policy_bridge"]
        for field, delta in (("E", "1966829.87"), ("N", "-104.66")):
            row = policy["source_bridge_arithmetic"][field]
            self.assertEqual(row["difference_cny"], delta)
            self.assertEqual(row["check"], {"difference_cny": "0.00", "status": "RECONCILED"})
        self.assertIs(policy["used_to_replace_2022_source"], False)
        wrong = dict(policy["later_2023_opening"], E="881681069.14")
        with self.assertRaises(ValueError):
            pilot.policy_bridge_arithmetic(self.tables()["rows"], wrong, policy["tables"]["rows"])

    def test_missing_policy_impact_does_not_derive_observation(self):
        rows = copy.deepcopy(self.report["policy_bridge"]["tables"]["rows"])
        rows["retained_earnings"]["observed_impact_cny"] = None
        result = pilot.policy_bridge_arithmetic(self.tables()["rows"], self.report["policy_bridge"]["later_2023_opening"], rows)
        self.assertIsNone(result["E"]["policy_observed_component_cny"])
        self.assertEqual(result["E"]["check"]["status"], "UNKNOWN")

    def test_shareholder_supplement_not_numeric_revision_audit_or_shares_proof(self):
        item = self.report["inquiry_supplement"]
        self.assertEqual(item["document"]["announcement_id"], "1217202489")
        self.assertEqual(item["document"]["page_count"], 2)
        for key, value in (("used_as_annual_field_version", True), ("audit_gate_conclusion", "PASS"), ("shares_reader_ready_proof", True)):
            report = copy.deepcopy(self.report)
            report["inquiry_supplement"][key] = value
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_scope_page_bindings_timing_authority_and_bridge_are_frozen(self):
        for key, value in (("period_end", "2023-12-31"), ("timing_policy", "ASSUMED_NEXT_DAY"), ("official_selection", True), ("diagnostic_only", 1)):
            scope = copy.deepcopy(self.scope)
            scope[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.fixed_scope(scope)
        for section, key, value in (("annual", "asset_pages", [132, 133, 134, 135]), ("policy_bridge", "statement_date", "2022-01-01"),
                                    ("inquiry_supplement", "interpretation", "ANNUAL_FIELD_VERSION")):
            scope = copy.deepcopy(self.scope)
            scope[section][key] = value
            with self.subTest(section=section), self.assertRaises(ValueError):
                pilot.fixed_scope(scope)

    def test_resealed_report_cannot_promote_pit_ready_full_lease_or_chain(self):
        for key, value in (("diagnostic_available_at", "2023-04-29"), ("historical_pit_observations_admitted", 1),
                           ("production_reader_ready", True), ("complete_revision_chain_verified", True), ("full_amended_audit_status", "AUDITED")):
            report = copy.deepcopy(self.report)
            report[key] = value
            with self.subTest(key=key):
                self.reject_resealed(report)
        for key in pilot.UNKNOWN_FIELDS:
            report = copy.deepcopy(self.report)
            report["version_bundles"][0]["pit_and_standard_outputs"][key] = "0.00"
            with self.subTest(key=key):
                self.reject_resealed(report)
        report = copy.deepcopy(self.report)
        report["version_bundles"][0]["lease_financing_component"]["full_lease_cash_not_already_deducted"] = "14537724.60"
        self.reject_resealed(report)

    def test_resealed_policy_cannot_replace_source_promote_timing_or_change_evidence(self):
        for key, value in (("used_to_replace_2022_source", True), ("diagnostic_available_at", "2024-04-29"),
                           ("historical_pit_status", "KNOWN"), ("statement_date", "2022-01-01"), ("evidence_refs", [])):
            report = copy.deepcopy(self.report)
            report["policy_bridge"][key] = value
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_resealed_source_math_evidence_and_document_drift_fail(self):
        for mutation in ("value", "math", "field_ref", "lease_ref", "annual_pages", "supplement_url", "policy_page"):
            report = copy.deepcopy(self.report)
            bundle = report["version_bundles"][0]
            if mutation == "value":
                bundle["observations"]["E"]["observed_value"] = "881681069.13"
            elif mutation == "math":
                bundle["ordinary_source_arithmetic"]["alpha_observed"] = "1"
            elif mutation == "field_ref":
                bundle["observations"]["Capex"]["evidence_refs"] = []
            elif mutation == "lease_ref":
                bundle["lease_financing_component"]["evidence_refs"] = []
            elif mutation == "annual_pages":
                report["source_documents"][0]["page_count"] = 258
            elif mutation == "supplement_url":
                report["inquiry_supplement"]["document"]["url"] = "https://example.com/file.PDF"
            else:
                report["policy_bridge"]["document"]["evidence_pages"] = [86]
            with self.subTest(mutation=mutation):
                self.reject_resealed(report)

    def test_one_current_full_annual_cannot_prove_historical_absence(self):
        report = copy.deepcopy(self.report)
        report["catalogue_queries"][2]["empty_result_proves_no_withdrawal"] = True
        self.reject_resealed(report)
        report = copy.deepcopy(self.report)
        report["catalogue_queries"][0]["completeness_scope"] = "ALL_HISTORICAL_VERSIONS"
        self.reject_resealed(report)
        report = copy.deepcopy(self.report)
        report["version_bundles"].append(copy.deepcopy(report["version_bundles"][0]))
        self.reject_resealed(report)

    def test_five_year_and_strategy_outputs_forbidden(self):
        for key in ("ranking", "orders", "F1", "F5", "nav", "target_weights"):
            report = copy.deepcopy(self.report)
            report["unapproved"] = {key: []}
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_all_raw_source_refs_and_code_hashes_bound(self):
        for resource in self.report["manifest"]["raw_resources"]:
            self.assertEqual(len(base.verified_bytes(ROOT, resource["local_path"], resource["sha256"])), resource["bytes"])
        docs = [*self.report["source_documents"], self.report["policy_bridge"]["document"], self.report["inquiry_supplement"]["document"]]
        for doc in docs:
            raw = base.verified_bytes(ROOT, doc["path"], doc["sha256"])
            self.assertTrue(raw.startswith(b"%PDF-"))
        for path, digest in self.report["manifest"]["code_hashes"].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)

    def test_previous_2023_review_and_original_lease_gap_immutable(self):
        reference = self.report["manifest"]["previous_2023_review"]
        old = base._json(base.verified_bytes(ROOT, reference["path"], reference["sha256"]))
        self.assertEqual(reference["sha256"], "6a7ab3c936636796b4ccb49bcb7ad09cbb9ebf6565352b1e402ea2e4cf5211a3")
        self.assertEqual(old["logical_content_hash"], reference["logical_content_hash"])
        self.assertIsNone(old["version_bundles"][0]["lease_financing_component"]["current_cny"])
        self.assertEqual(self.report["historical_pit_observations_admitted"], 0)

    def test_offline_rebuild_canonical_roundtrip_and_hash_stability(self):
        with patch.object(capture.previous.requests, "request", side_effect=AssertionError("unexpected network")):
            report = pilot.build_review(ROOT)
        self.assertEqual(base.canonical_bytes(report), base.canonical_bytes(self.report))
        self.assertEqual(pilot.render_markdown(base._json(base.canonical_bytes(report))), pilot.render_markdown(report))

    def test_isolated_processes_match_and_refuse_overwrite(self):
        with TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("first", "second")]
            for path in paths:
                result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / pilot.TOOL), "--output-dir", str(path)],
                                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("diagnostic-only.json", "diagnostic-only.md"):
                self.assertEqual((paths[0] / name).read_bytes(), (paths[1] / name).read_bytes())
            result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / pilot.TOOL), "--output-dir", str(paths[0])],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite", result.stderr)

    def test_cli_frozen_check_does_not_fetch_or_write(self):
        result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / pilot.TOOL), "--check"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.report["logical_content_hash"], result.stdout)

    def test_hash_mismatch_and_path_escape_fail(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                base.verified_bytes(Path(folder), "../outside.pdf", "0" * 64)
        doc = self.report["source_documents"][0]
        with self.assertRaises(ValueError):
            base.verified_bytes(ROOT, doc["path"], "0" * 64)
