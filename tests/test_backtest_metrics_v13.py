from datetime import date
from decimal import Decimal
import unittest

from turtle_quant.backtest.metrics import (
    BenchmarkPoint,
    NavPoint,
    TradeNotional,
    calculate_performance,
)


D = Decimal


class PerformanceMetricTests(unittest.TestCase):
    def test_complete_series_reports_frozen_metrics_and_earliest_drawdown_tie(self) -> None:
        nav = (
            NavPoint(date(2025, 1, 31), D("100"), D("20"), 2),
            NavPoint(date(2025, 2, 28), D("110"), D("20"), 2),
            NavPoint(date(2025, 3, 31), D("99"), D("19"), 2),
            NavPoint(date(2025, 4, 30), D("121"), D("21"), 3),
        )
        benchmark = (
            BenchmarkPoint(date(2025, 1, 31), D("100")),
            BenchmarkPoint(date(2025, 2, 28), D("105")),
            BenchmarkPoint(date(2025, 3, 31), D("100")),
            BenchmarkPoint(date(2025, 4, 30), D("110")),
        )
        yields = {
            date(2025, 2, 28): D("2"),
            date(2025, 3, 31): D("2"),
            date(2025, 4, 30): D("2"),
        }
        result = calculate_performance(
            nav,
            benchmark_points=benchmark,
            risk_free_yields_pct=yields,
            trades=(TradeNotional(date(2025, 2, 28), D("50")),),
            expected_trading_dates=tuple(item.trade_date for item in nav),
            calendar_complete_through=date(2025, 4, 30),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.cumulative_return, D("0.21"))
        self.assertEqual(result.max_drawdown, D("-0.1"))
        self.assertEqual(result.max_drawdown_peak, date(2025, 2, 28))
        self.assertEqual(result.max_drawdown_trough, date(2025, 3, 31))
        self.assertIsNotNone(result.cagr)
        self.assertIsNotNone(result.annualized_volatility)
        self.assertIsNotNone(result.sharpe)
        self.assertIsNotNone(result.tracking_error)
        self.assertIsNotNone(result.information_ratio)
        self.assertEqual(result.monthly_win_rate, D("0.6666666666666666666666666667"))
        self.assertEqual(result.one_way_turnover, D("50") / (D("2") * D("107.5")))

    def test_missing_benchmark_or_rate_marks_run_incomplete_without_filling(self) -> None:
        nav = (
            NavPoint(date(2025, 1, 1), D("100"), D("100"), 0),
            NavPoint(date(2025, 1, 2), D("101"), D("101"), 0),
        )
        result = calculate_performance(
            nav,
            benchmark_points=(),
            risk_free_yields_pct={},
            trades=(),
            expected_trading_dates=tuple(item.trade_date for item in nav),
            calendar_complete_through=date(2025, 1, 31),
        )
        self.assertFalse(result.complete)
        self.assertIsNone(result.sharpe)
        self.assertIsNone(result.tracking_error)
        self.assertIn("BENCHMARK_INCOMPLETE", result.quality_flags)
        self.assertIn("RISK_FREE_INCOMPLETE", result.quality_flags)

    def test_less_than_two_returns_keeps_sample_metrics_unknown(self) -> None:
        result = calculate_performance(
            (NavPoint(date(2025, 1, 1), D("100"), D("100"), 0),),
            benchmark_points=(BenchmarkPoint(date(2025, 1, 1), D("100")),),
            risk_free_yields_pct={},
            trades=(),
            expected_trading_dates=(date(2025, 1, 1),),
            calendar_complete_through=date(2025, 1, 31),
        )
        self.assertIsNone(result.cagr)
        self.assertIsNone(result.annualized_volatility)
        self.assertIsNone(result.sharpe)

    def test_zero_metric_denominators_mark_output_incomplete(self) -> None:
        nav = (
            NavPoint(date(2025, 1, 1), D("100"), D("100"), 0),
            NavPoint(date(2025, 1, 2), D("101"), D("101"), 0),
            NavPoint(date(2025, 1, 3), D("102.01"), D("102.01"), 0),
        )
        benchmark = tuple(BenchmarkPoint(item.trade_date, item.nav) for item in nav)
        result = calculate_performance(
            nav,
            benchmark_points=benchmark,
            risk_free_yields_pct={date(2025, 1, 2): D("0"), date(2025, 1, 3): D("0")},
            trades=(),
            expected_trading_dates=tuple(item.trade_date for item in nav),
            calendar_complete_through=date(2025, 1, 31),
        )
        self.assertFalse(result.complete)
        self.assertIsNone(result.sharpe)
        self.assertIsNone(result.information_ratio)
        self.assertIn("SHARPE_DENOMINATOR_ZERO", result.quality_flags)
        self.assertIn("ACTIVE_RETURN_DENOMINATOR_ZERO", result.quality_flags)

    def test_missing_nav_session_blocks_complete_metrics(self) -> None:
        expected = (date(2025, 1, 29), date(2025, 1, 30), date(2025, 1, 31))
        nav = (
            NavPoint(expected[0], D("100"), D("100"), 0),
            NavPoint(expected[2], D("110"), D("110"), 0),
        )
        result = calculate_performance(
            nav,
            benchmark_points=tuple(BenchmarkPoint(day, D("100")) for day in expected),
            risk_free_yields_pct={expected[2]: D("2")},
            trades=(),
            expected_trading_dates=expected,
            calendar_complete_through=date(2025, 1, 31),
        )
        self.assertFalse(result.complete)
        self.assertIn("NAV_INCOMPLETE", result.quality_flags)

    def test_incomplete_final_month_is_not_counted_as_monthly_win(self) -> None:
        dates = (date(2025, 1, 31), date(2025, 2, 3), date(2025, 2, 4))
        nav = tuple(NavPoint(day, D(100 + index * 10), D(100 + index * 10), 0)
                    for index, day in enumerate(dates))
        result = calculate_performance(
            nav,
            benchmark_points=tuple(BenchmarkPoint(day, D(100 + index * 5))
                                   for index, day in enumerate(dates)),
            risk_free_yields_pct={dates[1]: D("2"), dates[2]: D("2")},
            trades=(),
            expected_trading_dates=dates,
            calendar_complete_through=date(2025, 2, 4),
        )
        self.assertIsNone(result.monthly_win_rate)
        self.assertIn("MONTHLY_WIN_RATE_UNAVAILABLE", result.quality_flags)


if __name__ == "__main__":
    unittest.main()
