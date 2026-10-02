from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from turtle_quant.adapters.financial_statement_samples import (
    FINANCIAL_SAMPLE_FIELD_MATRICES,
    FinancialStatementObservation,
    build_sample_observation_revision_chain,
    normalize_financial_statement_sample,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "financials"
    / "eastmoney-financial-statement-samples-v1.json"
)
EXPECTED_FIXTURE_SHA256 = (
    "9850b85e2cf9f51b2b5180892b23e2f905655ad8eccea3084ed4eb3e07f76f63"
)


class FinancialStatementSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_bytes = FIXTURE_PATH.read_bytes()
        cls.fixture = json.loads(cls.fixture_bytes.decode("utf-8"))
        cls.first_observed_at = datetime.fromisoformat(
            cls.fixture["captured_at_utc"].replace("Z", "+00:00")
        )

    @staticmethod
    def _next_trading_day(announced_on: date) -> date:
        known = {
            date(2026, 3, 31): date(2026, 4, 1),
            date(2026, 4, 17): date(2026, 4, 20),
            date(2009, 10, 31): date(2009, 11, 2),
        }
        return known[announced_on]

    def _normalize(self, sample: dict[str, object]) -> tuple[dict[str, object], ...]:
        return normalize_financial_statement_sample(
            sample["raw_row"],
            source_interface=str(sample["source_interface"]),
            statement_type=str(sample["statement_type"]),
            first_observed_at=self.first_observed_at,
            next_trading_day=self._next_trading_day,
            statement_scope=str(
                sample.get(
                    "statement_scope",
                    self.fixture["default_statement_scope"],
                )
            ),
            scope_evidence_ref=sample.get("scope_evidence_ref"),
        )

    def test_fixture_content_is_pinned_by_sha256(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.fixture_bytes).hexdigest(),
            EXPECTED_FIXTURE_SHA256,
        )

    def test_maps_all_fixed_samples_with_interface_specific_matrices(self) -> None:
        total_rows = 0
        for sample in self.fixture["samples"]:
            with self.subTest(source_interface=sample["source_interface"]):
                rows = self._normalize(sample)
                total_rows += len(rows)
                self.assertEqual(len(rows), sample["expected_line_item_count"])
                self.assertTrue(all(row["research_eligible"] is False for row in rows))
                expected_scope = str(
                    sample.get(
                        "statement_scope",
                        self.fixture["default_statement_scope"],
                    )
                )
                self.assertTrue(
                    all(
                        row["statement_scope"] == expected_scope
                        for row in rows
                    )
                )
                self.assertTrue(
                    all(
                        row["revision_status"]
                        == "financials:latest_restated_only"
                        for row in rows
                    )
                )
                self.assertTrue(
                    all(row["provider_revision_sequence"] is None for row in rows)
                )
                expected_blockers = [
                    "provider_revision_sequence_unavailable"
                ]
                if expected_scope == "UNKNOWN":
                    expected_blockers.insert(0, "statement_scope_unknown")
                self.assertTrue(
                    all(
                        row["blocking_reasons"] == expected_blockers
                        for row in rows
                    )
                )
                self.assertTrue(
                    all(
                        row["value"] is None
                        or isinstance(row["value"], Decimal)
                        for row in rows
                    )
                )
                self.assertTrue(
                    all(
                        isinstance(row["source_row_hash"], str)
                        and len(row["source_row_hash"]) == 64
                        for row in rows
                    )
                )
        self.assertEqual(total_rows, 52)
        self.assertEqual(len(FINANCIAL_SAMPLE_FIELD_MATRICES), 9)

    def test_every_fixed_sample_has_legal_statement_scope_evidence(self) -> None:
        expected_scopes = {
            "600000": "CONSOLIDATED",
            "600001": "PARENT",
            "600519": "CONSOLIDATED",
        }
        for sample in self.fixture["samples"]:
            security_code = sample["raw_row"]["SECURITY_CODE"]
            with self.subTest(
                security_code=security_code,
                statement_type=sample["statement_type"],
            ):
                self.assertEqual(
                    sample.get("statement_scope"),
                    expected_scopes[security_code],
                )
                self.assertIsInstance(sample.get("scope_evidence_ref"), str)
                self.assertTrue(sample["scope_evidence_ref"].strip())
                rows = self._normalize(sample)
                self.assertTrue(
                    all(
                        row["blocking_reasons"]
                        == ["provider_revision_sequence_unavailable"]
                        for row in rows
                    )
                )

    def test_listed_general_sample_preserves_fcf_candidate_source_items(
        self,
    ) -> None:
        samples = {
            (sample["request"].get("code"), sample["statement_type"]): sample
            for sample in self.fixture["samples"]
            if "code" in sample["request"]
        }
        balance = self._normalize(samples[("SH600519", "balance_sheet")])
        cash_flow = self._normalize(
            samples[("SH600519", "cash_flow_statement")]
        )
        balance_by_item = {row["item_code"]: row for row in balance}
        cash_flow_by_item = {row["item_code"]: row for row in cash_flow}

        self.assertEqual(
            balance_by_item["MONETARYFUNDS"]["value"],
            Decimal("51690610946.5"),
        )
        self.assertIsNone(balance_by_item["SHORT_LOAN"]["value"])
        self.assertEqual(
            balance_by_item["SHORT_LOAN"]["value_status"], "UNKNOWN"
        )
        self.assertEqual(
            cash_flow_by_item["CONSTRUCT_LONG_ASSET"]["value"],
            Decimal("3127594916.41"),
        )
        self.assertTrue(
            all(row["organization_type"] == "general" for row in balance)
        )
        self.assertTrue(
            all(row["statement_scope"] == "CONSOLIDATED" for row in balance)
        )
        self.assertTrue(
            all(
                row["statement_scope_evidence_ref"]
                == "cninfo:1225114741:page:56"
                for row in balance
            )
        )
        self.assertTrue(
            all(row["research_eligible"] is False for row in cash_flow)
        )

    def test_scope_claim_requires_explicit_evidence(self) -> None:
        sample = self.fixture["samples"][0]
        arguments = {
            "source_interface": str(sample["source_interface"]),
            "statement_type": str(sample["statement_type"]),
            "first_observed_at": self.first_observed_at,
            "next_trading_day": self._next_trading_day,
        }
        with self.assertRaisesRegex(ValueError, "scope_evidence_ref"):
            normalize_financial_statement_sample(
                sample["raw_row"],
                statement_scope="CONSOLIDATED",
                **arguments,
            )
        with self.assertRaisesRegex(ValueError, "statement_scope"):
            normalize_financial_statement_sample(
                sample["raw_row"],
                statement_scope="GUESSED",
                scope_evidence_ref="unsupported",
                **arguments,
            )

    def test_latest_restated_value_is_not_backdated_to_notice_date(self) -> None:
        sample = self.fixture["samples"][0]
        rows = self._normalize(sample)
        row = rows[0]
        self.assertEqual(row["announcement_date"], "2026-03-31")
        self.assertEqual(
            row["candidate_announcement_available_date"], "2026-04-01"
        )
        self.assertEqual(row["available_at"], "2026-09-25T04:09:31Z")
        self.assertEqual(row["source_update_date"], "2026-08-28")

    def test_missing_accounting_value_stays_unknown_instead_of_zero(self) -> None:
        sample = self.fixture["samples"][0]
        raw_row = dict(sample["raw_row"])
        raw_row["TOTAL_ASSETS"] = None
        rows = normalize_financial_statement_sample(
            raw_row,
            source_interface=str(sample["source_interface"]),
            statement_type=str(sample["statement_type"]),
            first_observed_at=self.first_observed_at,
            next_trading_day=self._next_trading_day,
        )
        total_assets = next(
            row for row in rows if row["item_code"] == "TOTAL_ASSETS"
        )
        self.assertIsNone(total_assets["value"])
        self.assertEqual(total_assets["value_status"], "UNKNOWN")

    def test_rejects_security_identity_disagreement(self) -> None:
        sample = self.fixture["samples"][0]
        raw_row = dict(sample["raw_row"])
        raw_row["SECURITY_CODE"] = "600001"
        with self.assertRaisesRegex(ValueError, "SECURITY_CODE"):
            normalize_financial_statement_sample(
                raw_row,
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=self.first_observed_at,
                next_trading_day=self._next_trading_day,
            )

    def test_rejects_incomplete_field_matrix(self) -> None:
        sample = self.fixture["samples"][1]
        raw_row = dict(sample["raw_row"])
        del raw_row["PARENT_NETPROFIT"]
        with self.assertRaisesRegex(ValueError, "field matrix"):
            normalize_financial_statement_sample(
                raw_row,
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=self.first_observed_at,
                next_trading_day=self._next_trading_day,
            )

    def test_rejects_naive_first_observed_time(self) -> None:
        sample = self.fixture["samples"][0]
        with self.assertRaisesRegex(ValueError, "timezone"):
            normalize_financial_statement_sample(
                sample["raw_row"],
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=datetime(2026, 9, 25, 4, 9, 31),
                next_trading_day=self._next_trading_day,
            )


    def test_rejects_non_conservative_announcement_availability(self) -> None:
        sample = self.fixture["samples"][0]
        with self.assertRaisesRegex(ValueError, "next trading day"):
            normalize_financial_statement_sample(
                sample["raw_row"],
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=self.first_observed_at,
                next_trading_day=lambda announced_on: announced_on,
            )

    def test_rejects_unsupported_input_contracts(self) -> None:
        sample = self.fixture["samples"][0]
        cases = (
            (
                "not a mapping",
                lambda: normalize_financial_statement_sample(
                    [],
                    source_interface=str(sample["source_interface"]),
                    statement_type=str(sample["statement_type"]),
                    first_observed_at=self.first_observed_at,
                    next_trading_day=self._next_trading_day,
                ),
                TypeError,
                "mapping",
            ),
            (
                "unknown interface",
                lambda: normalize_financial_statement_sample(
                    sample["raw_row"],
                    source_interface="unknown_interface",
                    statement_type=str(sample["statement_type"]),
                    first_observed_at=self.first_observed_at,
                    next_trading_day=self._next_trading_day,
                ),
                ValueError,
                "unsupported financial sample interface",
            ),
            (
                "interface and statement mismatch",
                lambda: normalize_financial_statement_sample(
                    sample["raw_row"],
                    source_interface=str(sample["source_interface"]),
                    statement_type="income_statement",
                    first_observed_at=self.first_observed_at,
                    next_trading_day=self._next_trading_day,
                ),
                ValueError,
                "statement_type",
            ),
        )
        for label, operation, error_type, message in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(error_type, message):
                    operation()

    def test_rejects_missing_metadata_and_unknown_company_matrix(self) -> None:
        sample = self.fixture["samples"][0]
        missing_metadata = dict(sample["raw_row"])
        del missing_metadata["CURRENCY"]
        with self.assertRaisesRegex(ValueError, "metadata fields"):
            normalize_financial_statement_sample(
                missing_metadata,
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=self.first_observed_at,
                next_trading_day=self._next_trading_day,
            )

        unknown_company = dict(sample["raw_row"])
        unknown_company["ORG_TYPE"] = "保险"
        with self.assertRaisesRegex(ValueError, "ORG_TYPE"):
            normalize_financial_statement_sample(
                unknown_company,
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=self.first_observed_at,
                next_trading_day=self._next_trading_day,
            )


    @staticmethod
    def _observation(
        observed_at: datetime,
        source_row_hash: str,
        snapshot_id: str,
        statement_scope: str = "UNKNOWN",
    ) -> FinancialStatementObservation:
        return FinancialStatementObservation(
            source_interface="stock_balance_sheet_by_report_em",
            security_id="sh.600519",
            statement_type="balance_sheet",
            period_end=date(2025, 12, 31),
            observed_at=observed_at,
            source_row_hash=source_row_hash,
            snapshot_id=snapshot_id,
            statement_scope=statement_scope,
        )

    def test_builds_deterministic_forward_only_revision_episodes(self) -> None:
        observations = (
            self._observation(
                datetime(2026, 9, 28, tzinfo=timezone.utc),
                "a" * 64,
                "sample-4",
            ),
            self._observation(
                datetime(2026, 9, 25, tzinfo=timezone.utc),
                "a" * 64,
                "sample-1",
            ),
            self._observation(
                datetime(2026, 9, 27, tzinfo=timezone.utc),
                "b" * 64,
                "sample-3",
            ),
            self._observation(
                datetime(2026, 9, 26, tzinfo=timezone.utc),
                "a" * 64,
                "sample-2",
            ),
        )
        revisions = build_sample_observation_revision_chain(observations)
        reversed_revisions = build_sample_observation_revision_chain(
            reversed(observations)
        )

        self.assertEqual(revisions, reversed_revisions)
        self.assertEqual(
            [row.observation_revision_sequence for row in revisions],
            [1, 2, 3],
        )
        self.assertEqual(
            [row.source_row_hash for row in revisions],
            ["a" * 64, "b" * 64, "a" * 64],
        )
        self.assertEqual(
            revisions[0].available_at,
            datetime(2026, 9, 25, tzinfo=timezone.utc),
        )
        self.assertEqual(
            revisions[0].last_observed_at,
            datetime(2026, 9, 26, tzinfo=timezone.utc),
        )
        self.assertEqual(revisions[0].snapshot_ids, ("sample-1", "sample-2"))
        self.assertTrue(
            all(row.provider_revision_sequence is None for row in revisions)
        )
        self.assertTrue(
            all(
                row.revision_status == "financials:observed_forward_only"
                for row in revisions
            )
        )

    def test_collapses_same_timestamp_same_content_across_snapshots(self) -> None:
        timestamp = datetime(2026, 9, 25, tzinfo=timezone.utc)
        revisions = build_sample_observation_revision_chain(
            (
                self._observation(timestamp, "a" * 64, "sample-b"),
                self._observation(timestamp, "a" * 64, "sample-a"),
            )
        )
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].snapshot_ids, ("sample-a", "sample-b"))

    def test_revision_chain_keeps_statement_scopes_separate(self) -> None:
        timestamp = datetime(2026, 9, 25, tzinfo=timezone.utc)
        revisions = build_sample_observation_revision_chain(
            (
                self._observation(
                    timestamp,
                    "a" * 64,
                    "consolidated",
                    "CONSOLIDATED",
                ),
                self._observation(
                    timestamp,
                    "b" * 64,
                    "parent",
                    "PARENT",
                ),
            )
        )
        self.assertEqual(len(revisions), 2)
        self.assertEqual(
            {row.statement_scope for row in revisions},
            {"CONSOLIDATED", "PARENT"},
        )
        self.assertTrue(
            all(row.observation_revision_sequence == 1 for row in revisions)
        )

    def test_rejects_conflicting_content_at_same_observation_time(self) -> None:
        timestamp = datetime(2026, 9, 25, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "ambiguous observed revision"):
            build_sample_observation_revision_chain(
                (
                    self._observation(timestamp, "a" * 64, "sample-a"),
                    self._observation(timestamp, "b" * 64, "sample-b"),
                )
            )

    def test_observation_contract_rejects_invalid_identity_and_time(self) -> None:
        valid = {
            "source_interface": "stock_balance_sheet_by_report_em",
            "security_id": "sh.600519",
            "statement_type": "balance_sheet",
            "period_end": date(2025, 12, 31),
            "observed_at": datetime(2026, 9, 25, tzinfo=timezone.utc),
            "source_row_hash": "a" * 64,
            "snapshot_id": "sample-a",
        }
        cases = (
            ("observed_at", datetime(2026, 9, 25), "timezone"),
            ("source_row_hash", "not-a-hash", "source_row_hash"),
            ("snapshot_id", "../escape", "snapshot_id"),
            ("security_id", "600519", "normalized"),
            ("statement_type", "income_statement", "statement_type"),
            ("statement_scope", "GUESSED", "statement_scope"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                inputs = dict(valid)
                inputs[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    FinancialStatementObservation(**inputs)

    def test_rejects_impossible_dates_report_type_and_currency(self) -> None:
        sample = self.fixture["samples"][0]
        cases = (
            ("NOTICE_DATE", None, "must contain a provider date"),
            ("NOTICE_DATE", "not-a-date", "invalid NOTICE_DATE"),
            ("NOTICE_DATE", "2025-01-01", "cannot precede REPORT_DATE"),
            ("UPDATE_DATE", "2026-01-01", "cannot precede NOTICE_DATE"),
            ("REPORT_TYPE", "未知", "unsupported REPORT_TYPE"),
            ("REPORT_DATE", "2025-11-30", "disagrees with REPORT_DATE"),
            ("CURRENCY", "人民币", "invalid CURRENCY"),
        )
        for field, value, message in cases:
            with self.subTest(field=field, value=value):
                raw_row = dict(sample["raw_row"])
                raw_row[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    normalize_financial_statement_sample(
                        raw_row,
                        source_interface=str(sample["source_interface"]),
                        statement_type=str(sample["statement_type"]),
                        first_observed_at=self.first_observed_at,
                        next_trading_day=self._next_trading_day,
                    )

    def test_decimal_boundary_preserves_nan_as_unknown_and_rejects_bad_values(
        self,
    ) -> None:
        sample = self.fixture["samples"][0]
        raw_nan = dict(sample["raw_row"])
        raw_nan["TOTAL_ASSETS"] = float("nan")
        rows = normalize_financial_statement_sample(
            raw_nan,
            source_interface=str(sample["source_interface"]),
            statement_type=str(sample["statement_type"]),
            first_observed_at=self.first_observed_at,
            next_trading_day=self._next_trading_day,
        )
        total_assets = next(
            row for row in rows if row["item_code"] == "TOTAL_ASSETS"
        )
        self.assertIsNone(total_assets["value"])

        for value in (True, float("inf"), "not-a-number", "NaN"):
            with self.subTest(value=value):
                raw_row = dict(sample["raw_row"])
                raw_row["TOTAL_ASSETS"] = value
                with self.assertRaisesRegex(ValueError, "TOTAL_ASSETS"):
                    normalize_financial_statement_sample(
                        raw_row,
                        source_interface=str(sample["source_interface"]),
                        statement_type=str(sample["statement_type"]),
                        first_observed_at=self.first_observed_at,
                        next_trading_day=self._next_trading_day,
                    )

    def test_rejects_invalid_observation_and_calendar_types(self) -> None:
        sample = self.fixture["samples"][0]
        with self.assertRaisesRegex(TypeError, "datetime"):
            normalize_financial_statement_sample(
                sample["raw_row"],
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=date(2026, 9, 25),  # type: ignore[arg-type]
                next_trading_day=self._next_trading_day,
            )
        with self.assertRaisesRegex(ValueError, "return a date"):
            normalize_financial_statement_sample(
                sample["raw_row"],
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=self.first_observed_at,
                next_trading_day=lambda _announced_on: datetime(
                    2026, 4, 1, tzinfo=timezone.utc
                ),  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(ValueError, "first_observed_at cannot precede"):
            normalize_financial_statement_sample(
                sample["raw_row"],
                source_interface=str(sample["source_interface"]),
                statement_type=str(sample["statement_type"]),
                first_observed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                next_trading_day=self._next_trading_day,
            )


if __name__ == "__main__":
    unittest.main()
