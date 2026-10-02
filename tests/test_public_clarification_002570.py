"""Empty public queries and later audit scopes must not manufacture PIT proof."""

from __future__ import annotations

import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "docs/data-pilots/2026-10-02-002570-public-clarification-followup.json"


class PublicClarificationCaptureTests(TestCase):
    def setUp(self) -> None:
        try:
            from scripts.pilots import capture_002570_public_clarification
        except ImportError:
            self.skipTest("optional requests pilot dependency unavailable")
        self.module = capture_002570_public_clarification
        self.rows = [
            {"secCode": "002570", "orgId": "9900019035",
             "announcementId": identifier, "announcementTitle": role,
             "adjunctUrl": f"finalpage/{day}/{identifier}.{suffix}",
             "announcementTime": 1745856000000}
            for role, identifier, day, suffix in self.module.PDF_TARGETS
        ]

    def raw_catalogue(self, rows) -> bytes:
        return json.dumps({
            "announcements": rows, "totalAnnouncement": len(rows),
            "totalRecordNum": len(rows), "totalpages": 1 if rows else 0,
            "hasMore": False,
        }).encode()

    def raw_detail(self, target=None):
        target = target or self.module.DETAIL_TARGETS[0]
        role, identifier, day, suffix = target
        path = f"finalpage/{day}/{identifier}.{suffix}"
        return {
            "announcement": {"secCode": "002570", "orgId": "9900019035",
                             "announcementId": identifier, "adjunctUrl": path,
                             "announcementTime": self.module.DETAIL_CLOCKS[identifier],
                             "associateAnnouncement": None, "storageTime": None},
            "fileUrl": f"http://static.cninfo.com.cn/{path}", "bulletinStatus": None,
        }

    def test_null_rows_require_explicit_empty_query_counters(self) -> None:
        value = {"announcements": None, "totalAnnouncement": 0,
                 "totalRecordNum": 0, "totalpages": 0, "hasMore": False}
        self.assertEqual(self.module.parse_catalogue(json.dumps(value).encode()), {})
        for key, bad in (("totalRecordNum", None), ("totalRecordNum", False),
                         ("totalpages", 1), ("totalpages", False),
                         ("totalAnnouncement", 1), ("totalAnnouncement", False),
                         ("hasMore", None)):
            changed = {**value, key: bad}
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                self.module.parse_catalogue(json.dumps(changed).encode())

    def test_incomplete_catalogue_and_duplicate_json_keys_hard_fail(self) -> None:
        value = json.loads(self.raw_catalogue(self.rows))
        for changed in ({**value, "hasMore": True},
                        {**value, "totalAnnouncement": len(self.rows) + 1}):
            with self.assertRaises(ValueError):
                self.module.parse_catalogue(json.dumps(changed).encode())
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            self.module.parse_catalogue(b'{"announcements":[],"announcements":null}')

    def test_catalogue_identity_ids_title_and_clock_cannot_drift(self) -> None:
        for field, bad in (("secCode", "000637"), ("orgId", "other"),
                           ("announcementId", ""), ("announcementTitle", " "),
                           ("announcementTime", True)):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.module.parse_catalogue(self.raw_catalogue(rows))
        with self.assertRaisesRegex(ValueError, "duplicate announcement"):
            self.module.parse_catalogue(self.raw_catalogue(self.rows + [self.rows[0]]))

    def test_cross_query_drift_missing_target_and_pdf_case_drift_hard_fail(self) -> None:
        valid = self.module.parse_catalogue(self.raw_catalogue(self.rows))
        self.assertEqual(len(self.module.merge_catalogues([valid, valid])), 3)
        drift = copy.deepcopy(valid)
        identifier = self.rows[0]["announcementId"]
        drift[identifier]["announcementTitle"] = "other title"
        with self.assertRaisesRegex(ValueError, "cross-query"):
            self.module.merge_catalogues([valid, drift])
        with self.assertRaisesRegex(ValueError, "required PDF"):
            self.module.merge_catalogues([{}])
        drift = copy.deepcopy(valid)
        drift[identifier]["adjunctUrl"] = drift[identifier]["adjunctUrl"].replace(".pdf", ".PDF")
        with self.assertRaisesRegex(ValueError, "URL drift"):
            self.module.merge_catalogues([drift])

    def test_detail_identity_fixed_clock_and_raw_file_url_hard_fail_on_drift(self) -> None:
        target = self.module.DETAIL_TARGETS[0]
        for field, bad in (("secCode", "000662"), ("orgId", "other"),
                           ("announcementId", "other"), ("adjunctUrl", "other.PDF"),
                           ("announcementTime", True), ("announcementTime", 1)):
            value = self.raw_detail(target)
            value["announcement"][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.module.parse_detail(json.dumps(value).encode(), target)
        value = self.raw_detail(target)
        value["fileUrl"] = "https://third-party.invalid/report.PDF"
        with self.assertRaisesRegex(ValueError, "file URL drift"):
            self.module.parse_detail(json.dumps(value).encode(), target)
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            self.module.parse_detail(b'{"announcement":{},"announcement":{}}', target)

    def test_null_or_nonnull_detail_fields_do_not_certify_availability_or_relationships(self) -> None:
        target = self.module.DETAIL_TARGETS[0]
        for filled in (False, True):
            value = self.raw_detail(target)
            if filled:
                value["announcement"]["associateAnnouncement"] = [{"id": "other"}]
                value["announcement"]["storageTime"] = 1682697600123
                value["bulletinStatus"] = "A"
            observed = self.module.parse_detail(json.dumps(value).encode(), target)
            self.assertEqual(observed["associate_announcement_raw"], value["announcement"]["associateAnnouncement"])
            self.assertEqual(observed["storage_time_raw"], value["announcement"]["storageTime"])
            self.assertEqual(observed["bulletin_status_raw"], value["bulletinStatus"])
            self.assertIsNone(observed["exact_available_at_utc"])
            self.assertFalse(observed["earliest_public_availability_verified"])
            self.assertFalse(observed["withdrawal_or_platform_replacement_verified"])

    def test_existing_capture_is_refused_before_network(self) -> None:
        with TemporaryDirectory() as directory, patch.object(self.module.requests, "request") as request:
            with self.assertRaises(FileExistsError):
                self.module.capture(Path(directory))
            request.assert_not_called()

    def test_http_redirect_is_not_followed_and_partial_capture_is_not_completed(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "new-capture"
            with patch.object(self.module.requests, "request", return_value=SimpleNamespace(status_code=302)) as request:
                with self.assertRaisesRegex(ValueError, "HTTP 302"):
                    self.module.capture(output)
                self.assertEqual(request.call_count, 1)
                self.assertIs(request.call_args.kwargs["allow_redirects"], False)
                self.assertFalse((output / "capture.json").exists())

    def test_complete_mock_capture_only_calls_explicit_read_only_source_endpoints(self) -> None:
        def respond(method, url, **kwargs):
            if url == self.module.CATALOGUE_ENDPOINT:
                raw = self.raw_catalogue(self.rows)
            elif url == self.module.DETAIL_ENDPOINT:
                identifier = kwargs["params"]["announceId"]
                target = next(x for x in self.module.DETAIL_TARGETS if x[1] == identifier)
                raw = json.dumps(self.raw_detail(target)).encode()
            elif url == self.module.DETAIL_PAGE:
                raw = b'<script src="notice-detail.js"></script>'
            elif url == self.module.DETAIL_SCRIPT:
                raw = b"/announcement/bulletin_detail"
            else:
                self.assertTrue(url.startswith("https://static.cninfo.com.cn/finalpage/"))
                raw = b"%PDF-1.7 mock only"
            return SimpleNamespace(status_code=200, content=raw)
        with TemporaryDirectory() as directory, patch.object(self.module.requests, "request", side_effect=respond) as request:
            output = Path(directory) / "new-capture"
            result = self.module.capture(output)
            self.assertEqual(len(result["resources"]), 21)
            self.assertEqual(request.call_count, 21)
            self.assertEqual(json.loads((output / "capture.json").read_text(encoding="utf-8")), result)
            self.assertFalse(result["research_eligible"])
            self.assertFalse(result["production_reader_ready"])
            for call in request.call_args_list:
                self.assertIs(call.kwargs["allow_redirects"], False)


class PublicClarificationEvidenceTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.review = json.loads(REVIEW.read_text(encoding="utf-8"))

    def test_review_preserves_unknown_status_and_bounded_search_meaning(self) -> None:
        review = self.review
        for flag in ("research_eligible", "snapshot_published", "production_reader_ready",
                     "complete_revision_chain_verified", "withdrawal_or_platform_replacement_verified",
                     "earliest_public_availability_verified", "period_wording_ambiguity_resolved",
                     "external_evidence_requests_sent", "cross_issuer_pit_inputs_combined"):
            self.assertFalse(review[flag])
        for key in ("exact_available_at_utc", "amended_2022_full_statement_reaudit_stated", "explicit_no_2022_reaudit_stated"):
            self.assertIsNone(review[key])
        self.assertFalse(review["catalogue_review"]["empty_result_proves_absence_of_event"])
        self.assertFalse(review["detail_review"]["current_rows_prove_historical_continuous_availability"])
        for domain in review["bounded_other_domain_searches"]:
            self.assertFalse(domain["universal_public_pdf_impossibility_proven"])

    def test_later_annual_audit_scopes_are_not_2022_full_statement_reaudit(self) -> None:
        audit, performance_2024, performance_2025 = self.review["audit_scope_review"]
        self.assertEqual(audit["opinion_period_end"], "2024-12-31")
        self.assertEqual(performance_2024["stated_audit_year"], "2024")
        self.assertEqual(performance_2025["stated_audit_year"], "2025")
        for row in self.review["audit_scope_review"]:
            self.assertIsNone(row["amended_2022_full_statement_reaudit_stated"])
            self.assertIsNone(row["explicit_no_2022_reaudit_stated"])

    def test_comparative_reconciliation_is_2023_not_target_2022(self) -> None:
        row = self.review["comparative_reconciliation"]
        self.assertEqual(row["report_period_end"], "2024-12-31")
        self.assertEqual(row["comparative_balance_date"], "2023-12-31")
        for field in row["fields"]:
            self.assertEqual(Decimal(field["after"]) - Decimal(field["before"]), Decimal(field["delta"]))
            self.assertEqual(field["after"], field["audit_comparative"])
        self.assertEqual(sum(Decimal(field["delta"]) for field in row["fields"]), Decimal("0.00"))
        self.assertNotEqual(row["fields"][0]["delta"], "-260012912.05")
        self.assertFalse(row["comparison_values_may_replace_2022_values"])
        self.assertFalse(row["arithmetic_match_proves_target_2022_reaudit"])

    def test_fixed_raw_manifest_sources_and_physical_scope_pages_match_when_local(self) -> None:
        try:
            import fitz
            from scripts.pilots import capture_002570_public_clarification as module
        except ImportError:
            self.skipTest("optional PDF/requests pilot dependencies unavailable")
        record = self.review["capture_manifest"]
        path = ROOT / record["local_path"]
        if not path.is_file():
            self.skipTest("local raw clarification capture unavailable")
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
        capture = json.loads(raw)
        self.assertEqual(len(capture["resources"]), 21)
        resources = {row["name"]: row for row in capture["resources"]}
        for resource in resources.values():
            raw = (ROOT / resource["local_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), resource["sha256"])
            self.assertEqual(len(raw), resource["bytes"])
        observed_counts = []
        catalogues = []
        for catalogue in capture["catalogues"]:
            rows = module.parse_catalogue((ROOT / resources[catalogue["resource"]]["local_path"]).read_bytes())
            catalogues.append(rows)
            observed_counts.append(len(rows))
        self.assertEqual(observed_counts, self.review["catalogue_review"]["query_counts"])
        module.merge_catalogues(catalogues)
        for target, detail in zip(module.DETAIL_TARGETS, capture["details"]):
            observed = module.parse_detail((ROOT / resources[detail["resource"]]["local_path"]).read_bytes(), target)
            self.assertEqual(observed, {key: value for key, value in detail.items() if key != "resource"})
        parent = self.review["parent_evidence"]
        self.assertEqual(hashlib.sha256((ROOT / parent["local_path"]).read_bytes()).hexdigest(), parent["sha256"])
        for row in self.review["audit_scope_review"]:
            resource = resources[row["resource"]]
            self.assertEqual(resource["sha256"], row["sha256"])
            with fitz.open(ROOT / resource["local_path"]) as pdf:
                self.assertEqual(len(pdf), row["pages"])
                scope = "".join(pdf[row["scope_page"] - 1].get_text().split())
                if row["role"] == "audit_2024":
                    self.assertIn(row["report_number"], scope)
                    self.assertIn("2024年12月31日", scope)
                    self.assertIn("2025年4月27日", "".join(pdf[row["signature_page"] - 1].get_text().split()))
                    comparison = self.review["comparative_reconciliation"]
                    text = "".join(pdf[comparison["audit_statement_page"] - 1].get_text().split())
                    self.assertIn("2023年12月31日", text)
                    for field in comparison["fields"]:
                        self.assertIn(f'{Decimal(field["after"]):,.2f}', text)
                    note = "".join(pdf[row["prior_error_note_page"] - 1].get_text().split())
                    self.assertIn("前期会计差错", note)
                    for field in comparison["fields"]:
                        self.assertIn(f'{Decimal(field["delta"]):,.2f}', note)
                else:
                    self.assertIn(row["stated_audit_year"] + "年12月31日", scope)
        notice = self.review["comparative_reconciliation"]["correction_notice"]
        raw = (ROOT / notice["local_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), notice["sha256"])
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            text = "".join(pdf[notice["physical_page"] - 1].get_text().split())
            self.assertIn("合并资产负债表（2023年12月31日）", text)
            for field in self.review["comparative_reconciliation"]["fields"]:
                for key in ("before", "after", "delta"):
                    self.assertIn(f'{Decimal(field[key]):,.2f}', text)
