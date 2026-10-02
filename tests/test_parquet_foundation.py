from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pyarrow.parquet as pq

from turtle_quant.core.market_data import CoverageIssueType, cumulative_factor_on
from turtle_quant.pit.parquet_foundation import (
    ParquetDataIntegrityError,
    ParquetFoundationReader,
    ParquetSchemaError,
    SnapshotCoverageError,
)
from turtle_quant.storage import DomainRevokedError, IngestConfig, SnapshotSession
from turtle_quant.storage.parquet import write_parquet_rows


D = Decimal
START = date(2024, 1, 1)
END = date(2024, 1, 10)


class FoundationSnapshotFixture:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _config(steps: tuple[str, ...]) -> IngestConfig:
        return IngestConfig(
            ingest_calendar_date=END,
            steps=steps,
            start_date=START,
            end_date=END,
            max_symbols=None,
            board_filter_version="main_board_v1",
            source_provenance_template={"fixture": {"version": "1"}},
        )

    @staticmethod
    def _evidence(prefix: str, key: str) -> tuple[str, str]:
        return f"fixture:{prefix}:{key}", (key.encode("utf-8").hex() + "0" * 64)[:64]

    def publish_primary(
        self,
        *,
        market_schema_version: int = 1,
        factor_conflict: bool = False,
    ) -> str:
        session = SnapshotSession.start(
            self.root,
            self._config(
                ("security_master", "market_daily", "adjustment_factors")
            ),
        )
        security_path = session.staging_path / "security_master" / "part.parquet"
        security_rows = []
        for security_id, listing, delisting in (
            ("sh.600000", "1999-11-10", None),
            ("sh.600001", "1998-01-22", None),
            ("sh.600002", "1998-01-22", "2024-01-03"),
            ("sh.600010", "2001-01-01", None),
        ):
            evidence, row_hash = self._evidence("security", security_id)
            security_rows.append(
                {
                    "security_id": security_id,
                    "raw_code": security_id.split(".")[1],
                    "vendor_symbol": security_id,
                    "exchange": "sh",
                    "display_name": security_id,
                    "board": "main_board",
                    "board_effective_from": listing,
                    "board_effective_to": delisting,
                    "listing_date": listing,
                    "delisting_date": delisting,
                    "delisting_date_semantics": "provider_out_date",
                    "provider_status": "1",
                    "schema_version": 1,
                    "normalization_version": "cn_equity_v1",
                    "source_name": "fixture",
                    "source_row_hash": row_hash,
                    "evidence_ref": evidence,
                    "stockdb_present": True,
                    "stockdb_delisted_table": False,
                }
            )
        write_parquet_rows(
            security_path,
            security_rows,
            sort_keys=("security_id", "board_effective_from"),
        )
        session.complete_domain(
            "security_master",
            files=(security_path,),
            row_count=len(security_rows),
            quality_flags=("security_master:fixture:information",),
        )

        market_path = (
            session.staging_path / "market" / "raw_daily" / "part-60000.parquet"
        )
        market_rows = []
        for day, paused, evidence_missing in (
            (date(2024, 1, 2), False, False),
            (date(2024, 1, 3), None, False),
            (date(2024, 1, 5), False, True),
            (date(2024, 1, 8), False, False),
            (date(2024, 1, 9), False, False),
            (date(2024, 1, 10), False, False),
        ):
            key = day.isoformat()
            evidence, row_hash = self._evidence("bar", key)
            market_rows.append(
                {
                    "security_id": "sh.600000",
                    "trade_date": key,
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "volume": "100",
                    "amount": "1050",
                    "paused": paused,
                    "pause_status_source": (
                        "provider" if paused is not None else "unknown"
                    ),
                    "adjust_type": "RAW",
                    "schema_version": market_schema_version,
                    "normalization_version": "market_raw_v1",
                    "source_name": "fixture",
                    "source_row_hash": None if evidence_missing else row_hash,
                    "evidence_ref": None if evidence_missing else evidence,
                }
            )
        write_parquet_rows(
            market_path,
            market_rows,
            sort_keys=("security_id", "trade_date"),
        )
        unrelated_path = (
            session.staging_path / "market" / "raw_daily" / "part-60001.parquet"
        )
        evidence, row_hash = self._evidence("bar", "unrelated")
        write_parquet_rows(
            unrelated_path,
            [
                {
                    **market_rows[0],
                    "security_id": "sh.600010",
                    "evidence_ref": evidence,
                    "source_row_hash": row_hash,
                }
            ],
            sort_keys=("security_id", "trade_date"),
        )
        empty_path = (
            session.staging_path / "market" / "raw_daily" / "part-60002.parquet"
        )
        write_parquet_rows(empty_path, [], sort_keys=("security_id", "trade_date"))
        session.complete_domain(
            "market_daily",
            files=(market_path, unrelated_path, empty_path),
            row_count=len(market_rows) + 1,
            quality_flags=("market_daily:fixture:warning",),
            details={
                "security_coverage": "0.6666666667",
                "missing_security_ids": ["sh.600001"],
            },
        )

        factor_path = (
            session.staging_path
            / "corporate_actions"
            / "adjustment_factors"
            / "part.parquet"
        )
        factor_rows = []
        for ex_date, available_at, factor, suffix in (
            ("2023-12-01", "2023-12-01", "1", "base"),
            ("2024-01-03", "2024-01-03", "2", "v1"),
            ("2024-01-03", "2024-01-05", "2.1", "v2"),
        ):
            evidence, row_hash = self._evidence("factor", suffix)
            factor_rows.append(
                {
                    "security_id": "sh.600000",
                    "ex_date": ex_date,
                    "factor": factor,
                    "factor_source": "stockdb_cum",
                    "available_at": available_at,
                    "schema_version": 1,
                    "normalization_version": "adjustment_factor_v1",
                    "source_name": "fixture",
                    "source_row_hash": row_hash,
                    "evidence_ref": evidence,
                }
            )
        if factor_conflict:
            conflict = dict(factor_rows[1])
            conflict["factor"] = "3"
            conflict["source_row_hash"] = "f" * 64
            conflict["evidence_ref"] = "fixture:factor:conflict"
            factor_rows.append(conflict)
        write_parquet_rows(
            factor_path,
            factor_rows,
            sort_keys=("security_id", "ex_date", "available_at"),
        )
        session.complete_domain(
            "adjustment_factors",
            files=(factor_path,),
            row_count=len(factor_rows),
        )
        return session.publish(
            universe_hash="1111111111111111",
            source_descriptors={"fixture": {"version": "1"}},
        )

    def publish_auxiliary(
        self,
        *,
        omit_calendar_day: date | None = None,
        rate_normalization: str = "chinabond_10y_v1",
        rate_observations: tuple[tuple[str, str, str], ...] | None = None,
        closed_days: frozenset[date] = frozenset(),
    ) -> str:
        session = SnapshotSession.start(
            self.root,
            self._config(("calendar", "chinabond_10y")),
        )
        calendar_path = session.staging_path / "calendar" / "trade_dates.parquet"
        calendar_rows = []
        cursor = START
        while cursor <= END + timedelta(days=10):
            if cursor != omit_calendar_day:
                evidence, row_hash = self._evidence("calendar", cursor.isoformat())
                calendar_rows.append(
                    {
                        "exchange": "cn",
                        "date": cursor.isoformat(),
                        "is_trading_day": (
                            cursor.weekday() < 5
                            and cursor != START
                            and cursor not in closed_days
                        ),
                        "schema_version": 1,
                        "normalization_version": "cn_calendar_v1",
                        "source_name": "fixture",
                        "source_row_hash": row_hash,
                        "evidence_ref": evidence,
                    }
                )
            cursor += timedelta(days=1)
        write_parquet_rows(calendar_path, calendar_rows, sort_keys=("date",))
        session.complete_domain(
            "calendar", files=(calendar_path,), row_count=len(calendar_rows)
        )

        rate_path = (
            session.staging_path / "macro" / "cn_yield_10y" / "daily.parquet"
        )
        rate_rows = []
        selected_rates = rate_observations or (
            ("2024-01-02", "2024-01-03", "2.5"),
            ("2024-01-03", "2024-01-04", "2.6"),
            ("2024-01-05", "2024-01-08", "2.7"),
        )
        for obs_date, available_at, value in selected_rates:
            evidence, row_hash = self._evidence("rate", obs_date)
            rate_rows.append(
                {
                    "obs_date": obs_date,
                    "yield_10y_pct": value,
                    "curve_id": "ycqx",
                    "curve_name": "中债国债收益率曲线",
                    "tenor": "10Y",
                    "available_at": available_at,
                    "schema_version": 1,
                    "normalization_version": rate_normalization,
                    "source_name": "fixture",
                    "evidence_ref": evidence,
                    "source_row_hash": row_hash,
                }
            )
        write_parquet_rows(rate_path, rate_rows, sort_keys=("obs_date",))
        session.complete_domain(
            "chinabond_10y",
            files=(rate_path,),
            row_count=len(rate_rows),
            quality_flags=("chinabond_10y:fixture:warning",),
        )
        return session.publish(
            universe_hash="2222222222222222",
            source_descriptors={"fixture": {"version": "1"}},
        )

    def write_catalog(self, revocations: dict[str, object] | None = None) -> None:
        path = self.root / "catalog" / "domain-revocations.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"schema_version": 1, "revocations": revocations or {}},
                sort_keys=True,
            ),
            encoding="utf-8",
        )


class ParquetFoundationReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = FoundationSnapshotFixture(self.root)
        self.primary_id = self.fixture.publish_primary()
        self.auxiliary_id = self.fixture.publish_auxiliary()
        self.fixture.write_catalog()

    def _reader(self) -> ParquetFoundationReader:
        return ParquetFoundationReader(
            self.root,
            security_master_snapshot_id=self.primary_id,
            market_daily_snapshot_id=self.primary_id,
            adjustment_factors_snapshot_id=self.primary_id,
            calendar_snapshot_id=self.auxiliary_id,
            rate_snapshot_id=self.auxiliary_id,
        )

    def test_constructs_only_from_explicit_verified_cohorts(self) -> None:
        reader = self._reader()

        self.assertEqual(
            reader.snapshot_ids,
            tuple(sorted((self.primary_id, self.auxiliary_id))),
        )
        self.assertEqual(reader.universe_hash, "1111111111111111")
        self.assertIn("market_daily:fixture:warning", reader.data_quality_flags)
        self.assertIn("chinabond_10y:fixture:warning", reader.data_quality_flags)
        with self.assertRaisesRegex(ValueError, "same snapshot"):
            ParquetFoundationReader(
                self.root,
                security_master_snapshot_id=self.primary_id,
                market_daily_snapshot_id=self.auxiliary_id,
                adjustment_factors_snapshot_id=self.primary_id,
                calendar_snapshot_id=self.auxiliary_id,
                rate_snapshot_id=self.auxiliary_id,
            )

    def test_security_universe_uses_historical_inclusive_intervals(self) -> None:
        reader = self._reader()

        self.assertEqual(
            reader.security_ids_as_of(date(2024, 1, 2)),
            ("sh.600000", "sh.600001", "sh.600002", "sh.600010"),
        )
        self.assertIn("sh.600002", reader.security_ids_as_of(date(2024, 1, 3)))
        self.assertNotIn("sh.600002", reader.security_ids_as_of(date(2024, 1, 4)))

    def test_price_bars_return_structured_local_coverage_issues(self) -> None:
        result = self._reader().price_bars(
            "sh.600000", date(2024, 1, 2), date(2024, 1, 5), as_of=date(2024, 1, 5)
        )

        self.assertEqual(
            tuple(bar.trade_date for bar in result.bars),
            (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 5)),
        )
        self.assertEqual(
            tuple(issue.issue_type for issue in result.coverage_issues),
            (
                CoverageIssueType.PAUSE_STATUS_UNKNOWN,
                CoverageIssueType.MISSING_BAR,
                CoverageIssueType.EVIDENCE_MISSING,
            ),
        )
        self.assertEqual(
            result.coverage_issues[1].date_range,
            (date(2024, 1, 4), date(2024, 1, 4)),
        )
        self.assertFalse(result.coverage_complete)
        self.assertIsNone(result.bars[-1].evidence_ref)
        self.assertTrue(
            self._reader()
            .price_bars(
                "sh.600000",
                date(2024, 1, 2),
                date(2024, 1, 2),
                as_of=date(2024, 1, 2),
            )
            .coverage_complete
        )

    def test_missing_security_is_not_misreported_as_empty_complete_data(self) -> None:
        result = self._reader().price_bars(
            "sh.600001", date(2024, 1, 2), date(2024, 1, 5), as_of=date(2024, 1, 5)
        )

        self.assertEqual(result.bars, ())
        self.assertEqual(len(result.coverage_issues), 1)
        self.assertEqual(
            result.coverage_issues[0].issue_type,
            CoverageIssueType.SECURITY_NOT_COVERED,
        )
        self.assertEqual(
            result.coverage_issues[0].date_range,
            (date(2024, 1, 2), date(2024, 1, 5)),
        )

    def test_market_query_uses_the_security_shard_and_parquet_filters(self) -> None:
        reader = self._reader()
        original = pq.read_table
        with patch("pyarrow.parquet.read_table", wraps=original) as read_table:
            reader.price_bars(
                "sh.600000",
                date(2024, 1, 2),
                date(2024, 1, 2),
                as_of=date(2024, 1, 2),
            )

        market_calls = [
            call
            for call in read_table.call_args_list
            if "raw_daily" in str(call.args[0])
        ]
        self.assertEqual(len(market_calls), 1)
        self.assertTrue(str(market_calls[0].args[0]).endswith("part-60000.parquet"))
        self.assertTrue(market_calls[0].kwargs["filters"])
        self.assertIn("columns", market_calls[0].kwargs)

    def test_factor_reader_preserves_baseline_and_visible_revisions(self) -> None:
        reader = self._reader()
        observations = reader.adjustment_factor_series(
            "sh.600000",
            date(2024, 1, 2),
            date(2024, 1, 5),
            as_of=date(2024, 1, 5),
        )

        self.assertEqual(
            tuple(item.cumulative_factor for item in observations),
            (D("1"), D("2"), D("2.1")),
        )
        self.assertEqual(
            cumulative_factor_on(
                observations,
                security_id="sh.600000",
                day=date(2024, 1, 3),
                as_of=date(2024, 1, 5),
            ),
            D("2.1"),
        )
        earlier = reader.adjustment_factor_series(
            "sh.600000",
            date(2024, 1, 2),
            date(2024, 1, 5),
            as_of=date(2024, 1, 4),
        )
        self.assertEqual(
            tuple(item.cumulative_factor for item in earlier),
            (D("1"), D("2")),
        )

    def test_rate_staleness_counts_only_open_interval_trading_days(self) -> None:
        reader = self._reader()

        monday = reader.value_on(
            "CN_GOVT_10Y_YIELD_PCT", as_of=date(2024, 1, 8)
        )
        self.assertIsNotNone(monday)
        assert monday is not None
        self.assertEqual(monday.obs_date, date(2024, 1, 5))
        self.assertEqual(monday.value.value, D("2.7"))
        self.assertIsNone(
            reader.value_on(
                "CN_GOVT_10Y_YIELD_PCT", as_of=date(2024, 1, 10)
            )
        )
        self.assertIsNone(
            reader.value_on(
                "CN_GOVT_10Y_YIELD_PCT", as_of=date(2024, 1, 2)
            )
        )
        with self.assertRaisesRegex(ValueError, "unknown rate series"):
            reader.value_on("CGB10Y", as_of=date(2024, 1, 8))

    def test_rate_examples_distinguish_weekend_prior_day_and_long_holiday(self) -> None:
        cases = (
            (
                "friday_to_monday",
                (("2024-01-05", "2024-01-05", "2.7"),),
                frozenset(),
                True,
            ),
            (
                "thursday_to_monday",
                (("2024-01-04", "2024-01-04", "2.6"),),
                frozenset(),
                False,
            ),
            (
                "long_holiday",
                (("2024-01-01", "2024-01-01", "2.5"),),
                frozenset(
                    {
                        date(2024, 1, 2),
                        date(2024, 1, 3),
                        date(2024, 1, 4),
                        date(2024, 1, 5),
                    }
                ),
                True,
            ),
        )
        for label, rates, closed_days, expected_visible in cases:
            with self.subTest(label=label), TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = FoundationSnapshotFixture(root)
                primary = fixture.publish_primary()
                auxiliary = fixture.publish_auxiliary(
                    rate_observations=rates,
                    closed_days=closed_days,
                )
                fixture.write_catalog()
                reader = ParquetFoundationReader(
                    root,
                    security_master_snapshot_id=primary,
                    market_daily_snapshot_id=primary,
                    adjustment_factors_snapshot_id=primary,
                    calendar_snapshot_id=auxiliary,
                    rate_snapshot_id=auxiliary,
                )
                observation = reader.value_on(
                    "CN_GOVT_10Y_YIELD_PCT", as_of=date(2024, 1, 8)
                )
                self.assertEqual(observation is not None, expected_visible)

    def test_calendar_buffer_is_only_available_for_end_date_next_day(self) -> None:
        reader = self._reader()

        self.assertFalse(reader.calendar_day("cn", date(2024, 1, 6)))
        self.assertEqual(
            reader.previous_trading_day("cn", date(2024, 1, 10)),
            date(2024, 1, 9),
        )
        self.assertEqual(
            reader.next_trading_day("cn", END),
            date(2024, 1, 11),
        )
        with self.assertRaisesRegex(ValueError, "exchange"):
            reader.calendar_day("sh", date(2024, 1, 2))
        with self.assertRaises(SnapshotCoverageError):
            reader.calendar_day("cn", date(2024, 1, 11))
        with self.assertRaises(SnapshotCoverageError):
            reader.next_trading_day("cn", date(2024, 1, 11))

    def test_research_queries_fail_closed_outside_snapshot_coverage(self) -> None:
        reader = self._reader()

        with self.assertRaises(SnapshotCoverageError):
            reader.price_bars(
                "sh.600000",
                date(2023, 12, 31),
                date(2024, 1, 2),
                as_of=date(2024, 1, 2),
            )
        with self.assertRaisesRegex(ValueError, "canonical"):
            reader.price_bars(
                "600000.SH", START, START, as_of=START
            )

    def test_build_manifest_uses_all_selected_snapshot_evidence(self) -> None:
        manifest = self._reader().build_run_manifest(
            run_id="fixture-run",
            as_of=date(2024, 1, 8),
            code_version="fixture-code",
            config_hash="f" * 64,
        )

        self.assertEqual(manifest.rules_version, "v1.2.0")
        self.assertEqual(
            manifest.snapshot_ids,
            tuple(sorted((self.primary_id, self.auxiliary_id))),
        )
        self.assertEqual(manifest.universe_hash, "1111111111111111")
        self.assertIn("market_daily:fixture:warning", manifest.data_quality_flags)
        self.assertEqual(
            manifest.treasury_yield_source_used,
            "chinabond:ycqx:10Y",
        )
        self.assertEqual(manifest.fallback_policy, "none")

    def test_constructor_rejects_revocation_schema_and_calendar_gaps(self) -> None:
        self.fixture.write_catalog(
            {
                self.primary_id: {
                    "market_daily": {
                        "reason": "fixture revoked",
                        "replacement_snapshot_id": None,
                    }
                }
            }
        )
        with self.assertRaises(DomainRevokedError):
            self._reader()

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = FoundationSnapshotFixture(root)
            primary = fixture.publish_primary(market_schema_version=2)
            auxiliary = fixture.publish_auxiliary()
            fixture.write_catalog()
            with self.assertRaises(ParquetSchemaError):
                ParquetFoundationReader(
                    root,
                    security_master_snapshot_id=primary,
                    market_daily_snapshot_id=primary,
                    adjustment_factors_snapshot_id=primary,
                    calendar_snapshot_id=auxiliary,
                    rate_snapshot_id=auxiliary,
                )

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = FoundationSnapshotFixture(root)
            primary = fixture.publish_primary()
            auxiliary = fixture.publish_auxiliary(
                omit_calendar_day=date(2024, 1, 6)
            )
            fixture.write_catalog()
            with self.assertRaisesRegex(ParquetDataIntegrityError, "calendar"):
                ParquetFoundationReader(
                    root,
                    security_master_snapshot_id=primary,
                    market_daily_snapshot_id=primary,
                    adjustment_factors_snapshot_id=primary,
                    calendar_snapshot_id=auxiliary,
                    rate_snapshot_id=auxiliary,
                )

    def test_factor_conflicts_fail_instead_of_choosing_arbitrarily(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = FoundationSnapshotFixture(root)
            primary = fixture.publish_primary(factor_conflict=True)
            auxiliary = fixture.publish_auxiliary()
            fixture.write_catalog()
            reader = ParquetFoundationReader(
                root,
                security_master_snapshot_id=primary,
                market_daily_snapshot_id=primary,
                adjustment_factors_snapshot_id=primary,
                calendar_snapshot_id=auxiliary,
                rate_snapshot_id=auxiliary,
            )
            with self.assertRaisesRegex(ParquetDataIntegrityError, "conflicting"):
                reader.adjustment_factor_series(
                    "sh.600000", START, END, as_of=END
                )


if __name__ == "__main__":
    unittest.main()
