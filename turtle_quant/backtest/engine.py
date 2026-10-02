"""Deterministic order-book orchestration for synthetic v1.3.0 fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
from types import MappingProxyType
from typing import Mapping

from turtle_quant.backtest.execution import (
    FeeSchedule,
    Fill,
    ParticipationResult,
    Tradeability,
    attempt_order,
    create_fill,
)
from turtle_quant.backtest.hashing import canonical_row_stream, logical_content_hash
from turtle_quant.backtest.metrics import NavPoint
from turtle_quant.backtest.portfolio import (
    CashDividend,
    DelistingSettlement,
    PortfolioState,
    SplitEvent,
    UnsupportedCorporateAction,
    apply_cash_dividend,
    apply_fill,
    apply_split,
    settle_delisting,
)
from turtle_quant.core.types import to_decimal
from turtle_quant.strategy.orders import OrderSide, OrderStatus, PlannedOrder


@dataclass(frozen=True)
class ExecutionMarket:
    security_id: str
    raw_open: Decimal
    raw_close: Decimal | None
    close_evidence_ref: str | None
    tradeability: Tradeability
    participation: ParticipationResult

    def __post_init__(self) -> None:
        if not isinstance(self.security_id, str) or not self.security_id:
            raise ValueError("security_id must be non-empty")
        open_price = to_decimal(self.raw_open)
        if open_price <= 0:
            raise ValueError("raw_open must be positive")
        object.__setattr__(self, "raw_open", open_price)
        if self.raw_close is not None:
            close = to_decimal(self.raw_close)
            if close <= 0:
                raise ValueError("raw_close must be positive when present")
            object.__setattr__(self, "raw_close", close)
        if self.close_evidence_ref is not None and (
            not isinstance(self.close_evidence_ref, str) or not self.close_evidence_ref
        ):
            raise ValueError("close_evidence_ref must be non-empty or None")
        if not isinstance(self.tradeability, Tradeability):
            raise ValueError("tradeability must be Tradeability")
        if not isinstance(self.participation, ParticipationResult):
            raise ValueError("participation must be ParticipationResult")


@dataclass(frozen=True)
class ExecutionSession:
    trade_date: date
    markets: Mapping[str, ExecutionMarket]
    splits: tuple[SplitEvent, ...] = ()
    cash_dividends: tuple[CashDividend, ...] = ()
    delistings: tuple[DelistingSettlement, ...] = ()
    unsupported_actions: tuple[UnsupportedCorporateAction, ...] = ()

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")
        markets = dict(self.markets)
        if any(
            not isinstance(item, ExecutionMarket) or key != item.security_id
            for key, item in markets.items()
        ):
            raise ValueError("market mapping keys must match ExecutionMarket security IDs")
        object.__setattr__(self, "markets", MappingProxyType(dict(sorted(markets.items()))))
        for field_name, event_type, date_field in (
            ("splits", SplitEvent, "ex_date"),
            ("cash_dividends", CashDividend, "paid_on"),
            ("delistings", DelistingSettlement, "settled_on"),
            ("unsupported_actions", UnsupportedCorporateAction, "effective_on"),
        ):
            events = tuple(getattr(self, field_name))
            if any(
                not isinstance(event, event_type)
                or getattr(event, date_field) != self.trade_date
                for event in events
            ):
                raise ValueError(f"{field_name} must contain events dated trade_date")
            if len(set(events)) != len(events):
                raise ValueError(f"{field_name} must not repeat an event")
            object.__setattr__(self, field_name, events)
        if len({event.security_id for event in self.splits}) != len(self.splits):
            raise ValueError("only one split per security and session is supported")
        if len({event.security_id for event in self.delistings}) != len(self.delistings):
            raise ValueError("only one delisting per security and session is supported")


@dataclass(frozen=True)
class OrderOutcome:
    order_id: str
    signal_date: date
    first_execution_date: date
    security_id: str
    side: OrderSide
    priority_score: Decimal | None
    max_execution_days: int
    status: OrderStatus
    requested_quantity: int
    filled_quantity: int
    remaining_quantity: int
    attempts: int
    issues: tuple[str, ...]


@dataclass(frozen=True)
class HoldingSnapshot:
    trade_date: date
    security_id: str
    quantity: int
    close: Decimal
    market_value: Decimal
    stale_trading_days: int


@dataclass(frozen=True)
class BacktestEngineResult:
    order_outcomes: tuple[OrderOutcome, ...]
    fills: tuple[Fill, ...]
    holdings: tuple[HoldingSnapshot, ...]
    nav_points: tuple[NavPoint, ...]
    final_portfolio: PortfolioState
    complete: bool
    quality_flags: tuple[str, ...]

    def logical_hashes(self) -> Mapping[str, str]:
        order_rows = tuple(
            {
                "order_id": item.order_id,
                "signal_date": item.signal_date,
                "first_execution_date": item.first_execution_date,
                "security_id": item.security_id,
                "side": item.side,
                "priority_score": item.priority_score,
                "max_execution_days": item.max_execution_days,
                "status": item.status,
                "requested_quantity": item.requested_quantity,
                "filled_quantity": item.filled_quantity,
                "remaining_quantity": item.remaining_quantity,
                "attempts": item.attempts,
                "issues_json": json.dumps(item.issues, ensure_ascii=False, separators=(",", ":")),
            }
            for item in self.order_outcomes
        )
        fill_rows = tuple(
            {
                "order_id": fill.order_id,
                "execution_date": fill.execution_date,
                "security_id": fill.security_id,
                "side": fill.side,
                "quantity": fill.quantity,
                "raw_open": fill.raw_open,
                "execution_price": fill.execution_price,
                "notional": fill.notional,
                "slippage_cost": fill.slippage_cost,
                "commission": fill.fees.commission,
                "exchange_fee": fill.fees.exchange_fee,
                "transfer_fee": fill.fees.transfer_fee,
                "stamp_duty": fill.fees.stamp_duty,
                "cash_change": fill.cash_change,
            }
            for fill in self.fills
        )
        order_stream = canonical_row_stream(
            order_rows,
            schema_version="strategy-order-outcomes-v2",
            columns=(
                "order_id", "signal_date", "first_execution_date", "security_id", "side",
                "priority_score", "max_execution_days", "status", "requested_quantity",
                "filled_quantity", "remaining_quantity", "attempts", "issues_json",
            ),
            primary_key=("order_id",),
        )
        fill_stream = canonical_row_stream(
            fill_rows,
            schema_version="strategy-order-fills-v1",
            columns=(
                "order_id", "execution_date", "security_id", "side", "quantity",
                "raw_open", "execution_price", "notional", "slippage_cost", "commission",
                "exchange_fee", "transfer_fee", "stamp_duty", "cash_change",
            ),
            primary_key=("order_id", "execution_date"),
        )
        holding_rows = tuple(
            {
                "trade_date": item.trade_date,
                "security_id": item.security_id,
                "quantity": item.quantity,
                "close": item.close,
                "market_value": item.market_value,
                "stale_trading_days": item.stale_trading_days,
            }
            for item in self.holdings
        )
        nav_rows = tuple(
            {
                "trade_date": item.trade_date,
                "nav": item.nav,
                "cash": item.cash,
                "holdings_count": item.holdings_count,
            }
            for item in self.nav_points
        )
        return MappingProxyType(
            {
                "orders": hashlib.sha256((order_stream + "\n" + fill_stream).encode("utf-8")).hexdigest(),
                "holdings": logical_content_hash(
                    holding_rows,
                    schema_version="strategy-holdings-v1",
                    columns=(
                        "trade_date",
                        "security_id",
                        "quantity",
                        "close",
                        "market_value",
                        "stale_trading_days",
                    ),
                    primary_key=("trade_date", "security_id"),
                ),
                "nav": logical_content_hash(
                    nav_rows,
                    schema_version="strategy-nav-v1",
                    columns=("trade_date", "nav", "cash", "holdings_count"),
                    primary_key=("trade_date",),
                ),
            }
        )


@dataclass
class _OrderState:
    order: PlannedOrder
    remaining: int
    attempts: int = 0
    status: OrderStatus = OrderStatus.PENDING
    issues: tuple[str, ...] = ()


def run_order_book(
    initial_portfolio: PortfolioState,
    orders: tuple[PlannedOrder, ...],
    sessions: tuple[ExecutionSession, ...],
    *,
    fee_schedule: FeeSchedule,
    expected_trading_dates: tuple[date, ...],
) -> BacktestEngineResult:
    """Run deterministic sell-first attempts and close-of-day bookkeeping."""

    if not isinstance(initial_portfolio, PortfolioState):
        raise ValueError("initial_portfolio must be PortfolioState")
    planned = tuple(orders)
    if any(not isinstance(item, PlannedOrder) for item in planned):
        raise ValueError("orders must contain PlannedOrder values")
    if len({item.order_id for item in planned}) != len(planned):
        raise ValueError("order IDs must be unique")
    calendar = tuple(sessions)
    if any(not isinstance(item, ExecutionSession) for item in calendar):
        raise ValueError("sessions must contain ExecutionSession values")
    calendar = tuple(sorted(calendar, key=lambda item: item.trade_date))
    if len({item.trade_date for item in calendar}) != len(calendar):
        raise ValueError("execution session dates must be unique")
    expected = tuple(expected_trading_dates)
    if any(type(item) is not date for item in expected):
        raise ValueError("expected_trading_dates must contain dates")
    if tuple(sorted(expected)) != expected or len(set(expected)) != len(expected):
        raise ValueError("expected_trading_dates must be sorted and unique")
    if tuple(item.trade_date for item in calendar) != expected:
        raise ValueError("execution sessions must cover every expected trading date")
    if not isinstance(fee_schedule, FeeSchedule):
        raise ValueError("fee_schedule must be FeeSchedule")

    states = {
        item.order_id: _OrderState(
            order=item,
            remaining=item.requested_quantity,
            status=item.status,
        )
        for item in planned
    }
    portfolio = initial_portfolio
    fills: list[Fill] = []
    holdings: list[HoldingSnapshot] = []
    nav_points: list[NavPoint] = []
    quality_flags: set[str] = set(initial_portfolio.quality_flags)
    last_closes: dict[str, Decimal] = {}
    stale_days: dict[str, int] = {}

    for session in calendar:
        for event in sorted(session.splits, key=lambda item: item.security_id):
            portfolio = apply_split(portfolio, event)
            last_closes.pop(event.security_id, None)
            stale_days.pop(event.security_id, None)
            _invalidate_pending_action_orders(states, event.security_id)
        for event in sorted(session.unsupported_actions, key=lambda item: (item.security_id, item.action_type)):
            if portfolio.quantity(event.security_id) > 0:
                portfolio = PortfolioState(
                    portfolio.cash,
                    portfolio.lots,
                    False,
                    portfolio.quality_flags + ("UNSUPPORTED_CORPORATE_ACTION",),
                )
            _invalidate_pending_action_orders(states, event.security_id)
        for event in sorted(session.delistings, key=lambda item: item.security_id):
            _invalidate_pending_action_orders(states, event.security_id)
        active = tuple(
            sorted(
                (
                    state
                    for state in states.values()
                    if state.status
                    not in {OrderStatus.FILLED, OrderStatus.CANCELED_EXPIRED}
                    and state.order.first_execution_date <= session.trade_date
                ),
                key=_execution_priority,
            )
        )
        for state in tuple(
            item for item in active if item.order.side is OrderSide.SELL
        ):
            portfolio, fill = _attempt_sell(
                portfolio,
                state,
                session,
                fee_schedule,
            )
            if fill is not None:
                fills.append(fill)
        portfolio, buy_fills = _attempt_buys(
            portfolio,
            tuple(item for item in active if item.order.side is OrderSide.BUY),
            session,
            fee_schedule,
        )
        fills.extend(buy_fills)

        for event in sorted(session.cash_dividends, key=lambda item: (item.security_id, item.evidence_ref or "")):
            portfolio = apply_cash_dividend(portfolio, event)
        for event in sorted(session.delistings, key=lambda item: item.security_id):
            portfolio = settle_delisting(
                portfolio,
                security_id=event.security_id,
                settled_on=event.settled_on,
                cash_per_share=event.cash_per_share,
                evidence_ref=event.evidence_ref,
            )

        portfolio, day_holdings, nav_point, day_flags = _mark_close(
            portfolio,
            session,
            last_closes,
            stale_days,
        )
        holdings.extend(day_holdings)
        quality_flags.update(day_flags)
        if nav_point is not None:
            nav_points.append(nav_point)

    quality_flags.update(portfolio.quality_flags)

    outcomes = tuple(
        OrderOutcome(
            order_id=state.order.order_id,
            signal_date=state.order.signal_date,
            first_execution_date=state.order.first_execution_date,
            security_id=state.order.security_id,
            side=state.order.side,
            priority_score=state.order.priority_score,
            max_execution_days=state.order.max_execution_days,
            status=state.status,
            requested_quantity=state.order.requested_quantity,
            filled_quantity=state.order.requested_quantity - state.remaining,
            remaining_quantity=state.remaining,
            attempts=state.attempts,
            issues=state.issues,
        )
        for state in sorted(states.values(), key=lambda item: item.order.order_id)
    )
    for outcome in outcomes:
        quality_flags.update(
            issue for issue in outcome.issues
            if issue in {
                "MARKET_DATA_UNKNOWN",
                "PARTICIPATION_RATE_UNKNOWN",
                "TRADEABILITY_UNKNOWN",
                "COST_RATE_UNKNOWN",
                "CORPORATE_ACTION_ORDER_UNKNOWN",
            }
        )
        if outcome.status is OrderStatus.PENDING_OUT_OF_COVERAGE:
            quality_flags.add("MARKET_OUT_OF_COVERAGE")
    return BacktestEngineResult(
        order_outcomes=outcomes,
        fills=tuple(fills),
        holdings=tuple(holdings),
        nav_points=tuple(nav_points),
        final_portfolio=portfolio,
        complete=portfolio.complete and not quality_flags,
        quality_flags=tuple(sorted(quality_flags)),
    )


def _invalidate_pending_action_orders(states: Mapping[str, _OrderState], security_id: str) -> None:
    for state in states.values():
        if state.order.security_id != security_id or state.status in {
            OrderStatus.FILLED, OrderStatus.CANCELED_EXPIRED
        }:
            continue
        state.status = OrderStatus.CANCELED_EXPIRED
        state.issues = tuple(sorted(set(state.issues + ("CORPORATE_ACTION_ORDER_UNKNOWN",))))


def _execution_priority(state: _OrderState) -> tuple[int, Decimal, str, str]:
    if state.order.side is OrderSide.SELL:
        return (0, Decimal("0"), state.order.security_id, state.order.order_id)
    score = state.order.priority_score or Decimal("0")
    return (1, -score, state.order.security_id, state.order.order_id)


def _attempt_sell(
    portfolio: PortfolioState,
    state: _OrderState,
    session: ExecutionSession,
    fee_schedule: FeeSchedule,
) -> tuple[PortfolioState, Fill | None]:
    if state.status is OrderStatus.PENDING_OUT_OF_COVERAGE:
        return portfolio, None
    if state.attempts >= state.order.max_execution_days:
        return portfolio, None
    state.attempts += 1
    market = session.markets.get(state.order.security_id)
    if market is None:
        _record_no_market(state)
        return portfolio, None
    attempt = attempt_order(
        state.order,
        remaining_quantity=state.remaining,
        attempt_number=state.attempts,
        execution_date=session.trade_date,
        raw_open=market.raw_open,
        tradeability=market.tradeability,
        participation=market.participation,
        fee_schedule=fee_schedule,
        available_cash=portfolio.cash,
        sellable_quantity=portfolio.sellable_quantity(
            state.order.security_id, session.trade_date
        ),
    )
    state.remaining = attempt.remaining_quantity
    state.status = attempt.status
    state.issues = tuple(sorted(set(state.issues + attempt.issues)))
    if attempt.fill is None:
        return portfolio, None
    return apply_fill(portfolio, attempt.fill), attempt.fill


def _attempt_buys(
    portfolio: PortfolioState,
    states: tuple[_OrderState, ...],
    session: ExecutionSession,
    fee_schedule: FeeSchedule,
) -> tuple[PortfolioState, tuple[Fill, ...]]:
    tentative: list[tuple[_OrderState, ExecutionMarket, Fill]] = []
    for state in states:
        if state.status is OrderStatus.PENDING_OUT_OF_COVERAGE:
            continue
        if state.attempts >= state.order.max_execution_days:
            continue
        state.attempts += 1
        market = session.markets.get(state.order.security_id)
        if market is None:
            _record_no_market(state)
            continue
        attempt = attempt_order(
            state.order,
            remaining_quantity=state.remaining,
            attempt_number=state.attempts,
            execution_date=session.trade_date,
            raw_open=market.raw_open,
            tradeability=market.tradeability,
            participation=market.participation,
            fee_schedule=fee_schedule,
            available_cash=Decimal("1E+50"),
            sellable_quantity=0,
        )
        state.issues = tuple(sorted(set(state.issues + attempt.issues)))
        if attempt.fill is None:
            state.status = attempt.status
            continue
        tentative.append((state, market, attempt.fill))

    allocations = _allocate_buy_quantities(
        tentative,
        portfolio.cash,
        session.trade_date,
        fee_schedule,
    )
    fills: list[Fill] = []
    for state, market, maximum_fill in tentative:
        quantity = allocations[state.order.order_id]
        if quantity == 0:
            state.issues = tuple(sorted(set(state.issues + ("CASH_LIMIT_ZERO",))))
            state.status = (
                OrderStatus.CANCELED_EXPIRED
                if state.attempts >= state.order.max_execution_days
                else OrderStatus.PENDING
            )
            continue
        fill = create_fill(
            state.order,
            execution_date=session.trade_date,
            raw_open=market.raw_open,
            quantity=quantity,
            fee_schedule=fee_schedule,
        )
        if -fill.cash_change > portfolio.cash:
            raise AssertionError("proportional buy allocation exceeded available cash")
        portfolio = apply_fill(portfolio, fill)
        fills.append(fill)
        state.remaining -= quantity
        state.status = (
            OrderStatus.FILLED
            if state.remaining == 0
            else OrderStatus.CANCELED_EXPIRED
            if state.attempts >= state.order.max_execution_days
            else OrderStatus.PARTIALLY_FILLED
        )
        if quantity > maximum_fill.quantity:
            raise AssertionError("buy allocation exceeded participation-limited quantity")
    return portfolio, tuple(fills)


def _allocate_buy_quantities(
    tentative: list[tuple[_OrderState, ExecutionMarket, Fill]],
    cash: Decimal,
    day: date,
    fee_schedule: FeeSchedule,
) -> dict[str, int]:
    if not tentative:
        return {}
    maximum = {
        state.order.order_id: fill.quantity for state, _market, fill in tentative
    }
    total_required = sum((-fill.cash_change for _state, _market, fill in tentative), Decimal("0"))
    if total_required <= cash:
        return maximum

    ratio = cash / total_required
    allocations = {
        state.order.order_id: int(
            (Decimal(fill.quantity) * ratio / Decimal("100")).to_integral_value(
                rounding="ROUND_FLOOR"
            )
        )
        * 100
        for state, _market, fill in tentative
    }

    def allocation_cost(state: _OrderState, market: ExecutionMarket, quantity: int) -> Decimal:
        if quantity == 0:
            return Decimal("0")
        return -create_fill(
            state.order,
            execution_date=day,
            raw_open=market.raw_open,
            quantity=quantity,
            fee_schedule=fee_schedule,
        ).cash_change

    costs = {
        state.order.order_id: allocation_cost(
            state, market, allocations[state.order.order_id]
        )
        for state, market, _fill in tentative
    }
    spent = sum(costs.values(), Decimal("0"))
    made_progress = True
    while made_progress:
        made_progress = False
        for state, market, _fill in tentative:
            order_id = state.order.order_id
            proposed = allocations[order_id] + 100
            if proposed > maximum[order_id]:
                continue
            proposed_cost = allocation_cost(state, market, proposed)
            increment = proposed_cost - costs[order_id]
            if spent + increment <= cash:
                allocations[order_id] = proposed
                costs[order_id] = proposed_cost
                spent += increment
                made_progress = True
    return allocations


def _record_no_market(state: _OrderState) -> None:
    state.issues = tuple(sorted(set(state.issues + ("MARKET_DATA_UNKNOWN",))))
    state.status = (
        OrderStatus.CANCELED_EXPIRED
        if state.attempts >= state.order.max_execution_days
        else OrderStatus.PENDING
    )


def _mark_close(
    portfolio: PortfolioState,
    session: ExecutionSession,
    last_closes: dict[str, Decimal],
    stale_days: dict[str, int],
) -> tuple[PortfolioState, tuple[HoldingSnapshot, ...], NavPoint | None, tuple[str, ...]]:
    snapshots: list[HoldingSnapshot] = []
    flags: set[str] = set()
    market_value_total = Decimal("0")
    security_ids = sorted({item.security_id for item in portfolio.lots})
    for security_id in security_ids:
        market = session.markets.get(security_id)
        close: Decimal | None = None
        stale = 0
        if (
            market is not None
            and market.raw_close is not None
            and market.close_evidence_ref is not None
        ):
            close = market.raw_close
            last_closes[security_id] = close
            stale_days[security_id] = 0
        elif (
            market is not None
            and market.tradeability.paused is True
            and market.tradeability.evidence_ref is not None
            and security_id in last_closes
        ):
            close = last_closes[security_id]
            stale_days[security_id] = stale_days.get(security_id, 0) + 1
            stale = stale_days[security_id]
        else:
            flags.add("NAV_PRICE_UNKNOWN")
        if close is None:
            continue
        quantity = portfolio.quantity(security_id)
        market_value = close * Decimal(quantity)
        market_value_total += market_value
        snapshots.append(
            HoldingSnapshot(
                trade_date=session.trade_date,
                security_id=security_id,
                quantity=quantity,
                close=close,
                market_value=market_value,
                stale_trading_days=stale,
            )
        )
    if flags:
        portfolio = PortfolioState(
            portfolio.cash,
            portfolio.lots,
            False,
            portfolio.quality_flags + tuple(flags),
        )
        return portfolio, tuple(snapshots), None, tuple(flags)
    nav = portfolio.cash + market_value_total
    if nav <= 0:
        flags.add("NAV_NON_POSITIVE")
        portfolio = PortfolioState(
            portfolio.cash,
            portfolio.lots,
            False,
            portfolio.quality_flags + tuple(flags),
        )
        return portfolio, tuple(snapshots), None, tuple(flags)
    return (
        portfolio,
        tuple(snapshots),
        NavPoint(session.trade_date, nav, portfolio.cash, len(security_ids)),
        (),
    )


__all__ = [
    "BacktestEngineResult",
    "ExecutionMarket",
    "ExecutionSession",
    "HoldingSnapshot",
    "OrderOutcome",
    "run_order_book",
]
