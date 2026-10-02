from datetime import date, timedelta
from decimal import Decimal
import unittest

from turtle_quant.backtest.execution import (
    FeeRate,
    FeeSchedule,
    ParticipationDay,
    Tradeability,
    attempt_order,
    calculate_participation_limit,
)
from turtle_quant.strategy.orders import OrderSide, OrderStatus, PlannedOrder


D = Decimal


def participation_days(*, amount: str = "1000000") -> tuple[ParticipationDay, ...]:
    start = date(2025, 1, 1)
    return tuple(
        ParticipationDay(
            trade_date=start + timedelta(days=index),
            amount=D(amount),
            paused=False,
            evidence_ref=f"amount:{index}",
        )
        for index in range(20)
    )


def fee_schedule() -> FeeSchedule:
    return FeeSchedule(
        schedule_id="synthetic-fees-v1",
        rates=(
            FeeRate(
                effective_from=date(2024, 1, 1),
                brokerage_bps=D("3"),
                minimum_commission=D("5"),
                exchange_bps=D("0.5"),
                transfer_bps=D("0.1"),
                stamp_duty_bps=D("5"),
            ),
            FeeRate(
                effective_from=date(2025, 7, 1),
                brokerage_bps=D("2"),
                minimum_commission=D("5"),
                exchange_bps=D("0.4"),
                transfer_bps=D("0.1"),
                stamp_duty_bps=D("4"),
            ),
        ),
    )


def order(side: OrderSide = OrderSide.BUY, quantity: int = 10000) -> PlannedOrder:
    return PlannedOrder(
        order_id=f"fixture:{side.value}",
        signal_date=date(2025, 1, 31),
        first_execution_date=date(2025, 2, 3),
        security_id="sh.600001",
        side=side,
        requested_quantity=quantity,
        priority_score=D("80"),
        status=OrderStatus.PENDING,
    )


class ParticipationTests(unittest.TestCase):
    def test_twenty_complete_days_use_fixed_denominator(self) -> None:
        rows = participation_days()
        result = calculate_participation_limit(
            rows,
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.average_amount, D("1000000"))
        self.assertEqual(result.max_daily_notional, D("50000"))

    def test_evidenced_suspension_counts_as_zero(self) -> None:
        rows = list(participation_days())
        rows[0] = ParticipationDay(rows[0].trade_date, None, True, "suspension:0")
        result = calculate_participation_limit(
            tuple(rows),
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.average_amount, D("950000"))

    def test_missing_day_or_evidence_is_unknown_and_not_skipped(self) -> None:
        rows = participation_days()
        missing_day = calculate_participation_limit(
            rows[:-1],
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        broken = list(rows)
        broken[0] = ParticipationDay(broken[0].trade_date, D("1000000"), False, None)
        missing_evidence = calculate_participation_limit(
            tuple(broken),
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        self.assertFalse(missing_day.complete)
        self.assertFalse(missing_evidence.complete)
        self.assertEqual(missing_day.issue_code, "PARTICIPATION_RATE_UNKNOWN")


class ExecutionTests(unittest.TestCase):
    def test_buy_fill_uses_open_slippage_participation_and_costs(self) -> None:
        rows = participation_days(amount="1000000")
        participation = calculate_participation_limit(
            rows,
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        result = attempt_order(
            order(),
            remaining_quantity=10000,
            attempt_number=1,
            execution_date=date(2025, 2, 3),
            raw_open=D("10"),
            tradeability=Tradeability(True, True, False, False, False, "trade:ok"),
            participation=participation,
            fee_schedule=fee_schedule(),
            available_cash=D("1000000"),
            sellable_quantity=0,
        )
        self.assertEqual(result.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(result.fill.quantity, 4900)
        self.assertEqual(result.fill.execution_price, D("10.010"))
        self.assertGreater(result.fill.total_fees, D("5"))
        self.assertEqual(result.remaining_quantity, 5100)

    def test_stamp_duty_is_sell_only_and_rates_switch_by_date(self) -> None:
        schedule = fee_schedule()
        old_buy = schedule.calculate(date(2025, 6, 30), OrderSide.BUY, D("100000"))
        old_sell = schedule.calculate(date(2025, 6, 30), OrderSide.SELL, D("100000"))
        new_sell = schedule.calculate(date(2025, 7, 1), OrderSide.SELL, D("100000"))
        self.assertEqual(old_buy.stamp_duty, D("0"))
        self.assertEqual(old_sell.stamp_duty, D("50"))
        self.assertLess(new_sell.total, old_sell.total)
        self.assertIsNone(schedule.rate_on(date(2023, 12, 31)))

    def test_unknown_participation_consumes_attempt_and_expires_on_fifth(self) -> None:
        rows = participation_days()
        participation = calculate_participation_limit(
            rows[:-1],
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        result = attempt_order(
            order(),
            remaining_quantity=1000,
            attempt_number=5,
            execution_date=date(2025, 2, 7),
            raw_open=D("10"),
            tradeability=Tradeability(True, True, False, False, False, "trade:ok"),
            participation=participation,
            fee_schedule=fee_schedule(),
            available_cash=D("100000"),
            sellable_quantity=0,
        )
        self.assertEqual(result.status, OrderStatus.CANCELED_EXPIRED)
        self.assertEqual(result.issues, ("PARTICIPATION_RATE_UNKNOWN",))
        self.assertIsNone(result.fill)

    def test_tradeability_unknown_and_limits_do_not_infer_from_ohlc(self) -> None:
        rows = participation_days()
        participation = calculate_participation_limit(
            rows,
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        unknown = attempt_order(
            order(),
            remaining_quantity=1000,
            attempt_number=1,
            execution_date=date(2025, 2, 3),
            raw_open=D("10"),
            tradeability=Tradeability(None, True, False, False, False, "trade:unknown"),
            participation=participation,
            fee_schedule=fee_schedule(),
            available_cash=D("100000"),
            sellable_quantity=0,
        )
        upper_limit = attempt_order(
            order(),
            remaining_quantity=1000,
            attempt_number=1,
            execution_date=date(2025, 2, 3),
            raw_open=D("10"),
            tradeability=Tradeability(True, True, False, True, False, "trade:limit"),
            participation=participation,
            fee_schedule=fee_schedule(),
            available_cash=D("100000"),
            sellable_quantity=0,
        )
        self.assertIn("TRADEABILITY_UNKNOWN", unknown.issues)
        self.assertIn("BUY_BLOCKED", upper_limit.issues)

    def test_t_plus_one_sell_quantity_is_enforced(self) -> None:
        rows = participation_days(amount="10000000")
        participation = calculate_participation_limit(
            rows,
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        result = attempt_order(
            order(OrderSide.SELL, 1000),
            remaining_quantity=1000,
            attempt_number=1,
            execution_date=date(2025, 2, 3),
            raw_open=D("10"),
            tradeability=Tradeability(True, True, False, False, False, "trade:ok"),
            participation=participation,
            fee_schedule=fee_schedule(),
            available_cash=D("0"),
            sellable_quantity=0,
        )
        self.assertIsNone(result.fill)
        self.assertIn("T_PLUS_ONE_BLOCKED", result.issues)

    def test_fifth_day_partial_fill_cancels_only_the_remainder(self) -> None:
        rows = participation_days(amount="20020")
        participation = calculate_participation_limit(
            rows,
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        result = attempt_order(
            order(quantity=1000),
            remaining_quantity=600,
            attempt_number=5,
            execution_date=date(2025, 2, 7),
            raw_open=D("10"),
            tradeability=Tradeability(True, True, False, False, False, "trade:ok"),
            participation=participation,
            fee_schedule=fee_schedule(),
            available_cash=D("100000"),
            sellable_quantity=0,
        )
        self.assertEqual(result.fill.quantity, 100)
        self.assertEqual(result.remaining_quantity, 500)
        self.assertEqual(result.status, OrderStatus.CANCELED_EXPIRED)

    def test_participation_window_must_end_before_execution_date(self) -> None:
        rows = tuple(
            ParticipationDay(
                date(2025, 1, 15) + timedelta(days=index),
                D("1000000"),
                False,
                f"amount:overlap:{index}",
            )
            for index in range(20)
        )
        participation = calculate_participation_limit(
            rows,
            expected_trading_dates=tuple(item.trade_date for item in rows),
        )
        result = attempt_order(
            order(),
            remaining_quantity=1000,
            attempt_number=1,
            execution_date=date(2025, 2, 3),
            raw_open=D("10"),
            tradeability=Tradeability(True, True, False, False, False, "trade:ok"),
            participation=participation,
            fee_schedule=fee_schedule(),
            available_cash=D("100000"),
            sellable_quantity=0,
        )
        self.assertIsNone(result.fill)
        self.assertEqual(result.issues, ("PARTICIPATION_RATE_UNKNOWN",))


if __name__ == "__main__":
    unittest.main()
