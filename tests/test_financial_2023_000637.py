"""2023 source extension preserves version, missing-detail and PIT boundaries."""

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
from scripts.pilots import capture_financial_2023_000637 as capture
from scripts.pilots import verify_financial_2023_000637 as pilot

ROOT = Path(__file__).resolve().parents[1]


def replace(words, old, new):
    return [(*word[:4], new, *word[5:]) if word[4] == old else word for word in words]


class Financial2023CatalogueTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = base._json((ROOT / "storage/pilots/financial-000637-2023-chain-2026-10-02/capture.json").read_bytes())
        cls.raw = [(ROOT / item["local_path"]).read_bytes() for item in cls.audit["resources"][:3]]

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def test_filtered_counts_bind_two_full_annuals_and_separate_notice(self):
        parsed = [capture.previous.parse_catalogue(raw) for raw in self.raw]
        self.assertEqual([len(rows) for rows in parsed], [6, 23, 0])
        rows = capture.merge_catalogues(parsed)
        for _, identifier, day, title in (*capture.TARGETS, capture.NOTICE):
            self.assertEqual(rows[identifier]["announcementTitle"], title)
            self.assertEqual(rows[identifier]["adjunctUrl"], f"finalpage/{day}/{identifier}.PDF")
        self.assertTrue(any("摘要" in row["announcementTitle"] for row in parsed[0].values()))
        self.assertTrue(all(x["empty_result_proves_no_withdrawal"] is False for x in self.audit["catalogues"]))

    def test_null_empty_rows_require_explicit_zero_counters(self):
        value = capture.previous.strict_json(self.raw[2])
        value["announcements"] = None
        self.assertEqual(capture.previous.parse_catalogue(self.encode(value)), {})
        for key in ("totalRecordNum", "totalAnnouncement", "totalpages"):
            changed = copy.deepcopy(value)
            changed[key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(changed))

    def test_bool_counters_pagination_and_truncation_fail(self):
        for key, new in (("totalRecordNum", True), ("totalAnnouncement", True), ("totalpages", False),
                         ("totalpages", 1), ("hasMore", True), ("totalAnnouncement", 31)):
            value = capture.previous.strict_json(self.raw[0])
            value[key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(value))

    def test_duplicate_keys_and_nonfinite_numbers_fail(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                capture.previous.strict_json(raw)

    def test_security_org_clock_and_url_drift_fail(self):
        for key, new in (("secCode", "002570"), ("orgId", "other"), ("announcementId", ""),
                         ("announcementTitle", ""), ("announcementTime", True),
                         ("adjunctUrl", "https://example.com/file.PDF")):
            value = capture.previous.strict_json(self.raw[0])
            value["announcements"][0][key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.previous.parse_catalogue(self.encode(value))

    def test_duplicate_ids_and_row_count_mismatch_fail(self):
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
        changed[capture.TARGETS[0][1]]["announcementTime"] += 1
        with self.assertRaisesRegex(ValueError, "cross-query"):
            capture.merge_catalogues([rows, changed])
        for identifier, key, new in (("1221364107", "announcementTitle", "2023年年度报告摘要"),
                                     ("1222163844", "adjunctUrl", "finalpage/2026-08-06/1225460244.PDF")):
            changed = copy.deepcopy(rows)
            changed[identifier][key] = new
            with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, "identity drift"):
                capture.merge_catalogues([changed])

    def test_capture_refuses_existing_directory_before_network(self):
        with TemporaryDirectory() as folder, patch.object(capture.previous.requests, "request") as network:
            with self.assertRaises(FileExistsError):
                capture.capture(Path(folder))
            network.assert_not_called()

    def test_redirect_or_error_has_no_retry_or_fallback(self):
        for status in (302, 500):
            with self.subTest(status=status), TemporaryDirectory() as folder:
                with patch.object(capture.previous.requests, "request", return_value=Mock(status_code=status)) as network:
                    with self.assertRaises(ValueError):
                        capture.capture(Path(folder) / "new")
                    self.assertEqual(network.call_count, 1)
                    self.assertIs(network.call_args.kwargs["allow_redirects"], False)

    def test_html_is_not_accepted_as_pdf(self):
        replies = [Mock(status_code=200, content=raw) for raw in self.raw]
        replies.append(Mock(status_code=200, content=b"<html>error</html>"))
        with TemporaryDirectory() as folder, patch.object(capture.previous.requests, "request", side_effect=replies) as network:
            with self.assertRaisesRegex(ValueError, "signature"):
                capture.capture(Path(folder) / "new")
            self.assertEqual(network.call_count, 4)


class Financial2023SourceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = pilot.build_review(ROOT)
        cls.scope = base._json((ROOT / pilot.INPUTS).read_bytes())
        cls.words = []
        for doc, plan in zip(cls.report["source_documents"], cls.scope["documents"]):
            with fitz.open(stream=base.verified_bytes(ROOT, doc["path"], doc["sha256"]), filetype="pdf") as pdf:
                def combined(pages):
                    return [(*word[:1], word[1] + i * 1000, word[2], word[3] + i * 1000, *word[4:])
                            for i, page in enumerate(pages) for word in pdf[page - 1].get_text("words")]
                cls.words.append((combined(plan["asset_pages"]), combined(plan["cashflow_pages"]),
                                  combined(plan["lease_note_pages"])))

    def tables(self, index=0, assets=None, cash=None):
        words = self.words[index]
        return pilot.extract_tables(words[0] if assets is None else assets, words[1] if cash is None else cash)

    def lease(self, index, notes=None):
        return pilot.extract_lease_component(self.words[index][2] if notes is None else notes,
                                             self.tables(index)["rows"]["financing_other_total"],
                                             self.scope["documents"][index]["lease_note_mode"])

    def reject_resealed(self, report):
        report["logical_content_hash"] = base.logical_content_hash(report)
        with self.assertRaises(ValueError):
            pilot.validate_review(report)

    def test_real_2023_two_versions_not_2024_comparatives(self):
        for index, ocf in enumerate(("353022150.03", "246804136.31")):
            rows = self.tables(index)["rows"]
            self.assertEqual(rows["E"]["current_cny"], "728305124.36")
            self.assertEqual(rows["N"]["current_cny"], "145608980.40")
            self.assertEqual(rows["OCF"]["current_cny"], ocf)
            self.assertEqual(rows["Capex"]["current_cny"], "127491365.46")
        self.assertEqual([doc["page_count"] for doc in self.report["source_documents"]], [258, 283])

    def test_word_order_does_not_change_geometry_or_lease_results(self):
        for index, (assets, cash, notes) in enumerate(self.words):
            self.assertEqual(self.tables(index), pilot.extract_tables(list(reversed(assets)), list(reversed(cash))))
            self.assertEqual(self.lease(index), self.lease(index, list(reversed(notes))))

    def test_both_columns_equity_and_ocf_reconcile(self):
        for bundle in self.report["version_bundles"]:
            for checks in bundle["tables"]["checks"].values():
                for check in checks.values():
                    self.assertEqual(check, {"status": "RECONCILED", "difference_cny": "0.00"})
            self.assertEqual(bundle["tables"]["rows"]["E"]["prior_comparative_cny"], "881681069.13")
            self.assertEqual(bundle["tables"]["rows"]["N"]["prior_comparative_cny"], "151931979.46")

    def test_dated_opening_headers_are_not_generic_period_labels(self):
        for old, new in (("2023", "2024"), ("项目", "期末余额"), ("单位：元", "单位：万元")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.tables(assets=replace(self.words[0][0], old, new))
        assets = pilot.previous.section(self.words[0][0], "1、合并资产负债表", "2、母公司资产负债表")
        header = pilot.dated_asset_headers(assets)[0]
        part = next(word for word in assets if word[4] == "2023" and abs(word[1] - header[1]) < 1)
        with self.assertRaises(ValueError):
            pilot.dated_asset_headers([*assets, part])

    def test_2022_comparatives_do_not_close_original_window(self):
        for index in (0, 1):
            self.assertEqual(self.tables(index)["rows"]["OCF"]["prior_comparative_cny"], "435473652.17")
            self.assertEqual(self.tables(index)["rows"]["Capex"]["prior_comparative_cny"], "169336831.83")
        self.assertTrue(all(item["period_end"] == "2023-12-31"
                            for bundle in self.report["version_bundles"] for item in bundle["observations"].values()))
        self.assertIn("2021_2022_original_window", self.report["remaining_gaps"])

    def test_missing_or_dash_is_not_zero_or_other_column(self):
        for name, group, amount in (("E", 0, "728,305,124.36"), ("OCF", 1, "353,022,150.03"),
                                    ("Capex", 1, "127,491,365.46")):
            for mode in ("remove", "dash"):
                words = list(self.words[0][:2])
                words[group] = ([word for word in words[group] if word[4] != amount] if mode == "remove"
                                else replace(words[group], amount, "—"))
                with self.subTest(name=name, mode=mode):
                    result = pilot.extract_tables(*words)["rows"][name]
                    self.assertIsNone(result["current_cny"])
                    self.assertIsNotNone(result["prior_comparative_cny"])
        self.assertEqual(pilot.minority.parse_money_cell("0.00"), "0.00")

    def test_duplicate_row_or_currency_cell_fails(self):
        for label in ("经营活动产生的现金流量净额", "353,022,150.03"):
            words = self.words[0][1]
            extra = next(word for word in words if word[4] == label)
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.tables(cash=[*words, extra])

    def test_nonfinite_malformed_and_negative_capex_fail(self):
        for amount in ("NaN", "Infinity", "127,491,365.4", "-1.00"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.tables(cash=replace(self.words[0][1], "127,491,365.46", amount))

    def test_one_cent_reconciliation_drift_fails(self):
        for group, old, new in ((0, "728,305,124.36", "728,305,124.37"),
                                (1, "353,022,150.03", "353,022,150.04")):
            words = list(self.words[0][:2])
            words[group] = replace(words[group], old, new)
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, "reconcile"):
                pilot.extract_tables(*words)

    def test_cashflow_scope_unit_and_annual_header_fail_closed(self):
        for old, new in (("单位：元", "单位：万元"), ("2023", "2025"), ("年度", "季度"),
                         ("5、合并现金流量表", "5、母公司现金流量表"), ("6、母公司现金流量表", "未知边界")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.tables(cash=replace(self.words[0][1], old, new))

    def test_split_capex_adjacency_and_payment_identity_required(self):
        words = [(*word[:1], word[1] + 5, word[2], word[3] + 5, *word[4:])
                 if word[4] == "期资产支付的现金" else word for word in self.words[0][1]]
        with self.assertRaisesRegex(ValueError, "adjacent"):
            self.tables(cash=words)
        with self.assertRaises(ValueError):
            self.tables(cash=replace(self.words[0][1], "期资产支付的现金", "期资产收回的现金净额"))

    def test_original_main_total_does_not_allocate_missing_lease_detail(self):
        self.assertEqual(self.tables()["rows"]["financing_other_total"]["current_cny"], "10104914.34")
        self.assertIsNone(self.lease(0)["current_cny"])
        self.assertIsNone(self.lease(0)["prior_comparative_cny"])
        self.assertEqual(self.lease(0)["observation_state"], "NOT_IDENTIFIED_IN_FIXED_NOTE_SECTION")
        self.assertEqual(self.lease(1)["current_cny"], "10104914.34")
        self.assertEqual(self.lease(1)["prior_comparative_cny"], "14537724.60")

    def test_original_note_unexpected_financing_shape_requires_review(self):
        for old, new in (("（2）与投资活动有关的现金", "（2）与筹资活动有关的现金"),
                         ("61、现金流量表项目", "61、未核实章节")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.lease(0, replace(self.words[0][2], old, new))

    def test_amended_lease_heading_unit_and_both_totals_are_required(self):
        for old, new in (("（3）与筹资活动有关的现金", "（3）与投资活动有关的现金"),
                         ("单位：元", "单位：万元"), ("10,104,914.34", "10,104,914.35"),
                         ("14,537,724.60", "14,537,724.61"), ("10,104,914.34", "-1.00")):
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                self.lease(1, replace(self.words[1][2], old, new))

    def test_missing_amended_component_is_unknown_not_zero_or_total(self):
        notes = self.words[1][2]
        label = next(word for word in notes if word[4] == "偿还租赁负债支付的金额")
        modified = [word for word in notes if not (word[4] == "10,104,914.34"
                    and abs(pilot.previous.centre(word) - pilot.previous.centre(label)) < 1)]
        component = self.lease(1, modified)
        self.assertIsNone(component["current_cny"])
        self.assertEqual(component["note_total"]["current_cny"], "10104914.34")
        self.assertEqual(component["full_lease_cash_coverage"], "UNKNOWN")
        self.assertIsNone(component["full_lease_cash_not_already_deducted"])

    def test_source_arithmetic_same_version_and_fixed_decimal_context(self):
        expected = ("187953513.0610703007932992135", "99433230.26638803154451103358")
        for bundle, amount in zip(self.report["version_bundles"], expected):
            with localcontext() as context:
                context.prec = 4
                context.rounding = ROUND_DOWN
                self.assertEqual(pilot.source_arithmetic(bundle["observations"]), bundle["ordinary_source_arithmetic"])
            self.assertEqual(bundle["ordinary_source_arithmetic"]["alpha_observed"], "0.8333829610863322896713284534")
            self.assertEqual(bundle["ordinary_source_arithmetic"]["FCF_ordinary_source_arithmetic_cny"], amount)
        values = copy.deepcopy(self.report["version_bundles"][0]["observations"])
        values["Capex"]["observed_value"] = None
        self.assertEqual(pilot.source_arithmetic(values)["status"], "UNKNOWN")

    def test_source_arithmetic_rejects_cross_version_pdf_year_scope_fields(self):
        for name, key, value in (("OCF", "version", capture.TARGETS[1][0]), ("N", "document_sha256", "f" * 64),
                                 ("N", "statement_scope", "PARENT"), ("E", "period_start", "2024-01-01"),
                                 ("Capex", "field", "investment_outflow_total"), ("OCF", "unit", "CNY_10K")):
            values = copy.deepcopy(self.report["version_bundles"][0]["observations"])
            values[name][key] = value
            with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                pilot.source_arithmetic(values)

    def test_scope_physical_pages_authority_and_notice_are_frozen(self):
        for key, new in (("period_end", "2024-12-31"), ("timing_policy", "ASSUMED_NEXT_DAY"),
                         ("official_selection", True), ("diagnostic_only", 1)):
            scope = copy.deepcopy(self.scope)
            scope[key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.fixed_scope(scope)
        scope = copy.deepcopy(self.scope)
        scope["documents"][0]["asset_pages"] = [113, 114, 115, 116]
        with self.assertRaises(ValueError):
            pilot.fixed_scope(scope)
        scope = copy.deepcopy(self.scope)
        scope["earlier_correction_notice"]["interpretation"] = "ANNUAL_FIELD_VERSION"
        with self.assertRaises(ValueError):
            pilot.fixed_scope(scope)

    def test_notice_is_not_annual_field_revision_or_whole_report_audit(self):
        notice = self.report["earlier_correction_notice"]
        self.assertEqual(notice["document"]["announcement_id"], "1222163844")
        self.assertEqual(notice["document"]["page_count"], 17)
        self.assertIs(notice["used_as_annual_field_version"], False)
        self.assertEqual(notice["audit_gate_conclusion"], "UNKNOWN")
        for key, new in (("interpretation", "ANNUAL_FIELD_VERSION"), ("used_as_annual_field_version", True),
                         ("audit_gate_conclusion", "PASS")):
            report = copy.deepcopy(self.report)
            report["earlier_correction_notice"][key] = new
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_resealed_report_cannot_promote_timing_ready_or_full_lease(self):
        for key, new in (("diagnostic_available_at", "2024-04-29"), ("historical_pit_observations_admitted", 1),
                         ("production_reader_ready", True), ("complete_revision_chain_verified", True),
                         ("full_amended_audit_status", "AUDITED")):
            report = copy.deepcopy(self.report)
            report[key] = new
            with self.subTest(key=key):
                self.reject_resealed(report)
        for key in pilot.UNKNOWN_FIELDS:
            report = copy.deepcopy(self.report)
            report["version_bundles"][0]["pit_and_standard_outputs"][key] = "0.00"
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_resealed_original_lease_cannot_be_backfilled_or_add_alias(self):
        for key, new in (("current_cny", "10104914.34"), ("prior_comparative_cny", "14537724.60"),
                         ("observed_cny", "10104914.34"), ("principal_interest_cash_bridge", "KNOWN"),
                         ("full_lease_cash_not_already_deducted", "10104914.34")):
            report = copy.deepcopy(self.report)
            report["version_bundles"][0]["lease_financing_component"][key] = new
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_resealed_report_rejects_source_math_and_evidence_drift(self):
        for name in ("evidence", "source", "math", "lease", "table"):
            report = copy.deepcopy(self.report)
            bundle = report["version_bundles"][1]
            if name == "evidence":
                bundle["observations"]["E"]["evidence_refs"] = ["unverified"]
            elif name == "source":
                bundle["observations"]["OCF"]["observed_value"] = "0.00"
            elif name == "math":
                bundle["ordinary_source_arithmetic"]["alpha_observed"] = "1"
            elif name == "lease":
                bundle["lease_financing_component"]["evidence_refs"] = []
            else:
                bundle["tables"]["rows"]["E"]["current_cny"] = "0.00"
            with self.subTest(name=name):
                self.reject_resealed(report)

    def test_resealed_documents_and_filtered_catalogue_cannot_drift(self):
        for which, key, new in (("annual", "page_count", 240), ("annual", "evidence_pages", [134]),
                                ("notice", "url", "https://example.com/file.PDF"), ("notice", "page_count", 3)):
            report = copy.deepcopy(self.report)
            doc = report["source_documents"][0] if which == "annual" else report["earlier_correction_notice"]["document"]
            doc[key] = new
            with self.subTest(which=which, key=key):
                self.reject_resealed(report)
        report = copy.deepcopy(self.report)
        report["catalogue_queries"][2]["empty_result_proves_no_withdrawal"] = True
        self.reject_resealed(report)

    def test_five_year_and_strategy_outputs_are_forbidden(self):
        for key in ("ranking", "orders", "F1", "F5", "nav", "target_weights"):
            report = copy.deepcopy(self.report)
            report["unapproved"] = {key: []}
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_all_raw_hashes_page_refs_and_code_identity(self):
        for resource in self.report["manifest"]["raw_resources"]:
            self.assertEqual(len(base.verified_bytes(ROOT, resource["local_path"], resource["sha256"])), resource["bytes"])
        for bundle, doc in zip(self.report["version_bundles"], self.report["source_documents"]):
            for item in bundle["observations"].values():
                self.assertEqual(item["document_sha256"], doc["sha256"])
                self.assertTrue(all(f'pdf:sha256:{doc["sha256"]}:physical-page:' in ref for ref in item["evidence_refs"]))
        for path, digest in self.report["manifest"]["code_hashes"].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)

    def test_offline_rebuild_and_canonical_roundtrip_match(self):
        with patch.object(capture.previous.requests, "request", side_effect=AssertionError("unexpected network")):
            report = pilot.build_review(ROOT)
        self.assertEqual(base.canonical_bytes(report), base.canonical_bytes(self.report))
        self.assertEqual(pilot.render_markdown(base._json(base.canonical_bytes(report))), pilot.render_markdown(report))

    def test_previous_2024_review_immutable_and_all_pit_unknown(self):
        reference = self.report["manifest"]["previous_2024_review"]
        old = base._json(base.verified_bytes(ROOT, reference["path"], reference["sha256"]))
        self.assertEqual(old["logical_content_hash"], reference["logical_content_hash"])
        self.assertEqual(reference["sha256"], "eb9a362c3ecfbf568f0f61040197a4c213cbbc40dbc40a55fae65a9805bfd2b7")
        self.assertEqual(self.report["historical_pit_observations_admitted"], 0)
        self.assertTrue(all(value is None for bundle in self.report["version_bundles"]
                            for value in bundle["pit_and_standard_outputs"].values()))

    def test_two_process_artifacts_match_and_refuse_overwrite(self):
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

    def test_cli_frozen_check_does_not_write_or_fetch(self):
        result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / pilot.TOOL), "--check"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.report["logical_content_hash"], result.stdout)

    def test_source_hash_mismatch_and_path_escape_fail(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                base.verified_bytes(Path(folder), "../outside.pdf", "0" * 64)
        doc = self.report["source_documents"][0]
        with self.assertRaises(ValueError):
            base.verified_bytes(ROOT, doc["path"], "0" * 64)
