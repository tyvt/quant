from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from turtle_quant.adapters.baostock_adapter import BaostockAdapter
from turtle_quant.adapters.chinabond import (
    CHINABOND_HISTORY_ENDPOINT,
    ChinabondAdapter,
    build_history_request,
    parse_history_html,
    year_slices,
)
from turtle_quant.adapters.stockdb_rd import (
    StockDBLocalAdapter,
    adjusted_close_to_as_of,
)
from turtle_quant.storage.parquet import read_parquet_rows, write_parquet_rows


class FakeQuery:
    def __init__(self, value: object) -> None:
        self.value = value

    def do(self) -> object:
        return self.value

    def get(self, *_args: object) -> "FakeQuery":
        return self


class FakeStockDB:
    def get(self, table: str) -> FakeQuery:
        if table == "股票代码":
            return FakeQuery({"0": ["000001"], "6": ["600000"]})
        if table == "复权*":
            return FakeQuery(
                [
                    ["复权:600000:20200101", 1.0],
                    ["复权:600000:20210101", 2.0],
                ]
            )
        raise AssertionError(table)

    def vals(self, table: str, *args: object) -> FakeQuery:
        if table == "退市*":
            return FakeQuery(["600001"])
        if table == "日k":
            code, _query = args
            return FakeQuery(
                [
                    {
                        "code": code,
                        "date": 20260923,
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                        "volume": 1000,
                        "amount": 10500,
                    }
                ]
            )
        raise AssertionError((table, args))


class ZeroPlaceholderStockDB(FakeStockDB):
    def vals(self, table: str, *args: object) -> FakeQuery:
        if table != "日k":
            return super().vals(table, *args)
        code, _query = args
        return FakeQuery(
            [
                {
                    "code": code,
                    "date": 20260624,
                    "open": 0,
                    "high": 0,
                    "low": 0,
                    "close": 69.78,
                    "volume": 0,
                    "amount": 0,
                }
            ]
        )


class StockDBAdapterTests(unittest.TestCase):
    def test_reads_query_result_with_do_and_keeps_delisted_codes(self) -> None:
        adapter = StockDBLocalAdapter(rd=FakeStockDB())
        securities = adapter.list_security_codes()
        self.assertEqual(
            [item.security_id for item in securities],
            ["sh.600000", "sh.600001", "sz.000001"],
        )
        self.assertTrue(
            next(
                item
                for item in securities
                if item.security_id == "sh.600001"
            ).is_in_delisted_table
        )

    def test_maps_only_unadjusted_daily_bars(self) -> None:
        adapter = StockDBLocalAdapter(rd=FakeStockDB())
        rows = adapter.fetch_raw_daily(
            "sh.600000",
            start_date=date(2026, 9, 23),
            end_date=date(2026, 9, 24),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["adjust_type"], "RAW")
        self.assertEqual(rows[0]["close"], Decimal("10.5"))
        self.assertIsNone(rows[0]["paused"])
        self.assertEqual(rows[0]["security_id"], "sh.600000")

    def test_reads_cumulative_factor_with_key_date(self) -> None:
        adapter = StockDBLocalAdapter(rd=FakeStockDB())
        rows = adapter.fetch_adjustment_factors({"sh.600000"})
        self.assertEqual(
            [row["ex_date"] for row in rows],
            ["2020-01-01", "2021-01-01"],
        )
        self.assertEqual(rows[-1]["factor"], Decimal("2.0"))

    def test_provider_pause_flags_do_not_treat_zero_text_as_true(self) -> None:
        class PausedStockDB(FakeStockDB):
            def __init__(self, paused: object) -> None:
                self.paused = paused

            def vals(self, table: str, *args: object) -> FakeQuery:
                if table != "日k":
                    return super().vals(table, *args)
                code, _query = args
                row = super().vals(table, *args).do()[0]
                row = dict(row)
                row["code"] = code
                row["paused"] = self.paused
                return FakeQuery([row])

        unpaused = StockDBLocalAdapter(
            rd=PausedStockDB("0")
        ).fetch_raw_daily(
            "sh.600000",
            start_date=date(2026, 9, 23),
            end_date=date(2026, 9, 24),
        )
        paused = StockDBLocalAdapter(
            rd=PausedStockDB(1)
        ).fetch_raw_daily(
            "sh.600000",
            start_date=date(2026, 9, 23),
            end_date=date(2026, 9, 24),
        )
        self.assertIs(unpaused[0]["paused"], False)
        self.assertEqual(unpaused[0]["pause_status_source"], "provider")
        self.assertIs(paused[0]["paused"], True)

    def test_marks_stockdb_zero_ohlc_placeholder_as_nontrading(self) -> None:
        rows = StockDBLocalAdapter(
            rd=ZeroPlaceholderStockDB()
        ).fetch_raw_daily(
            "sz.001331",
            start_date=date(2026, 6, 24),
            end_date=date(2026, 6, 24),
        )
        self.assertIs(rows[0]["paused"], True)
        self.assertEqual(
            rows[0]["pause_status_source"],
            "derived_zero_ohlc",
        )

    def test_adjusted_to_as_of_uses_factor_at_each_date(self) -> None:
        self.assertEqual(
            adjusted_close_to_as_of(
                raw_close=Decimal("20"),
                factor_on_bar_date=Decimal("1"),
                factor_as_of=Decimal("2"),
            ),
            Decimal("10"),
        )
        self.assertEqual(
            adjusted_close_to_as_of(
                raw_close=Decimal("10"),
                factor_on_bar_date=Decimal("2"),
                factor_as_of=Decimal("2"),
            ),
            Decimal("10"),
        )


class FakeResult:
    def __init__(self, fields: list[str], rows: list[list[str]]) -> None:
        self.fields = fields
        self.rows = rows
        self.index = 0
        self.error_code = "0"
        self.error_msg = ""

    def next(self) -> bool:
        return self.index < len(self.rows)

    def get_row_data(self) -> list[str]:
        row = self.rows[self.index]
        self.index += 1
        return row


class FakeResponse:
    def __init__(self, error_code: str = "0", error_msg: str = "") -> None:
        self.error_code = error_code
        self.error_msg = error_msg


class FakeBaostock:
    __version__ = "fixture"

    def login(self) -> FakeResponse:
        return FakeResponse()

    def logout(self) -> FakeResponse:
        return FakeResponse()

    def query_trade_dates(
        self, *, start_date: str, end_date: str
    ) -> FakeResult:
        return FakeResult(
            ["calendar_date", "is_trading_day"],
            [["2026-09-23", "1"], ["2026-09-24", "0"]],
        )

    def query_stock_basic(self, **_kwargs: object) -> FakeResult:
        return FakeResult(
            ["code", "code_name", "ipoDate", "outDate", "type", "status"],
            [
                ["sh.600000", "浦发银行", "1999-11-10", "", "1", "1"],
                ["sh.600001", "退市样本", "1990-01-01", "2023-01-02", "1", "0"],
                ["sz.002001", "历史中小板", "2004-06-25", "", "1", "1"],
            ],
        )

    def query_adjust_factor(
        self, *, code: str, start_date: str, end_date: str
    ) -> FakeResult:
        return FakeResult(
            [
                "code",
                "dividOperateDate",
                "foreAdjustFactor",
                "backAdjustFactor",
                "adjustFactor",
            ],
            [[code, "2024-06-01", "0.5", "2", "2"]],
        )


class FlakyBaostock(FakeBaostock):
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.login_calls = 0

    def login(self) -> FakeResponse:
        self.login_calls += 1
        if self.login_calls <= self.failures:
            return FakeResponse("10002007", "network receive error")
        return FakeResponse()


class BaostockAdapterTests(unittest.TestCase):
    def test_retries_transient_login_failure(self) -> None:
        module = FlakyBaostock(failures=2)
        with BaostockAdapter(
            module, login_attempts=3, retry_delay_seconds=0
        ):
            pass
        self.assertEqual(module.login_calls, 3)

    def test_maps_calendar_and_historical_security_master(self) -> None:
        with BaostockAdapter(FakeBaostock()) as adapter:
            calendar = adapter.fetch_calendar(
                date(2026, 9, 23), date(2026, 9, 24)
            )
            master = adapter.fetch_security_master()
        self.assertEqual(
            [row["is_trading_day"] for row in calendar],
            [True, False],
        )
        self.assertEqual(master[1]["delisting_date"], "2023-01-02")
        self.assertEqual(master[1]["delisting_date_semantics"], "provider_out_date")
        former_sme = [
            row for row in master if row["security_id"] == "sz.002001"
        ]
        self.assertEqual(
            [(row["board"], row["board_effective_from"]) for row in former_sme],
            [
                ("sme", "2004-06-25"),
                ("main_board", "2021-04-06"),
            ],
        )
        self.assertEqual(former_sme[0]["board_effective_to"], "2021-04-05")

    def test_maps_adjustment_factor_without_float(self) -> None:
        with BaostockAdapter(FakeBaostock()) as adapter:
            rows = adapter.fetch_adjustment_factors(
                "sh.600000",
                date(2024, 1, 1),
                date(2024, 12, 31),
            )
        self.assertEqual(rows[0]["factor"], Decimal("2"))
        self.assertEqual(rows[0]["available_at"], "2024-06-01")


class ChinabondAdapterTests(unittest.TestCase):
    def test_uses_verified_history_endpoint_and_year_slices(self) -> None:
        endpoint, params = build_history_request(
            date(2024, 1, 1), date(2024, 12, 31)
        )
        self.assertEqual(endpoint, CHINABOND_HISTORY_ENDPOINT)
        self.assertEqual(params["qxId"], "ycqx")
        self.assertEqual(params["gjqx"], "0")
        self.assertEqual(
            year_slices(date(2023, 7, 1), date(2025, 2, 1)),
            (
                (date(2023, 7, 1), date(2023, 12, 31)),
                (date(2024, 1, 1), date(2024, 12, 31)),
                (date(2025, 1, 1), date(2025, 2, 1)),
            ),
        )

    def test_parses_ten_year_yield_as_decimal(self) -> None:
        html = """
        <table>
          <tr><th>曲线名称</th><th>日期</th><th>10年</th></tr>
          <tr><td>中债国债收益率曲线</td><td>2024-01-02</td><td>2.3456</td></tr>
          <tr><td>中债商业银行普通债收益率曲线(AAA)</td><td>2024-01-02</td><td>2.9000</td></tr>
        </table>
        """
        rows = parse_history_html(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["obs_date"], "2024-01-02")
        self.assertEqual(rows[0]["yield_10y_pct"], Decimal("2.3456"))

    def test_fetch_records_request_evidence_and_conservative_availability(
        self,
    ) -> None:
        class Response:
            text = """
            <table>
              <tr><th>曲线名称</th><th>日期</th><th>10年</th></tr>
              <tr><td>中债国债收益率曲线</td><td>2024-01-02</td><td>2.3456</td></tr>
            </table>
            """

            def raise_for_status(self) -> None:
                return None

        class Session:
            def get(self, *_args: object, **_kwargs: object) -> Response:
                return Response()

        rows = ChinabondAdapter(Session()).fetch_10y(
            date(2024, 1, 1),
            date(2024, 1, 3),
            available_at_resolver=lambda observed: observed
            + timedelta(days=1),
        )
        self.assertEqual(rows[0]["available_at"], "2024-01-03")
        self.assertEqual(rows[0]["curve_id"], "ycqx")
        self.assertRegex(str(rows[0]["source_row_hash"]), r"^[0-9a-f]{64}$")

    def test_rejects_availability_before_observation(self) -> None:
        class Response:
            text = """
            <table>
              <tr><th>曲线名称</th><th>日期</th><th>10年</th></tr>
              <tr><td>中债国债收益率曲线</td><td>2024-01-02</td><td>2.3</td></tr>
            </table>
            """

            def raise_for_status(self) -> None:
                return None

        class Session:
            def get(self, *_args: object, **_kwargs: object) -> Response:
                return Response()

        with self.assertRaisesRegex(ValueError, "available_at"):
            ChinabondAdapter(Session()).fetch_10y(
                date(2024, 1, 1),
                date(2024, 1, 3),
                available_at_resolver=lambda observed: observed
                - timedelta(days=1),
            )

    def test_fetch_records_an_explicit_gap_for_empty_year(self) -> None:
        class Response:
            def __init__(self, text: str) -> None:
                self.text = text

            def raise_for_status(self) -> None:
                return None

        class Session:
            def get(
                self, _url: str, *, params: dict[str, str], **_kwargs: object
            ) -> Response:
                value = "-" if params["startDate"].startswith("2005") else "2.8"
                year = params["startDate"][:4]
                return Response(
                    "<table><tr><th>曲线名称</th><th>日期</th><th>10年</th></tr>"
                    f"<tr><td>中债国债收益率曲线</td><td>{year}-03-01</td>"
                    f"<td>{value}</td></tr></table>"
                )

        adapter = ChinabondAdapter(Session())
        rows = adapter.fetch_10y(
            date(2005, 1, 1),
            date(2006, 12, 31),
            available_at_resolver=lambda observed: observed
            + timedelta(days=1),
        )
        self.assertEqual([row["obs_date"] for row in rows], ["2006-03-01"])
        self.assertEqual(adapter.last_gaps, ("2005",))


class ParquetStorageTests(unittest.TestCase):
    def test_atomic_parquet_round_trip_preserves_decimal_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "rows.parquet"
            write_parquet_rows(
                target,
                [{"symbol": "sh.600000", "factor": Decimal("2.3456")}],
                sort_keys=("symbol",),
            )
            self.assertFalse(
                any(path.suffix == ".tmp" for path in target.parent.iterdir())
            )
            rows = read_parquet_rows(target)
            self.assertEqual(rows[0]["factor"], "2.3456")

    def test_allocator_release_failure_does_not_discard_written_shard(
        self,
    ) -> None:
        class Pool:
            def release_unused(self) -> None:
                raise OSError(22, "allocator release failed")

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "rows.parquet"
            with patch("pyarrow.default_memory_pool", return_value=Pool()):
                write_parquet_rows(
                    target,
                    [{"symbol": "sh.600000", "value": "1"}],
                )
            self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()
