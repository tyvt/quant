from datetime import date, timedelta
from decimal import Decimal
import unittest

from turtle_quant.backtest.engine import (
    ExecutionMarket,
    ExecutionSession,
    run_order_book as _run_order_book,
)
from turtle_quant.backtest.execution import (
    FeeRate,
    FeeSchedule,
    ParticipationResult,
    Tradeability,
)
from turtle_quant.backtest.manifest import StrategyRunManifest
from turtle_quant.backtest.portfolio import (
    CashDividend,
    DelistingSettlement,
    PortfolioState,
    PositionLot,
    SplitEvent,
    UnsupportedCorporateAction,
)
from turtle_quant.strategy.orders import OrderSide, OrderStatus, PlannedOrder


D = Decimal


def fees() -> FeeSchedule:
    return FeeSchedule(
        "fixture-zero-fees",
        (
            FeeRate(
                date(2020, 1, 1),
                D("0"),
                D("0"),
                D("0"),
                D("0"),
                D("0"),
            ),
        ),
    )


def order(
    security_id: str,
    side: OrderSide,
    quantity: int,
    *,
    priority: str = "80",
) -> PlannedOrder:
    return PlannedOrder(
        order_id=f"fixture:{security_id}:{side.value}",
        signal_date=date(2025, 1, 31),
        first_execution_date=date(2025, 2, 3),
        security_id=security_id,
        side=side,
        requested_quantity=quantity,
        priority_score=D(priority) if side is OrderSide.BUY else None,
        status=OrderStatus.PENDING,
    )


def market(
    security_id: str,
    *,
    raw_open: str = "10",
    raw_close: str | None = "10",
    max_notional: str = "1000000",
    paused: bool = False,
) -> ExecutionMarket:
    return ExecutionMarket(
        security_id=security_id,
        raw_open=D(raw_open),
        raw_close=None if raw_close is None else D(raw_close),
        close_evidence_ref=None if raw_close is None else f"close:{security_id}",
        tradeability=Tradeability(
            can_buy=not paused,
            can_sell=not paused,
            paused=paused,
            at_upper_limit=False,
            at_lower_limit=False,
            evidence_ref=f"tradeability:{security_id}",
        ),
        participation=ParticipationResult(
            complete=True,
            average_amount=D(max_notional) / D("0.05"),
            max_daily_notional=D(max_notional),
            window_end=date(2025, 1, 31),
        ),
    )


def run_order_book(
    initial: PortfolioState,
    orders: tuple[PlannedOrder, ...],
    sessions: tuple[ExecutionSession, ...],
    *,
    fee_schedule: FeeSchedule,
):
    return _run_order_book(
        initial,
        orders,
        sessions,
        fee_schedule=fee_schedule,
        expected_trading_dates=tuple(sorted(item.trade_date for item in sessions)),
    )


class BacktestEngineTests(unittest.TestCase):
    def test_same_day_sells_fund_later_buys_and_outputs_are_deterministic(self) -> None:
        initial = PortfolioState(
            cash=D("0"),
            lots=(PositionLot("sh.600001", 1000, date(2025, 1, 1), D("15")),),
        )
        orders = (
            order("sh.600002", OrderSide.BUY, 1000),
            order("sh.600001", OrderSide.SELL, 1000),
        )
        session = ExecutionSession(
            trade_date=date(2025, 2, 3),
            markets={
                "sh.600001": market("sh.600001", raw_open="20", raw_close="20"),
                "sh.600002": market("sh.600002", raw_open="10", raw_close="10"),
            },
        )
        first = run_order_book(initial, orders, (session,), fee_schedule=fees())
        second = run_order_book(initial, tuple(reversed(orders)), (session,), fee_schedule=fees())

        self.assertEqual(tuple(fill.side for fill in first.fills), (OrderSide.SELL, OrderSide.BUY))
        self.assertEqual(first.final_portfolio.quantity("sh.600001"), 0)
        self.assertEqual(first.final_portfolio.quantity("sh.600002"), 1000)
        self.assertEqual(first.logical_hashes(), second.logical_hashes())
        self.assertEqual(first.nav_points, second.nav_points)

        def manifest_for(result):
            hashes = result.logical_hashes()
            return StrategyRunManifest(
                manifest_version="strategy-v1",
                run_id="fixture-repeat",
                base_run_manifest_hash="a" * 64,
                strategy_id="GENERAL_FCF_MONTHLY_TOP20_V1",
                execution_policy_id="CN_A_OPEN_STRICT_V1",
                initial_capital=D("20000"),
                signal_start=date(2025, 1, 31),
                signal_end=date(2025, 1, 31),
                snapshot_ids=("market:fixture", "calendar:fixture"),
                benchmark_id="H00985",
                benchmark_snapshot_id="benchmark:fixture",
                fee_schedule_id="fixture-zero-fees",
                config_hash="b" * 64,
                code_version="fixture",
                rules_version="v1.3.0",
                completeness_summary={
                    "complete": result.complete,
                    "quality_flag_count": len(result.quality_flags),
                },
                order_content_hash=hashes["orders"],
                holding_content_hash=hashes["holdings"],
                nav_content_hash=hashes["nav"],
            )

        self.assertEqual(manifest_for(first).canonical_json(), manifest_for(second).canonical_json())

    def test_remainder_is_canceled_after_five_partial_days(self) -> None:
        initial = PortfolioState(cash=D("100000"), lots=())
        sessions = tuple(
            ExecutionSession(
                trade_date=date(2025, 2, 3) + timedelta(days=index),
                markets={
                    "sh.600002": market(
                        "sh.600002",
                        max_notional="1001",
                    )
                },
            )
            for index in range(5)
        )
        result = run_order_book(
            initial,
            (order("sh.600002", OrderSide.BUY, 1000),),
            sessions,
            fee_schedule=fees(),
        )
        outcome = result.order_outcomes[0]
        self.assertEqual(outcome.attempts, 5)
        self.assertEqual(outcome.status, OrderStatus.CANCELED_EXPIRED)
        self.assertEqual(outcome.remaining_quantity, 500)
        self.assertEqual(result.final_portfolio.quantity("sh.600002"), 500)

    def test_order_hash_includes_fill_prices_and_fee_ledger(self) -> None:
        initial = PortfolioState(cash=D("10000"), lots=())
        planned = (order("sh.600002", OrderSide.BUY, 100),)
        first = run_order_book(
            initial,
            planned,
            (ExecutionSession(date(2025, 2, 3), {"sh.600002": market("sh.600002", raw_open="10")}),),
            fee_schedule=fees(),
        )
        second = run_order_book(
            initial,
            planned,
            (ExecutionSession(date(2025, 2, 3), {"sh.600002": market("sh.600002", raw_open="11")}),),
            fee_schedule=fees(),
        )
        self.assertEqual(first.order_outcomes[0].status, second.order_outcomes[0].status)
        self.assertEqual(first.order_outcomes[0].filled_quantity, second.order_outcomes[0].filled_quantity)
        self.assertNotEqual(first.logical_hashes()["orders"], second.logical_hashes()["orders"])

    def test_unknown_execution_input_blocks_run_completeness(self) -> None:
        initial = PortfolioState(cash=D("10000"), lots=())
        planned = (order("sh.600002", OrderSide.BUY, 100),)
        result = run_order_book(
            initial,
            planned,
            (ExecutionSession(date(2025, 2, 3), {}),),
            fee_schedule=fees(),
        )
        self.assertFalse(result.complete)
        self.assertIn("MARKET_DATA_UNKNOWN", result.quality_flags)

    def test_split_before_open_and_dividend_after_execution_affect_nav_once(self) -> None:
        initial = PortfolioState(
            cash=D("0"),
            lots=(PositionLot("sh.600001", 100, date(2025, 1, 1), D("20")),),
        )
        session = ExecutionSession(
            date(2025, 2, 5),
            {"sh.600001": market("sh.600001", raw_open="10", raw_close="10")},
            splits=(SplitEvent("sh.600001", date(2025, 2, 5), D("2"), "split"),),
            cash_dividends=(CashDividend(
                "sh.600001", date(2025, 2, 5), D("0.5"), True, "paid",
                record_date=date(2025, 2, 3),
                entitled_quantity=100,
                entitlement_evidence_ref="record-date-holdings",
            ),),
        )
        result = run_order_book(initial, (), (session,), fee_schedule=fees())
        self.assertTrue(result.complete)
        self.assertEqual(result.final_portfolio.quantity("sh.600001"), 200)
        self.assertEqual(result.final_portfolio.cash, D("50"))
        self.assertEqual(result.nav_points[0].nav, D("2050"))

    def test_unknown_delisting_and_unsupported_action_block_publication(self) -> None:
        initial = PortfolioState(
            cash=D("0"),
            lots=(PositionLot("sh.600001", 100, date(2025, 1, 1), D("10")),),
        )
        session = ExecutionSession(
            date(2025, 2, 5),
            {"sh.600001": market("sh.600001")},
            delistings=(DelistingSettlement("sh.600001", date(2025, 2, 5), None, None),),
            unsupported_actions=(UnsupportedCorporateAction(
                "sh.600001", date(2025, 2, 5), "RIGHTS_ISSUE", "rights",
            ),),
        )
        result = run_order_book(initial, (), (session,), fee_schedule=fees())
        self.assertFalse(result.complete)
        self.assertEqual(result.final_portfolio.cash, D("0"))
        self.assertEqual(result.final_portfolio.quantity("sh.600001"), 100)
        self.assertIn("DELISTING_EXIT_UNKNOWN", result.quality_flags)
        self.assertIn("UNSUPPORTED_CORPORATE_ACTION", result.quality_flags)

    def test_pending_order_is_not_executed_across_unadjusted_split(self) -> None:
        initial = PortfolioState(cash=D("10000"), lots=())
        session = ExecutionSession(
            date(2025, 2, 3),
            {"sh.600002": market("sh.600002", raw_open="5", raw_close="5")},
            splits=(SplitEvent("sh.600002", date(2025, 2, 3), D("2"), "split"),),
        )
        result = run_order_book(
            initial,
            (order("sh.600002", OrderSide.BUY, 100),),
            (session,),
            fee_schedule=fees(),
        )
        self.assertEqual(result.fills, ())
        self.assertFalse(result.complete)
        self.assertIn("CORPORATE_ACTION_ORDER_UNKNOWN", result.quality_flags)

    def test_missing_execution_session_cannot_shortcut_five_day_clock(self) -> None:
        initial = PortfolioState(cash=D("10000"), lots=())
        sessions = (ExecutionSession(date(2025, 2, 3), {}),)
        with self.assertRaisesRegex(ValueError, "cover every expected trading date"):
            _run_order_book(
                initial,
                (order("sh.600002", OrderSide.BUY, 100),),
                sessions,
                fee_schedule=fees(),
                expected_trading_dates=(date(2025, 2, 3), date(2025, 2, 4)),
            )

    def test_paused_position_may_use_last_evidenced_close_for_bookkeeping_only(self) -> None:
        initial = PortfolioState(
            cash=D("0"),
            lots=(PositionLot("sh.600001", 100, date(2025, 1, 1), D("10")),),
        )
        sessions = (
            ExecutionSession(
                date(2025, 2, 3),
                {"sh.600001": market("sh.600001", raw_close="10")},
            ),
            ExecutionSession(
                date(2025, 2, 4),
                {"sh.600001": market("sh.600001", raw_close=None, paused=True)},
            ),
        )
        result = run_order_book(initial, (), sessions, fee_schedule=fees())
        self.assertTrue(result.complete)
        self.assertEqual(tuple(point.nav for point in result.nav_points), (D("1000"), D("1000")))
        stale = tuple(item for item in result.holdings if item.trade_date == date(2025, 2, 4))[0]
        self.assertEqual(stale.stale_trading_days, 1)

    def test_unexplained_missing_close_blocks_publishable_nav(self) -> None:
        initial = PortfolioState(
            cash=D("0"),
            lots=(PositionLot("sh.600001", 100, date(2025, 1, 1), D("10")),),
        )
        broken_market = market("sh.600001", raw_close=None, paused=False)
        result = run_order_book(
            initial,
            (),
            (ExecutionSession(date(2025, 2, 3), {"sh.600001": broken_market}),),
            fee_schedule=fees(),
        )
        self.assertFalse(result.complete)
        self.assertIn("NAV_PRICE_UNKNOWN", result.quality_flags)
        self.assertEqual(result.nav_points, ())

    def test_cash_shortage_scales_all_buys_before_priority_residual(self) -> None:
        initial = PortfolioState(cash=D("11011"), lots=())
        orders = (
            order("sh.600002", OrderSide.BUY, 1000, priority="90"),
            order("sh.600003", OrderSide.BUY, 1000, priority="80"),
        )
        session = ExecutionSession(
            date(2025, 2, 3),
            {
                "sh.600002": market("sh.600002"),
                "sh.600003": market("sh.600003"),
            },
        )
        result = run_order_book(initial, orders, (session,), fee_schedule=fees())
        self.assertEqual(result.final_portfolio.quantity("sh.600002"), 600)
        self.assertEqual(result.final_portfolio.quantity("sh.600003"), 500)


if __name__ == "__main__":
    unittest.main()
