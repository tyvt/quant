from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from turtle_quant.adapters.stockdb_rd import StockDBSecurityCode
from turtle_quant.storage.snapshot import IngestConfig
from turtle_quant.storage.sync import (
    FoundationSyncRunner,
    validate_foundation_steps,
)


class FakeStockDBAdapter:
    def list_security_codes(self) -> tuple[StockDBSecurityCode, ...]:
        return (
            StockDBSecurityCode("sh.600000", "600000", "sh", False),
            StockDBSecurityCode("sh.600001", "600001", "sh", True),
        )

    def fetch_raw_daily(
        self,
        security_id: str,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        return [
            {
                "security_id": security_id,
                "trade_date": start_date.isoformat(),
                "open": Decimal("10"),
                "high": Decimal("11"),
                "low": Decimal("9"),
                "close": Decimal("10.5"),
                "volume": Decimal("1000"),
                "amount": Decimal("10500"),
                "paused": None,
                "adjust_type": "RAW",
                "schema_version": 1,
                "normalization_version": "market_raw_v1",
                "source_name": "stockdb_rd",
                "source_row_hash": "a" * 64,
                "evidence_ref": f"fixture:bar:{security_id}",
            }
        ]

    def fetch_adjustment_factors(
        self, security_ids: set[str]
    ) -> list[dict[str, object]]:
        return [
            {
                "security_id": security_id,
                "ex_date": "2024-01-01",
                "factor": Decimal("1"),
                "factor_source": "fixture",
                "available_at": "2024-01-01",
                "schema_version": 1,
                "normalization_version": "adjustment_factor_v1",
                "source_name": "stockdb_rd",
                "source_row_hash": "b" * 64,
                "evidence_ref": f"fixture:factor:{security_id}",
            }
            for security_id in sorted(security_ids)
        ]


class MissingBarStockDBAdapter(FakeStockDBAdapter):
    def fetch_raw_daily(
        self,
        security_id: str,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        if security_id == "sh.600001":
            return []
        return super().fetch_raw_daily(
            security_id,
            start_date=start_date,
            end_date=end_date,
        )


class FakeBaostockAdapter:
    def fetch_security_master(self) -> list[dict[str, object]]:
        return [
            {
                "security_id": "sh.600000",
                "raw_code": "600000",
                "vendor_symbol": "sh.600000",
                "exchange": "sh",
                "display_name": "当前样本",
                "board": "main_board",
                "board_effective_from": "1999-11-10",
                "board_effective_to": None,
                "listing_date": "1999-11-10",
                "delisting_date": None,
                "delisting_date_semantics": "provider_out_date",
                "provider_status": "1",
                "schema_version": 1,
                "normalization_version": "cn_equity_v1",
                "source_name": "baostock",
                "source_row_hash": "c" * 64,
                "evidence_ref": "fixture:security:600000",
            },
            {
                "security_id": "sh.600001",
                "raw_code": "600001",
                "vendor_symbol": "sh.600001",
                "exchange": "sh",
                "display_name": "退市样本",
                "board": "main_board",
                "board_effective_from": "1990-01-01",
                "board_effective_to": "2023-01-02",
                "listing_date": "1990-01-01",
                "delisting_date": "2023-01-02",
                "delisting_date_semantics": "provider_out_date",
                "provider_status": "0",
                "schema_version": 1,
                "normalization_version": "cn_equity_v1",
                "source_name": "baostock",
                "source_row_hash": "d" * 64,
                "evidence_ref": "fixture:security:600001",
            },
        ]

    def fetch_calendar(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        current = start_date
        while current <= end_date:
            rows.append(
                {
                    "exchange": "cn",
                    "date": current.isoformat(),
                    "is_trading_day": current.weekday() < 5,
                    "schema_version": 1,
                    "normalization_version": "cn_calendar_v1",
                    "source_name": "baostock",
                    "source_row_hash": "e" * 64,
                    "evidence_ref": f"fixture:calendar:{current}",
                }
            )
            current += timedelta(days=1)
        return rows


class FakeChinabondAdapter:
    def fetch_10y(
        self,
        start_date: date,
        end_date: date,
        *,
        available_at_resolver: object,
    ) -> list[dict[str, object]]:
        resolver = available_at_resolver
        available_at = resolver(start_date)
        return [
            {
                "obs_date": start_date.isoformat(),
                "yield_10y_pct": Decimal("2.3"),
                "curve_id": "ycqx",
                "tenor": "10Y",
                "available_at": available_at.isoformat(),
                "schema_version": 1,
                "normalization_version": "chinabond_10y_v1",
                "source_name": "chinabond",
                "source_row_hash": "f" * 64,
                "evidence_ref": "fixture:chinabond",
            }
        ]


class ForbiddenBaostockAdapter:
    def fetch_security_master(self) -> list[dict[str, object]]:
        raise AssertionError("parent security master should have been reused")

    def fetch_calendar(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        raise AssertionError("calendar was not requested")


class FoundationSyncTests(unittest.TestCase):
    def _config(self) -> IngestConfig:
        return IngestConfig(
            ingest_calendar_date=date(2026, 9, 24),
            steps=(
                "security_master",
                "calendar",
                "market_daily",
                "adjustment_factors",
                "chinabond_10y",
            ),
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            max_symbols=1,
            board_filter_version="main_board_v1",
            source_provenance_template={
                "stockdb_rd": {"version": "fixture"},
                "baostock": {"version": "fixture"},
                "chinabond": {"endpoint": "fixture"},
            },
        )

    def test_dependencies_are_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "security_master"):
            validate_foundation_steps(("market_daily",))
        with self.assertRaisesRegex(ValueError, "calendar"):
            validate_foundation_steps(
                ("security_master", "chinabond_10y")
            )

    def test_market_selection_respects_board_effective_interval(self) -> None:
        config = IngestConfig(
            ingest_calendar_date=date(2026, 9, 24),
            steps=("security_master",),
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            max_symbols=None,
            board_filter_version="main_board_v1",
            source_provenance_template={},
        )
        runner = FoundationSyncRunner(
            storage_root="unused",
            config=config,
            stockdb=FakeStockDBAdapter(),
            baostock=FakeBaostockAdapter(),
            chinabond=FakeChinabondAdapter(),
        )
        selected = runner._select_market_securities(  # noqa: SLF001
            [
                {
                    "security_id": "sz.002001",
                    "board": "main_board",
                    "listing_date": "2004-06-25",
                    "delisting_date": None,
                    "board_effective_from": "2021-04-06",
                    "board_effective_to": None,
                }
            ]
        )
        self.assertEqual(selected, [])

    def test_runs_foundation_domains_and_publishes_complete_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = FoundationSyncRunner(
                storage_root=root,
                config=self._config(),
                stockdb=FakeStockDBAdapter(),
                baostock=FakeBaostockAdapter(),
                chinabond=FakeChinabondAdapter(),
            )
            snapshot_id = runner.run()
            snapshot = root / "snapshots" / snapshot_id
            meta = json.loads((snapshot / "meta.json").read_text("utf-8"))

            self.assertEqual(meta["status"], "complete")
            self.assertEqual(
                sorted(meta["domains"]),
                sorted(self._config().steps),
            )
            self.assertTrue(
                (
                    snapshot
                    / "market"
                    / "raw_daily"
                    / "part-60000.parquet"
                ).is_file()
            )
            self.assertEqual(
                meta["domains"]["market_daily"]["row_count"],
                1,
            )
            self.assertFalse(any((root / ".staging").iterdir()))

    def test_market_coverage_below_configured_threshold_blocks_publish(self) -> None:
        config = IngestConfig(
            ingest_calendar_date=date(2026, 9, 24),
            steps=("security_master", "market_daily"),
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 2),
            max_symbols=2,
            board_filter_version="main_board_v1",
            source_provenance_template={
                "stockdb_rd": {"version": "fixture"},
                "baostock": {"version": "fixture"},
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            runner = FoundationSyncRunner(
                storage_root=temporary,
                config=config,
                stockdb=MissingBarStockDBAdapter(),
                baostock=FakeBaostockAdapter(),
                chinabond=FakeChinabondAdapter(),
            )
            with self.assertRaisesRegex(ValueError, "coverage"):
                runner.run()

    def test_reuses_verified_security_master_from_parent_snapshot(self) -> None:
        parent_config = IngestConfig(
            ingest_calendar_date=date(2026, 9, 24),
            steps=("security_master",),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            max_symbols=1,
            board_filter_version="main_board_v1",
            source_provenance_template={
                "baostock": {"version": "fixture"}
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            parent = FoundationSyncRunner(
                storage_root=temporary,
                config=parent_config,
                stockdb=FakeStockDBAdapter(),
                baostock=FakeBaostockAdapter(),
                chinabond=FakeChinabondAdapter(),
            ).run()
            child_config = IngestConfig(
                ingest_calendar_date=date(2026, 9, 25),
                steps=(
                    "security_master",
                    "market_daily",
                    "adjustment_factors",
                ),
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 2),
                max_symbols=1,
                board_filter_version="main_board_v1",
                source_provenance_template={
                    "stockdb_rd": {"version": "fixture"},
                    "parent_security_master": {"snapshot_id": parent},
                },
            )
            child = FoundationSyncRunner(
                storage_root=temporary,
                config=child_config,
                stockdb=FakeStockDBAdapter(),
                baostock=ForbiddenBaostockAdapter(),
                chinabond=FakeChinabondAdapter(),
                parent_security_master_snapshot=parent,
            ).run()
            child_meta = json.loads(
                (
                    Path(temporary)
                    / "snapshots"
                    / child
                    / "meta.json"
                ).read_text("utf-8")
            )
            self.assertEqual(
                child_meta["domains"]["security_master"]["details"][
                    "parent_snapshot_id"
                ],
                parent,
            )


if __name__ == "__main__":
    unittest.main()
