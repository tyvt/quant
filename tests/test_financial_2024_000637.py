"""Bounded 2024 source extension cannot relax timing, scope or missing data."""

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
from scripts.pilots import capture_financial_2024_000637 as capture
from scripts.pilots import verify_financial_2024_000637 as pilot

ROOT = Path(__file__).resolve().parents[1]


def relabel(word, value):
    return (*word[:4], value, *word[5:])


def replace(words, old, new):
    return [relabel(word, new) if word[4] == old else word for word in words]


class Financial2024CatalogueTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = base._json((ROOT / "storage/pilots/financial-000637-2024-chain-2026-10-02/capture.json").read_bytes())
        cls.raw = [(ROOT / x["local_path"]).read_bytes() for x in cls.audit["resources"][:3]]

    def encode(self, value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def test_bounded_filtered_counts_and_explicit_original_amended_ids(self):
        parsed = [capture.parse_catalogue(raw) for raw in self.raw]
        self.assertEqual([len(x) for x in parsed], [6, 22, 0])
        rows = capture.merge_catalogues(parsed)
        self.assertEqual(rows["1223369814"]["announcementTitle"], "2024年年度报告")
        self.assertEqual(rows["1225460241"]["announcementTitle"], "2024年年度报告（更正后）")
        self.assertEqual(len(parsed[0]), 6)  # Includes half-year/summary, not six full annuals.

    def test_empty_null_rows_need_all_explicit_zero_counters(self):
        value = capture.strict_json(self.raw[2])
        value["announcements"] = None
        self.assertEqual(capture.parse_catalogue(self.encode(value)), {})
        for key in ("totalRecordNum", "totalAnnouncement", "totalpages"):
            changed = copy.deepcopy(value)
            changed[key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.parse_catalogue(self.encode(changed))

    def test_bool_counters_has_more_or_truncated_page_fail(self):
        for key, new in (("totalAnnouncement", True), ("totalRecordNum", True), ("totalpages", False),
                         ("totalpages", 1), ("hasMore", True), ("totalAnnouncement", 31)):
            value = capture.strict_json(self.raw[0])
            value[key] = new
            with self.subTest(key=key, new=new), self.assertRaises(ValueError):
                capture.parse_catalogue(self.encode(value))

    def test_duplicate_json_keys_and_nonfinite_numbers_fail(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                capture.strict_json(raw)

    def test_security_org_title_clock_and_url_drift_fail(self):
        for key, new in (("secCode", "002570"), ("orgId", "different"), ("announcementId", ""),
                         ("announcementTitle", ""), ("announcementTime", True),
                         ("adjunctUrl", "https://example.com/file.PDF")):
            value = capture.strict_json(self.raw[0])
            value["announcements"][0][key] = new
            with self.subTest(key=key), self.assertRaises(ValueError):
                capture.parse_catalogue(self.encode(value))

    def test_duplicate_announcement_and_count_mismatch_fail(self):
        value = capture.strict_json(self.raw[0])
        value["announcements"][1] = value["announcements"][0]
        with self.assertRaises(ValueError):
            capture.parse_catalogue(self.encode(value))
        value = capture.strict_json(self.raw[0])
        value["announcements"].pop()
        with self.assertRaises(ValueError):
            capture.parse_catalogue(self.encode(value))

    def test_cross_query_same_id_drift_and_target_substitution_fail(self):
        rows = capture.parse_catalogue(self.raw[0])
        changed = copy.deepcopy(rows)
        changed["1223369814"]["announcementTime"] += 1
        with self.assertRaisesRegex(ValueError, "cross-query"):
            capture.merge_catalogues([rows, changed])
        for key, new in (("adjunctUrl", "finalpage/2025-04-29/1223369873.PDF"),
                         ("announcementTitle", "2024年年度报告摘要")):
            changed = copy.deepcopy(rows)
            changed["1223369814"][key] = new
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity drift"):
                capture.merge_catalogues([changed])

    def test_capture_refuses_overwrite_before_network(self):
        with TemporaryDirectory() as folder, patch.object(capture.requests, "request") as network:
            with self.assertRaises(FileExistsError):
                capture.capture(Path(folder))
            network.assert_not_called()

    def test_redirect_or_error_never_retries_or_falls_back(self):
        for status in (302, 500):
            with self.subTest(status=status), TemporaryDirectory() as folder:
                with patch.object(capture.requests, "request", return_value=Mock(status_code=status)) as network:
                    with self.assertRaises(ValueError):
                        capture.capture(Path(folder) / "new")
                    self.assertEqual(network.call_count, 1)
                    self.assertIs(network.call_args.kwargs["allow_redirects"], False)

    def test_non_pdf_response_is_not_accepted(self):
        replies = [Mock(status_code=200, content=raw) for raw in self.raw]
        replies.append(Mock(status_code=200, content=b"<html>error</html>"))
        with TemporaryDirectory() as folder, patch.object(capture.requests, "request", side_effect=replies) as network:
            with self.assertRaisesRegex(ValueError, "signature"):
                capture.capture(Path(folder) / "new")
            self.assertEqual(network.call_count, 4)


class Financial2024SourceTests(TestCase):
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
                                  pdf[plan["lease_note_page"] - 1].get_text("words")))

    def tables(self, index=0, assets=None, cash=None, notes=None):
        original = self.words[index]
        return pilot.extract_tables(original[0] if assets is None else assets,
                                    original[1] if cash is None else cash,
                                    original[2] if notes is None else notes)

    def test_real_two_versions_target_2024_not_2025_comparatives(self):
        for index, ocf in enumerate(("9077909.18", "-185115131.48")):
            rows = self.tables(index)["rows"]
            self.assertEqual(rows["E"]["current_cny"], "645132659.65")
            self.assertEqual(rows["N"]["current_cny"], "112947471.32")
            self.assertEqual(rows["OCF"]["current_cny"], ocf)
            self.assertEqual(rows["Capex"]["current_cny"], "79764639.75")
        self.assertEqual([x["page_count"] for x in self.report["source_documents"]], [240, 260])

    def test_geometry_is_independent_of_word_order(self):
        for index, words in enumerate(self.words):
            self.assertEqual(self.tables(index), pilot.extract_tables(*[list(reversed(x)) for x in words]))

    def test_both_columns_equity_ocf_financing_reconcile(self):
        for bundle in self.report["version_bundles"]:
            for column, checks in bundle["tables"]["checks"].items():
                for name, check in checks.items():
                    if column == "prior_comparative_cny" and name == "financing":
                        # The borrowing comparative is blank, not an explicit zero.
                        self.assertEqual(check, {"difference_cny": None, "status": "UNKNOWN"})
                        continue
                    self.assertEqual(check, {"difference_cny": "0.00", "status": "RECONCILED"})

    def test_2023_comparatives_are_not_original_window_publications(self):
        self.assertEqual(self.tables()["rows"]["OCF"]["prior_comparative_cny"], "353022150.03")
        self.assertEqual(self.tables(1)["rows"]["OCF"]["prior_comparative_cny"], "246804136.31")
        self.assertTrue(all(x["period_end"] == "2024-12-31"
                            for b in self.report["version_bundles"] for x in b["observations"].values()))
        self.assertIn("2021_2023_original_window", self.report["remaining_gaps"])

    def test_missing_e_ocf_or_capex_is_not_zero_or_comparative(self):
        assets, cash, notes = self.words[0]
        for name, amount, group in (("E", "645,132,659.65", 0), ("OCF", "9,077,909.18", 1),
                                    ("Capex", "79,764,639.75", 1)):
            words = [assets, cash, notes]
            # Capex's value also appears as the investment subtotal; remove both
            # to verify absence is not backfilled from another row.
            words[group] = [word for word in words[group] if word[4] != amount]
            with self.subTest(name=name):
                result = pilot.extract_tables(*words)
                self.assertIsNone(result["rows"][name]["current_cny"])
                self.assertIsNotNone(result["rows"][name]["prior_comparative_cny"])

    def test_dash_currency_unknown_differs_from_explicit_zero(self):
        assets = replace(self.words[0][0], "645,132,659.65", "—")
        self.assertIsNone(self.tables(assets=assets)["rows"]["E"]["current_cny"])
        self.assertEqual(pilot.minority.parse_money_cell("0.00"), "0.00")

    def test_duplicate_row_or_currency_cell_fails(self):
        for label in ("经营活动产生的现金流量净额", "9,077,909.18"):
            cash = self.words[0][1]
            extra = next(word for word in cash if word[4] == label)
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.tables(cash=[*cash, extra])

    def test_nonfinite_malformed_and_negative_payment_fail(self):
        for amount in ("NaN", "Infinity", "79,764,639.7", "-1.00"):
            cash = replace(self.words[0][1], "79,764,639.75", amount)
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.tables(cash=cash)

    def test_one_cent_subtotal_drift_fails(self):
        for group, old, new in ((0, "645,132,659.65", "645,132,659.66"),
                                (1, "9,077,909.18", "9,077,909.19"),
                                (2, "14,834,290.95", "14,834,290.96")):
            words = list(self.words[0])
            words[group] = replace(words[group], old, new)
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, "reconcile"):
                pilot.extract_tables(*words)

    def test_headers_scope_currency_and_annual_period_fail_closed(self):
        for group, old, new in ((0, "单位：元", "单位：万元"),
                                (0, "1、合并资产负债表", "1、母公司资产负债表"),
                                (1, "2024", "2025"), (1, "年度", "季度"),
                                (1, "6、母公司现金流量表", "未核实边界")):
            words = list(self.words[0])
            words[group] = replace(words[group], old, new)
            with self.subTest(group=group, old=old), self.assertRaises(ValueError):
                pilot.extract_tables(*words)

    def test_split_capex_label_adjacency_and_payment_identity_required(self):
        cash = [(*word[:1], word[1] + 5, word[2], word[3] + 5, *word[4:])
                if word[4] == "期资产支付的现金" else word for word in self.words[0][1]]
        with self.assertRaisesRegex(ValueError, "adjacent"):
            self.tables(cash=cash)
        with self.assertRaises(ValueError):
            self.tables(cash=replace(self.words[0][1], "期资产支付的现金", "期资产收回的现金净额"))

    def test_lease_financing_heading_unit_and_total_required(self):
        for old, new in (("与筹资活动有关的现金", "与投资活动有关的现金"), ("单位：元", "单位：万元"),
                         ("85,086,290.95", "85,086,290.96")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.tables(notes=replace(self.words[0][2], old, new))

    def test_missing_lease_component_keeps_full_cash_unknown(self):
        notes = [word for word in self.words[0][2] if word[4] != "14,834,290.95"]
        result = self.tables(notes=notes)
        self.assertIsNone(result["rows"]["lease_financing_component"]["current_cny"])
        self.assertEqual(result["checks"]["current_cny"]["financing"]["status"], "UNKNOWN")
        for bundle in self.report["version_bundles"]:
            self.assertEqual(bundle["lease_financing_component"]["full_lease_cash_coverage"], "UNKNOWN")
            self.assertIsNone(bundle["pit_and_standard_outputs"]["FCF_conservative"])

    def test_source_arithmetic_uses_same_version_and_decimal_context(self):
        b = self.report["version_bundles"][0]
        with localcontext() as context:
            context.prec = 4
            context.rounding = ROUND_DOWN
            self.assertEqual(pilot.source_arithmetic(b["observations"]), b["ordinary_source_arithmetic"])
        values = copy.deepcopy(b["observations"])
        values["OCF"]["version"] = self.report["version_bundles"][1]["version"]
        with self.assertRaises(ValueError):
            pilot.source_arithmetic(values)
        values = copy.deepcopy(b["observations"])
        values["Capex"]["observed_value"] = None
        self.assertEqual(pilot.source_arithmetic(values)["status"], "UNKNOWN")

    def test_source_arithmetic_rejects_cross_pdf_period_scope_and_fields(self):
        for field, key, value in (("N", "document_sha256", "f" * 64), ("N", "statement_scope", "PARENT"),
                                  ("OCF", "period_start", "2025-01-01"), ("Capex", "field", "investment_outflow_total")):
            values = copy.deepcopy(self.report["version_bundles"][0]["observations"])
            values[field][key] = value
            with self.subTest(field=field, key=key), self.assertRaises(ValueError):
                pilot.source_arithmetic(values)

    def test_scope_physical_pages_and_authority_are_frozen(self):
        for key, value in (("period_end", "2025-12-31"), ("timing_policy", "ASSUMED_NEXT_DAY"),
                           ("official_selection", True), ("diagnostic_only", 1)):
            scope = copy.deepcopy(self.scope)
            scope[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                pilot.fixed_scope(scope)
        scope = copy.deepcopy(self.scope)
        scope["documents"][0]["asset_pages"] = [93, 94, 95]
        with self.assertRaises(ValueError):
            pilot.fixed_scope(scope)

    def reject_resealed(self, report):
        report["logical_content_hash"] = base.logical_content_hash(report)
        with self.assertRaises(ValueError):
            pilot.validate_review(report)

    def test_resealed_report_cannot_promote_pit_or_partial_cash(self):
        for key, value in (("diagnostic_available_at", "2025-04-29"), ("historical_pit_observations_admitted", 1),
                           ("complete_revision_chain_verified", True), ("production_reader_ready", True)):
            report = copy.deepcopy(self.report)
            report[key] = value
            with self.subTest(key=key):
                self.reject_resealed(report)
        for key in pilot.UNKNOWN_FIELDS:
            report = copy.deepcopy(self.report)
            report["version_bundles"][0]["pit_and_standard_outputs"][key] = "0.00"
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_resealed_report_rejects_five_year_and_strategy_outputs(self):
        for key in ("ranking", "orders", "F1", "nav", "target_weights"):
            report = copy.deepcopy(self.report)
            report["unapproved"] = {key: []}
            with self.subTest(key=key):
                self.reject_resealed(report)

    def test_resealed_report_rejects_source_evidence_or_calculation_drift(self):
        for mutation in ("evidence", "value", "math", "lease", "table"):
            report = copy.deepcopy(self.report)
            bundle = report["version_bundles"][0]
            if mutation == "evidence":
                bundle["observations"]["E"]["evidence_refs"] = ["unverified"]
            elif mutation == "value":
                bundle["observations"]["OCF"]["observed_value"] = "0.00"
            elif mutation == "math":
                bundle["ordinary_source_arithmetic"]["alpha_observed"] = "1"
            elif mutation == "lease":
                bundle["lease_financing_component"]["observed_cny"] = "0.00"
            else:
                bundle["tables"]["rows"]["E"]["current_cny"] = "0.00"
            with self.subTest(mutation=mutation):
                self.reject_resealed(report)

    def test_all_raw_resources_hashes_and_field_physical_page_refs(self):
        for row in self.report["manifest"]["raw_resources"]:
            raw = base.verified_bytes(ROOT, row["local_path"], row["sha256"])
            self.assertEqual(len(raw), row["bytes"])
        for b, doc in zip(self.report["version_bundles"], self.report["source_documents"]):
            for item in b["observations"].values():
                self.assertEqual(item["document_sha256"], doc["sha256"])
                self.assertTrue(all(f'pdf:sha256:{doc["sha256"]}:physical-page:' in ref for ref in item["evidence_refs"]))
        for file, digest in self.report["manifest"]["code_hashes"].items():
            self.assertEqual(hashlib.sha256((ROOT / file).read_bytes()).hexdigest(), digest)

    def test_offline_twice_and_canonical_roundtrip_are_exact(self):
        with patch.object(capture.requests, "request", side_effect=AssertionError("unexpected network")):
            report = pilot.build_review(ROOT)
        self.assertEqual(base.canonical_bytes(report), base.canonical_bytes(self.report))
        reread = base._json(base.canonical_bytes(report))
        self.assertEqual(pilot.render_markdown(reread), pilot.render_markdown(report))

    def test_parent_2025_report_is_immutable_and_pit_stays_unknown(self):
        reference = self.report["manifest"]["previous_2025_lease_review"]
        raw = base.verified_bytes(ROOT, reference["path"], reference["sha256"])
        old = base._json(raw)
        self.assertEqual(old["logical_content_hash"], reference["logical_content_hash"])
        self.assertEqual(self.report["historical_pit_observations_admitted"], 0)
        for bundle in old["version_bundles"]:
            self.assertEqual(bundle["expense_observations_not_cash"]["short_term_lease_expense"]["prior_comparative_state"],
                             "PAGE_EDGE_CLIPPED_NOT_OBSERVED")

    def test_cli_check_does_not_write_or_fetch(self):
        result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / pilot.TOOL), "--check"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.report["logical_content_hash"], result.stdout)

    def test_two_isolated_processes_have_identical_artifacts_and_refuse_overwrite(self):
        with TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("first", "second")]
            for path in paths:
                result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / pilot.TOOL),
                                         "--output-dir", str(path)], cwd=ROOT,
                                        capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("diagnostic-only.json", "diagnostic-only.md"):
                self.assertEqual((paths[0] / name).read_bytes(), (paths[1] / name).read_bytes())
                self.assertEqual((paths[0] / name).read_bytes(), (ROOT / pilot.OUTPUT / name).read_bytes())
            result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / pilot.TOOL),
                                     "--output-dir", str(paths[0])], cwd=ROOT,
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite", result.stderr)

    def test_source_hash_mismatch_and_path_escape_fail(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                base.verified_bytes(Path(folder), "../outside.pdf", "0" * 64)
        reference = self.report["source_documents"][0]
        with self.assertRaises(ValueError):
            base.verified_bytes(ROOT, reference["path"], "0" * 64)
