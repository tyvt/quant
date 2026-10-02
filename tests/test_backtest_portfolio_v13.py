from datetime import date
from decimal import Decimal
import unittest

from turtle_quant.backtest.execution import Fill, FeeBreakdown
from turtle_quant.backtest.portfolio import (
    CashDividend,
    PortfolioState,
    PositionLot,
    SplitEvent,
    apply_cash_dividend,
    apply_fill,
    apply_split,
    settle_delisting,
)
from turtle_quant.strategy.orders import OrderSide


D = Decimal
ZERO_FEES = FeeBreakdown(D("0"), D("0"), D("0"), D("0"))


def fill(side: OrderSide, day: date, quantity: int, price: str) -> Fill:
    value = D(price)
    notional = value * quantity
    return Fill(
        order_id=f"fill:{side.value}:{day}",
        security_id="sh.600001",
        side=side,
        execution_date=day,
        quantity=quantity,
        raw_open=value,
        execution_price=value,
        notional=notional,
        slippage_cost=D("0"),
        fees=ZERO_FEES,
        cash_change=-notional if side is OrderSide.BUY else notional,
    )


class PortfolioAccountingTests(unittest.TestCase):
    def test_buy_lot_is_not_sellable_until_a_later_trading_day(self) -> None:
        state = PortfolioState(cash=D("10000"), lots=())
        bought = apply_fill(state, fill(OrderSide.BUY, date(2025, 2, 3), 100, "10"))
        self.assertEqual(bought.cash, D("9000"))
        self.assertEqual(bought.sellable_quantity("sh.600001", date(2025, 2, 3)), 0)
        self.assertEqual(bought.sellable_quantity("sh.600001", date(2025, 2, 4)), 100)
        with self.assertRaises(ValueError):
            apply_fill(bought, fill(OrderSide.SELL, date(2025, 2, 3), 100, "10"))

    def test_sell_uses_oldest_sellable_lots_and_adds_cash(self) -> None:
        state = PortfolioState(
            cash=D("0"),
            lots=(
                PositionLot("sh.600001", 50, date(2025, 2, 1), D("8")),
                PositionLot("sh.600001", 70, date(2025, 2, 2), D("9")),
            ),
        )
        sold = apply_fill(state, fill(OrderSide.SELL, date(2025, 2, 3), 80, "10"))
        self.assertEqual(sold.cash, D("800"))
        self.assertEqual(sold.quantity("sh.600001"), 40)
        self.assertEqual(sold.lots[0].unit_cost, D("9"))

    def test_verified_dividend_and_split_preserve_explicit_semantics(self) -> None:
        state = PortfolioState(
            cash=D("100"),
            lots=(PositionLot("sh.600001", 100, date(2025, 1, 1), D("20")),),
        )
        dividend_state = apply_cash_dividend(
            state,
            CashDividend(
                "sh.600001", date(2025, 2, 5), D("0.5"), True, "dividend:paid",
                record_date=date(2025, 2, 3),
                entitled_quantity=100,
                entitlement_evidence_ref="holding:record-date",
            ),
        )
        split_state = apply_split(
            dividend_state,
            SplitEvent("sh.600001", date(2025, 2, 6), D("2"), "split:2-for-1"),
        )
        self.assertEqual(dividend_state.cash, D("150.0"))
        self.assertEqual(split_state.quantity("sh.600001"), 200)
        self.assertEqual(split_state.lots[0].unit_cost, D("10"))

    def test_paid_dividend_uses_record_date_entitlement_not_payment_day_holdings(self) -> None:
        state = PortfolioState(cash=D("100"), lots=())
        missing_entitlement = apply_cash_dividend(
            state,
            CashDividend("sh.600001", date(2025, 2, 5), D("0.5"), True, "paid"),
        )
        self.assertFalse(missing_entitlement.complete)
        self.assertEqual(missing_entitlement.cash, D("100"))
        self.assertIn("DIVIDEND_ENTITLEMENT_UNKNOWN", missing_entitlement.quality_flags)
        entitled = apply_cash_dividend(
            state,
            CashDividend(
                "sh.600001", date(2025, 2, 5), D("0.5"), True, "paid",
                record_date=date(2025, 2, 3),
                entitled_quantity=100,
                entitlement_evidence_ref="record-date-holdings",
            ),
        )
        self.assertEqual(entitled.cash, D("150.0"))

    def test_unknown_dividend_or_delisting_blocks_completeness(self) -> None:
        state = PortfolioState(
            cash=D("0"),
            lots=(PositionLot("sh.600001", 100, date(2025, 1, 1), D("20")),),
        )
        dividend_state = apply_cash_dividend(
            state,
            CashDividend("sh.600001", None, None, None, None),
        )
        delisted = settle_delisting(
            dividend_state,
            security_id="sh.600001",
            settled_on=date(2025, 3, 1),
            cash_per_share=None,
            evidence_ref=None,
        )
        self.assertFalse(delisted.complete)
        self.assertIn("DIVIDEND_STATE_UNKNOWN", delisted.quality_flags)
        self.assertIn("DELISTING_EXIT_UNKNOWN", delisted.quality_flags)
        self.assertEqual(delisted.quantity("sh.600001"), 100)


if __name__ == "__main__":
    unittest.main()
