from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from turtle_quant.adapters.dividend_samples import (
    normalize_dividend_sample,
    normalize_dividend_sample_revisions,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "dividends"
    / "spdb-2022-annual-cash-dividend-v1.json"
)
ORDINARY_EVIDENCE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "dividends"
    / "spdb-2022-ordinary-classification-v1.json"
)
LOCAL_ORDINARY_PDF_ROOT = (
    Path(__file__).resolve().parents[1]
    / "storage"
    / "pilots"
    / "dividend-ordinary-2026-10-01"
)
EXPECTED_FIXTURE_SHA256 = (
    "12742e6fa8e2fe166b7e8846a499288c8dca1d1f2002bf8eacb7c0cd790a6ae0"
)
EXPECTED_ORDINARY_EVIDENCE_SHA256 = (
    "8ef02d875900c102bc246342329e38265f7c7c530198ef53a578715e73920b8a"
)


class DividendSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_bytes = FIXTURE_PATH.read_bytes()
        cls.fixture = json.loads(cls.fixture_bytes.decode("utf-8"))
        cls.sample = cls.fixture["sample"]
        cls.ordinary_evidence_bytes = ORDINARY_EVIDENCE_PATH.read_bytes()
        cls.ordinary_evidence = json.loads(cls.ordinary_evidence_bytes.decode("utf-8"))
        cls.first_observed_at = datetime.fromisoformat(
            cls.fixture["captured_at_utc"].replace("Z", "+00:00")
        )

    @staticmethod
    def _next_trading_day(announced_on: date) -> date:
        known = {
            date(2023, 4, 18): date(2023, 4, 19),
            date(2023, 7, 12): date(2023, 7, 13),
            date(2023, 8, 31): date(2023, 9, 1),
        }
        try:
            return known[announced_on]
        except KeyError as exc:
            raise AssertionError(
                f"unexpected announcement date: {announced_on}"
            ) from exc

    def _normalize(self, sample: dict[str, object] | None = None):
        return normalize_dividend_sample(
            self.sample if sample is None else sample,
            first_observed_at=self.first_observed_at,
            next_trading_day=self._next_trading_day,
        )

    def _normalize_revisions(self, sample: dict[str, object] | None = None):
        return normalize_dividend_sample_revisions(
            self.sample if sample is None else sample,
            first_observed_at=self.first_observed_at,
            next_trading_day=self._next_trading_day,
        )

    def _classified_sample(self) -> dict[str, object]:
        sample = json.loads(json.dumps(self.sample, ensure_ascii=False))
        sample["ordinary_classification_evidence"] = json.loads(
            json.dumps(
                self.ordinary_evidence["ordinary_classification_evidence"],
                ensure_ascii=False,
            )
        )
        return sample

    def test_fixture_content_is_pinned_by_sha256(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.fixture_bytes).hexdigest(),
            EXPECTED_FIXTURE_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(self.ordinary_evidence_bytes).hexdigest(),
            EXPECTED_ORDINARY_EVIDENCE_SHA256,
        )

    def test_local_legal_pdf_bytes_match_reviewed_hashes_when_present(self) -> None:
        expected = {
            "spdb-2022-plan.pdf": "3304f19cd12fc66b019017756c4da6c5e12b04de5750ce2d422cb93d048d3a9d",
            "spdb-2022-implementation.pdf": "556db2246673babc2d6dcc996fd3d9dff308b6610b4cd61dfe78baf5c005f17b",
        }
        for filename, digest in expected.items():
            with self.subTest(filename=filename):
                path = LOCAL_ORDINARY_PDF_ROOT / filename
                if path.exists():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_reconciles_cross_source_dates_amount_and_share_basis(self) -> None:
        row = self._normalize()

        self.assertEqual(row["security_id"], "sh.600000")
        self.assertEqual(row["fiscal_period_end"], "2022-12-31")
        self.assertEqual(row["plan_announcement_date"], "2023-04-19")
        self.assertEqual(row["legal_document_date"], "2023-07-12")
        self.assertEqual(
            row["provider_implementation_announcement_date"],
            "2023-07-13",
        )
        self.assertEqual(row["record_date"], "2023-07-20")
        self.assertEqual(row["ex_date"], "2023-07-21")
        self.assertEqual(row["scheduled_payment_date"], "2023-07-21")
        self.assertEqual(row["gross_cash_per_share"], Decimal("0.32"))
        self.assertEqual(row["basis_shares"], 29352175642)
        self.assertEqual(row["gross_cash_total"], Decimal("9392696205.44"))
        self.assertEqual(
            row["calculated_gross_cash_total"],
            row["gross_cash_total"],
        )
        self.assertEqual(row["currency"], "CNY")
        self.assertEqual(row["share_class"], "COMMON")
        self.assertIs(row["differential_distribution"], False)

    def test_uses_legal_announcement_availability_without_backdating(self) -> None:
        row = self._normalize()

        self.assertEqual(row["available_at"], "2023-07-13T00:00:00Z")
        self.assertEqual(
            row["available_at_basis"],
            "next_trading_day_after_legal_document_date",
        )
        self.assertEqual(row["first_observed_at"], "2026-09-25T05:14:54Z")

    def test_v1_does_not_infer_paid_or_ordinary_from_provider_labels(self) -> None:
        row = self._normalize()

        self.assertEqual(row["is_ordinary"], "UNKNOWN")
        self.assertEqual(row["is_paid"], "UNKNOWN")
        self.assertIsNone(row["d_eligible_amount"])
        self.assertIs(row["research_eligible"], False)
        self.assertEqual(
            row["blocking_reasons"],
            [
                "ordinary_classification_unknown",
                "payment_completion_unverified",
                "window_event_coverage_unverified",
            ],
        )

    def test_v2_classifies_only_pinned_annual_legal_pdf_pair(self) -> None:
        row = self._normalize(self._classified_sample())

        self.assertEqual(row["schema_version"], 2)
        self.assertEqual(row["normalization_version"], "dividend_sample_v2_ordinary")
        self.assertEqual(row["is_ordinary"], "TRUE")
        self.assertEqual(
            row["ordinary_status_basis"],
            "rule_spec_v1.2_annual_base_cash_legal_pdf_pair",
        )
        self.assertIn(
            row["ordinary_classification_evidence_ref"], row["evidence_refs"]
        )
        self.assertEqual(row["available_at"], "2023-07-13T00:00:00Z")
        self.assertEqual(row["is_paid"], "UNKNOWN")
        self.assertEqual(
            row["blocking_reasons"],
            ["payment_completion_unverified", "window_event_coverage_unverified"],
        )
        self.assertIsNone(row["d_eligible_amount"])
        self.assertIs(row["research_eligible"], False)

    def test_v2_payment_revision_does_not_unlock_window_aggregate(self) -> None:
        initial, verified = self._normalize_revisions(self._classified_sample())

        self.assertEqual(initial["is_ordinary"], "TRUE")
        self.assertEqual(initial["is_paid"], "UNKNOWN")
        self.assertEqual(verified["is_ordinary"], "TRUE")
        self.assertEqual(verified["is_paid"], "TRUE")
        self.assertEqual(verified["available_at"], "2023-09-01T00:00:00Z")
        self.assertEqual(verified["blocking_reasons"], ["window_event_coverage_unverified"])
        self.assertIsNone(verified["d_eligible_amount"])
        self.assertIs(verified["research_eligible"], False)

    def test_v2_rejects_mismatched_or_unsupported_classification_evidence(self) -> None:
        cases = (
            ("plan_document_sha256", "0" * 64, "identity"),
            ("security_code", "600001", "identity"),
            ("implementation_document_sha256", "0" * 64, "identity"),
            ("plan_available_on", "2023-04-18", "PIT dates"),
            ("special_component_present", True, "not supported"),
            ("annual_base_cash_distribution", False, "not supported"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                sample = self._classified_sample()
                sample["ordinary_classification_evidence"][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self._normalize(sample)

    def test_preserves_independent_source_hashes_and_legal_pdf_hash(self) -> None:
        row = self._normalize()

        self.assertEqual(
            row["legal_document_sha256"],
            "556db2246673babc2d6dcc996fd3d9dff308b6610b4cd61dfe78baf5c005f17b",
        )
        self.assertEqual(
            set(row["source_row_hashes"]),
            {"akshare", "baostock"},
        )
        self.assertTrue(
            all(len(value) == 64 for value in row["source_row_hashes"].values())
        )

    def test_later_issuer_report_verifies_payment_without_backdating(self) -> None:
        initial, verified = self._normalize_revisions()

        self.assertEqual(initial["available_at"], "2023-07-13T00:00:00Z")
        self.assertEqual(initial["is_paid"], "UNKNOWN")
        self.assertEqual(verified["available_at"], "2023-09-01T00:00:00Z")
        self.assertEqual(verified["is_paid"], "TRUE")
        self.assertEqual(
            verified["payment_status_basis"],
            "issuer_periodic_report_explicitly_states_completed",
        )
        self.assertEqual(
            verified["payment_completion_evidence_ref"],
            "cninfo:1217716491:page:54",
        )
        self.assertEqual(
            verified["payment_completion_document_sha256"],
            "fbb1f078f3c845973aefcf5d3fa8cbcc5c978ba86310619dfdb4d0ee9edcfe63",
        )
        self.assertIsNone(verified["d_eligible_amount"])
        self.assertEqual(
            verified["blocking_reasons"],
            [
                "ordinary_classification_unknown",
                "window_event_coverage_unverified",
            ],
        )

    def test_rejects_payment_completion_evidence_that_disagrees(self) -> None:
        cases = (
            ("security", "security_code", "600001"),
            ("payment date", "payment_date", "2023-07-22"),
            ("per-share amount", "gross_cash_per_share", "0.31"),
            ("share basis", "basis_shares", "29352175641"),
            ("total amount", "gross_cash_total", "9392696205.43"),
        )
        for label, field, value in cases:
            with self.subTest(label=label):
                sample = json.loads(json.dumps(self.sample, ensure_ascii=False))
                sample["payment_completion_evidence"][field] = value
                with self.assertRaisesRegex(ValueError, "disagree"):
                    self._normalize_revisions(sample)

    def test_rejects_cross_source_identity_date_and_amount_disagreement(self) -> None:
        cases = (
            ("security", ("baostock", "raw_row", "code"), "sh.600001"),
            (
                "record date",
                ("baostock", "raw_row", "dividRegistDate"),
                "2023-07-19",
            ),
            (
                "per-share amount",
                ("baostock", "raw_row", "dividCashPsBeforeTax"),
                "0.31",
            ),
            (
                "share basis",
                ("legal_announcement", "basis_shares"),
                "29352175641",
            ),
            (
                "total amount",
                ("legal_announcement", "gross_cash_total"),
                "9392696205.43",
            ),
        )
        for label, path, value in cases:
            with self.subTest(label=label):
                sample = json.loads(json.dumps(self.sample, ensure_ascii=False))
                target = sample
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaisesRegex(ValueError, "disagree|total"):
                    self._normalize(sample)

    def test_rejects_missing_fields_bad_hash_and_non_conservative_time(self) -> None:
        missing = json.loads(json.dumps(self.sample, ensure_ascii=False))
        del missing["akshare"]["raw_row"]["总股本"]
        with self.assertRaisesRegex(ValueError, "missing"):
            self._normalize(missing)

        bad_hash = json.loads(json.dumps(self.sample, ensure_ascii=False))
        bad_hash["legal_announcement"]["sha256"] = "not-a-hash"
        with self.assertRaisesRegex(ValueError, "sha256"):
            self._normalize(bad_hash)

        with self.assertRaisesRegex(ValueError, "timezone"):
            normalize_dividend_sample(
                self.sample,
                first_observed_at=datetime(2026, 9, 25, 5, 14, 54),
                next_trading_day=self._next_trading_day,
            )

        with self.assertRaisesRegex(ValueError, "next trading day"):
            normalize_dividend_sample(
                self.sample,
                first_observed_at=self.first_observed_at,
                next_trading_day=lambda announced_on: announced_on,
            )


if __name__ == "__main__":
    unittest.main()
