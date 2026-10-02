from datetime import date, timedelta
from decimal import Decimal
import unittest

from turtle_quant.core.result import ResultStatus
from turtle_quant.market.position import PositionDay, analyze_market_position


D = Decimal
HASH = "a" * 64


def days(count: int, *, price: Decimal | None = D("10")) -> tuple[PositionDay, ...]:
    start = date(2024, 1, 1)
    return tuple(
        PositionDay(
            trade_date=start + timedelta(days=offset),
            adjusted_close=price,
            paused=False,
            evidence_ref=f"bar:{offset}",
        )
        for offset in range(count)
    )


class MarketPositionV13Tests(unittest.TestCase):
    def test_all_equal_prices_have_mid_rank_fifty(self) -> None:
        series = days(504)
        result = analyze_market_position(
            series,
            as_of=series[-1].trade_date,
            expected_trading_dates=tuple(item.trade_date for item in series),
            valuation_price=D("10"),
            factor_view_hash=HASH,
            valuation_factor_view_hash=HASH,
        )

        self.assertEqual(result.status, ResultStatus.PASS)
        self.assertEqual(result.position_pct, D("50"))
        self.assertEqual(result.market_position_score, D("50"))
        self.assertEqual(result.label, "MID")
        self.assertEqual(result.sample_size, 504)

    def test_window_is_capped_at_latest_756_days(self) -> None:
        start = date(2020, 1, 1)
        series = tuple(
            PositionDay(
                trade_date=start + timedelta(days=offset),
                adjusted_close=D(offset + 1),
                paused=False,
                evidence_ref=f"bar:{offset}",
            )
            for offset in range(800)
        )
        result = analyze_market_position(
            series,
            as_of=series[-1].trade_date,
            expected_trading_dates=tuple(item.trade_date for item in series),
            valuation_price=D("800"),
            factor_view_hash=HASH,
            valuation_factor_view_hash=HASH,
        )
        self.assertEqual(result.sample_size, 756)
        self.assertGreater(result.position_pct, D("99"))

    def test_explicit_suspension_does_not_forward_fill(self) -> None:
        series = list(days(505))
        series[100] = PositionDay(
            trade_date=series[100].trade_date,
            adjusted_close=None,
            paused=True,
            evidence_ref="suspension:100",
        )
        result = analyze_market_position(
            tuple(series),
            as_of=series[-1].trade_date,
            expected_trading_dates=tuple(item.trade_date for item in series),
            valuation_price=D("10"),
            factor_view_hash=HASH,
            valuation_factor_view_hash=HASH,
        )
        self.assertEqual(result.status, ResultStatus.PASS)
        self.assertEqual(result.sample_size, 504)

    def test_unexplained_missing_close_blocks_standard_result(self) -> None:
        series = list(days(505))
        series[100] = PositionDay(
            trade_date=series[100].trade_date,
            adjusted_close=None,
            paused=False,
            evidence_ref="bar:missing",
        )
        result = analyze_market_position(
            tuple(series),
            as_of=series[-1].trade_date,
            expected_trading_dates=tuple(item.trade_date for item in series),
            valuation_price=D("10"),
            factor_view_hash=HASH,
            valuation_factor_view_hash=HASH,
        )
        self.assertEqual(result.status, ResultStatus.NEEDS_REVIEW)
        self.assertIn("MISSING_BAR", result.quality_flags)

    def test_evidence_or_factor_view_mismatch_blocks(self) -> None:
        series = list(days(504))
        series[0] = PositionDay(
            trade_date=series[0].trade_date,
            adjusted_close=D("10"),
            paused=False,
            evidence_ref=None,
        )
        missing_evidence = analyze_market_position(
            tuple(series),
            as_of=series[-1].trade_date,
            expected_trading_dates=tuple(item.trade_date for item in series),
            valuation_price=D("10"),
            factor_view_hash=HASH,
            valuation_factor_view_hash=HASH,
        )
        mismatch = analyze_market_position(
            days(504),
            as_of=days(504)[-1].trade_date,
            expected_trading_dates=tuple(item.trade_date for item in days(504)),
            valuation_price=D("10"),
            factor_view_hash=HASH,
            valuation_factor_view_hash="b" * 64,
        )
        self.assertIn("EVIDENCE_MISSING", missing_evidence.quality_flags)
        self.assertIn("FACTOR_VIEW_MISMATCH", mismatch.quality_flags)

    def test_omitted_expected_trading_day_is_not_silently_skipped(self) -> None:
        series = days(505)
        result = analyze_market_position(
            tuple(item for item in series if item.trade_date != series[100].trade_date),
            as_of=series[-1].trade_date,
            expected_trading_dates=tuple(item.trade_date for item in series),
            valuation_price=D("10"),
            factor_view_hash=HASH,
            valuation_factor_view_hash=HASH,
        )
        self.assertEqual(result.status, ResultStatus.NEEDS_REVIEW)
        self.assertIn("MISSING_BAR", result.quality_flags)


if __name__ == "__main__":
    unittest.main()
