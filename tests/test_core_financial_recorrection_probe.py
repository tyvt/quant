"""Real core-statement changes remain evidence, never implicit PIT authorization."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "docs/data-pilots/2026-10-01-core-financial-recorrection-002570.json"


class CoreFinancialCaptureTests(TestCase):
    def setUp(self) -> None:
        try:
            from scripts.pilots import capture_financial_recorrection_002570
        except ImportError:
            self.skipTest("optional requests pilot dependency unavailable")
        self.module = capture_financial_recorrection_002570
        self.rows = [
            {"secCode": "002570", "orgId": "9900019035",
             "announcementId": identifier, "announcementTitle": role,
             "adjunctUrl": f"finalpage/{day}/{identifier}.PDF", "announcementTime": 1}
            for role, identifier, day in self.module.TARGETS
        ]

    def raw(self, rows, total=None) -> bytes:
        return json.dumps({"announcements": rows, "totalAnnouncement": len(rows) if total is None else total}).encode()

    def test_catalogue_requires_complete_return_set_and_unique_keys(self) -> None:
        self.assertEqual(len(self.module.catalogue_rows(self.raw(self.rows))), 8)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.module.catalogue_rows(self.raw(self.rows, 9))
        with self.assertRaisesRegex(ValueError, "duplicate catalogue JSON key"):
            self.module.catalogue_rows(b'{"announcements":[],"announcements":[]}')

    def test_security_identity_and_duplicate_ids_hard_fail(self) -> None:
        for field, value in (("secCode", "000662"), ("orgId", "other")):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity drift"):
                self.module.catalogue_rows(self.raw(rows))
        with self.assertRaisesRegex(ValueError, "duplicate announcement"):
            self.module.catalogue_rows(self.raw(self.rows + [self.rows[0]]))
        with self.assertRaisesRegex(ValueError, "row must be an object"):
            self.module.catalogue_rows(self.raw([None]))

    def test_target_urls_missing_files_and_cross_query_drift_hard_fail(self) -> None:
        rows = self.module.catalogue_rows(self.raw(self.rows))
        self.assertEqual(len(self.module.target_rows([rows, copy.deepcopy(rows)])), 8)
        changed = copy.deepcopy(rows)
        first = self.rows[0]["announcementId"]
        changed[first]["adjunctUrl"] = "https://third-party.invalid/file.PDF"
        with self.assertRaisesRegex(ValueError, "URL drift"):
            self.module.target_rows([changed])
        with self.assertRaisesRegex(ValueError, "cross-query"):
            self.module.target_rows([rows, changed])
        del changed[first]
        with self.assertRaisesRegex(ValueError, "required legal document"):
            self.module.target_rows([changed])

    def test_existing_capture_is_refused_before_network(self) -> None:
        with TemporaryDirectory() as directory, patch.object(self.module.requests, "post") as post:
            with self.assertRaises(FileExistsError):
                self.module.capture(Path(directory))
            post.assert_not_called()

    def test_pdf_redirect_has_no_third_party_fallback_or_snapshot(self) -> None:
        catalogue = SimpleNamespace(status_code=200, content=self.raw(self.rows))
        redirect = SimpleNamespace(status_code=302, content=b"")
        with TemporaryDirectory() as directory, patch.object(self.module.requests, "post", return_value=catalogue) as post, patch.object(self.module.requests, "get", return_value=redirect) as get:
            output = Path(directory) / "capture"
            with self.assertRaisesRegex(ValueError, "HTTP 302"):
                self.module.capture(output)
            self.assertEqual(post.call_count, 4)
            self.assertEqual(get.call_count, 1)
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            self.assertEqual(len(list(output.glob("catalogue-*.json"))), 4)
            self.assertEqual(list(output.glob("*.pdf")), [])


class CoreFinancialEvidenceTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = json.loads(PROBE.read_text(encoding="utf-8"))

    def test_same_period_core_changes_do_not_unlock_production(self) -> None:
        probe = self.probe
        self.assertEqual(probe["security_id"], "sz.002570")
        self.assertEqual(probe["period_end"], "2022-12-31")
        self.assertEqual(probe["observation_scope"]["statement_scope"], "CONSOLIDATED")
        self.assertTrue(probe["observation_scope"]["two_core_statement_corrections_observed"])
        self.assertFalse(probe["observation_scope"]["core_financial_recorrection_fixture_accepted"])
        for flag in ("research_eligible", "production_reader_ready", "snapshot_published", "complete_revision_chain_verified", "withdrawal_or_platform_replacement_verified"):
            self.assertFalse(probe[flag])
        self.assertIsNone(probe["exact_available_at_utc"])
        self.assertFalse(probe["search_followup"]["universal_public_pdf_impossibility_proven"])
        self.assertFalse(probe["search_followup"]["cross_issuer_pit_inputs_combined"])

    def test_exact_income_bridge_and_rounded_reply_are_not_interchangeable(self) -> None:
        original, first, second = [row["fields"] for row in self.probe["observed_versions"]]
        revenue_change = Decimal(first["revenue"]) - Decimal(original["revenue"])
        cost_change = Decimal(first["operating_cost"]) - Decimal(original["operating_cost"])
        self.assertEqual(revenue_change, Decimal("-145452723.30"))
        self.assertEqual(revenue_change, cost_change)
        self.assertEqual(first["revenue"], second["revenue"])
        reply = self.probe["correction_evidence"][2]
        rounded_cny = Decimal(reply["rounded_revenue_change"]) * 10000
        self.assertNotEqual(revenue_change, rounded_cny)
        self.assertEqual(revenue_change - rounded_cny, Decimal(reply["difference_from_rounded_cny"]))

    def test_asset_reclassification_is_exact_and_blank_liability_is_not_zero(self) -> None:
        original, first, second = [row["fields"] for row in self.probe["observed_versions"]]
        for fields in (("investment_property", "fixed_assets", "intangible_assets"), ("other_noncurrent_financial_assets", "other_noncurrent_assets")):
            self.assertEqual(sum(Decimal(second[key]) - Decimal(first[key]) for key in fields), 0)
        self.assertIsNone(original["other_noncurrent_liabilities"])
        self.assertIsNone(first["other_noncurrent_liabilities"])
        self.assertEqual(second["other_noncurrent_liabilities"], "18000000.00")
        self.assertEqual([row["source_states"]["other_noncurrent_liabilities"] for row in self.probe["observed_versions"]], ["BLANK_NOT_ZERO", "BLANK_NOT_ZERO", "EXPLICIT_NUMERIC"])
        self.assertEqual({row["operating_cashflow_net"] for row in (original, first, second)}, {"377416659.60"})

    def test_original_audit_number_and_ambiguous_special_report_do_not_prove_reaudit(self) -> None:
        for row in self.probe["observed_versions"]:
            self.assertEqual(row["embedded_audit_report_number"], "大华审字[2023]001405号")
            self.assertIsNone(row["amended_full_statement_reaudit_stated"])
            self.assertIsNone(row["explicit_no_reaudit_stated"])
        first, second = self.probe["special_review_scopes"]
        for row in (first, second):
            self.assertFalse(row["full_amended_2022_statement_audit_verified"])
            self.assertTrue(row["purpose_restriction_observed"])
        self.assertEqual(second["report_title_periods"], ["2022", "2023"])
        self.assertEqual(second["purpose_paragraph_period"], "2024")
        self.assertTrue(second["period_wording_ambiguity_observed"])
        self.assertFalse(second["ambiguity_resolved"])

    def test_catalogue_midnight_is_not_verified_available_at(self) -> None:
        for document in self.probe["documents"]:
            observed = datetime.fromtimestamp(document["catalogue_time_raw_ms"] / 1000, timezone.utc)
            self.assertEqual(observed.isoformat(), document["catalogue_time_utc"])
            self.assertEqual((observed.hour, observed.minute), (16, 0))
            self.assertIsNone(document["exact_available_at_utc"])
            self.assertIsNone(document["associate_announcement"])
            self.assertIsNone(document["storage_time"])

    def test_fixed_catalogue_and_pdf_bytes_match_documented_rows_when_local(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("optional PDF pilot dependency unavailable")
        for catalogue in self.probe["catalogues"]:
            path = ROOT / catalogue["local_path"]
            if not path.is_file():
                continue
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), catalogue["sha256"])
            self.assertEqual(len(json.loads(raw)["announcements"]), catalogue["returned_count"])
        versions = {row["role"]: row for row in self.probe["observed_versions"]}
        for document in self.probe["documents"]:
            path = ROOT / document["local_path"]
            if not path.is_file():
                continue
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), document["sha256"])
            self.assertEqual(len(raw), document["bytes"])
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                self.assertEqual(len(pdf), document["pages"])
                if document["role"] in versions:
                    fields = versions[document["role"]]["fields"]
                    for definition in self.probe["field_definitions"]:
                        lines = [line.strip().replace(" ", "") for line in pdf[definition["evidence_page"] - 1].get_text().splitlines()]
                        position = lines.index(definition["source_label"])
                        value = fields[definition["field"]]
                        if value is None:
                            self.assertEqual(lines[position + 1], "")
                        else:
                            self.assertEqual(Decimal(lines[position + 1].replace(",", "")), Decimal(value))
                if document["role"] == "second_correction_special_review":
                    text = "".join(pdf[0].get_text().split())
                    self.assertIn("2022-2023年度财务报表更正事项", text)
                    self.assertIn("更正后的2024年度财务信息", text)
