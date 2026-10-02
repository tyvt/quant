from datetime import date
from decimal import Decimal
import unittest

from turtle_quant.strategy.orders import OrderSide, OrderStatus, plan_rebalance
from turtle_quant.strategy.selection import MonthlySelection, RankedCandidate


D = Decimal


def selection() -> MonthlySelection:
    ranked = (
        RankedCandidate("sh.600001", 1, D("90"), D("75"), D("75"), D("70"), D("80")),
        RankedCandidate("sh.600002", 2, D("80"), D("25"), D("25"), D("60"), D("60")),
    )
    return MonthlySelection(
        diagnostic_only=False,
        official_selection=True,
        diagnostics=(),
        ranked_candidates=ranked,
        target_weights={"sh.600001": D("0.05"), "sh.600002": D("0.05")},
        cash_weight=D("0.90"),
    )


class RebalanceOrderTests(unittest.TestCase):
    def test_targets_use_signal_close_and_buy_lot_rounding(self) -> None:
        orders = plan_rebalance(
            selection(),
            signal_date=date(2025, 1, 31),
            first_execution_date=date(2025, 2, 3),
            signal_nav=D("10000000"),
            signal_raw_closes={"sh.600001": D("33"), "sh.600002": D("20")},
            current_quantities={},
            market_coverage_end=date(2025, 2, 3),
        )
        by_id = {item.security_id: item for item in orders}
        self.assertEqual(by_id["sh.600001"].requested_quantity, 15100)
        self.assertEqual(by_id["sh.600002"].requested_quantity, 25000)
        self.assertTrue(all(item.side is OrderSide.BUY for item in orders))
        self.assertTrue(all(item.status is OrderStatus.PENDING for item in orders))

    def test_exited_odd_lot_is_sold_before_buys(self) -> None:
        orders = plan_rebalance(
            selection(),
            signal_date=date(2025, 1, 31),
            first_execution_date=date(2025, 2, 3),
            signal_nav=D("10000000"),
            signal_raw_closes={"sh.600001": D("50"), "sh.600002": D("50")},
            current_quantities={"sh.600099": 57},
            market_coverage_end=date(2025, 2, 3),
        )
        self.assertEqual(orders[0].side, OrderSide.SELL)
        self.assertEqual(orders[0].security_id, "sh.600099")
        self.assertEqual(orders[0].requested_quantity, 57)

    def test_execution_must_follow_signal_and_out_of_coverage_stays_pending(self) -> None:
        with self.assertRaises(ValueError):
            plan_rebalance(
                selection(),
                signal_date=date(2025, 1, 31),
                first_execution_date=date(2025, 1, 31),
                signal_nav=D("10000000"),
                signal_raw_closes={"sh.600001": D("50"), "sh.600002": D("50")},
                current_quantities={},
                market_coverage_end=date(2025, 2, 3),
            )
        orders = plan_rebalance(
            selection(),
            signal_date=date(2025, 1, 31),
            first_execution_date=date(2025, 2, 3),
            signal_nav=D("10000000"),
            signal_raw_closes={"sh.600001": D("50"), "sh.600002": D("50")},
            current_quantities={},
            market_coverage_end=date(2025, 1, 31),
        )
        self.assertTrue(
            all(item.status is OrderStatus.PENDING_OUT_OF_COVERAGE for item in orders)
        )

    def test_diagnostic_month_cannot_plan_orders(self) -> None:
        diagnostic = MonthlySelection(
            diagnostic_only=True,
            official_selection=False,
            diagnostics=(),
            ranked_candidates=(),
            target_weights={},
            cash_weight=D("1"),
        )
        with self.assertRaises(ValueError):
            plan_rebalance(
                diagnostic,
                signal_date=date(2025, 1, 31),
                first_execution_date=date(2025, 2, 3),
                signal_nav=D("10000000"),
                signal_raw_closes={},
                current_quantities={},
                market_coverage_end=date(2025, 2, 3),
            )

    def test_buy_difference_below_one_lot_is_not_ordered(self) -> None:
        orders = plan_rebalance(
            selection(),
            signal_date=date(2025, 1, 31),
            first_execution_date=date(2025, 2, 3),
            signal_nav=D("100000"),
            signal_raw_closes={"sh.600001": D("50"), "sh.600002": D("50")},
            current_quantities={"sh.600001": 57, "sh.600002": 100},
            market_coverage_end=date(2025, 2, 3),
        )
        self.assertEqual(orders, ())


if __name__ == "__main__":
    unittest.main()
