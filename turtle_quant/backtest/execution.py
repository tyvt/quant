"""Strict next-open execution, participation and historical costs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR

from turtle_quant.core.types import calculation_context, to_decimal
from turtle_quant.strategy.orders import OrderSide, OrderStatus, PlannedOrder


@dataclass(frozen=True)
class ParticipationDay:
    trade_date: date
    amount: Decimal | None
    paused: bool | None
    evidence_ref: str | None

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")
        if self.amount is not None:
            amount = to_decimal(self.amount)
            if amount < 0:
                raise ValueError("amount must be non-negative")
            object.__setattr__(self, "amount", amount)
        if self.paused is not None and type(self.paused) is not bool:
            raise ValueError("paused must be bool or None")
        if self.evidence_ref is not None and (
            not isinstance(self.evidence_ref, str) or not self.evidence_ref
        ):
            raise ValueError("evidence_ref must be non-empty or None")


@dataclass(frozen=True)
class ParticipationResult:
    complete: bool
    average_amount: Decimal | None
    max_daily_notional: Decimal | None
    issue_code: str | None = None
    window_end: date | None = None


def calculate_participation_limit(
    observations: tuple[ParticipationDay, ...],
    *,
    expected_trading_dates: tuple[date, ...],
) -> ParticipationResult:
    """Use exactly the preceding 20 expected trading dates and denominator 20."""

    expected = tuple(expected_trading_dates)
    if len(expected) != 20 or any(type(item) is not date for item in expected):
        raise ValueError("expected_trading_dates must contain exactly 20 dates")
    if tuple(sorted(expected)) != expected or len(set(expected)) != 20:
        raise ValueError("expected_trading_dates must be sorted and unique")
    rows = tuple(observations)
    if any(not isinstance(item, ParticipationDay) for item in rows):
        raise ValueError("observations must contain ParticipationDay values")
    by_date = {item.trade_date: item for item in rows}
    if len(by_date) != len(rows) or set(by_date) != set(expected):
        return _unknown_participation()

    amounts: list[Decimal] = []
    for day in expected:
        observation = by_date[day]
        if observation.evidence_ref is None or observation.paused is None:
            return _unknown_participation()
        if observation.paused:
            if observation.amount not in (None, Decimal("0")):
                return _unknown_participation()
            amounts.append(Decimal("0"))
        elif observation.amount is None:
            return _unknown_participation()
        else:
            amounts.append(observation.amount)
    with calculation_context():
        average = sum(amounts, Decimal("0")) / Decimal("20")
        return ParticipationResult(
            complete=True,
            average_amount=average,
            max_daily_notional=average * Decimal("0.05"),
            window_end=expected[-1],
        )


def _unknown_participation() -> ParticipationResult:
    return ParticipationResult(
        complete=False,
        average_amount=None,
        max_daily_notional=None,
        issue_code="PARTICIPATION_RATE_UNKNOWN",
    )


@dataclass(frozen=True)
class Tradeability:
    can_buy: bool | None
    can_sell: bool | None
    paused: bool | None
    at_upper_limit: bool | None
    at_lower_limit: bool | None
    evidence_ref: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "can_buy",
            "can_sell",
            "paused",
            "at_upper_limit",
            "at_lower_limit",
        ):
            value = getattr(self, field_name)
            if value is not None and type(value) is not bool:
                raise ValueError(f"{field_name} must be bool or None")
        if self.evidence_ref is not None and (
            not isinstance(self.evidence_ref, str) or not self.evidence_ref
        ):
            raise ValueError("evidence_ref must be non-empty or None")


@dataclass(frozen=True)
class FeeRate:
    effective_from: date
    brokerage_bps: Decimal
    minimum_commission: Decimal
    exchange_bps: Decimal
    transfer_bps: Decimal
    stamp_duty_bps: Decimal

    def __post_init__(self) -> None:
        if type(self.effective_from) is not date:
            raise ValueError("effective_from must be a date")
        for field_name in (
            "brokerage_bps",
            "minimum_commission",
            "exchange_bps",
            "transfer_bps",
            "stamp_duty_bps",
        ):
            value = to_decimal(getattr(self, field_name))
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True)
class FeeBreakdown:
    commission: Decimal
    exchange_fee: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal

    def __post_init__(self) -> None:
        for field_name in (
            "commission",
            "exchange_fee",
            "transfer_fee",
            "stamp_duty",
        ):
            value = to_decimal(getattr(self, field_name))
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
            object.__setattr__(self, field_name, value)

    @property
    def total(self) -> Decimal:
        return self.commission + self.exchange_fee + self.transfer_fee + self.stamp_duty


@dataclass(frozen=True)
class FeeSchedule:
    schedule_id: str
    rates: tuple[FeeRate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.schedule_id, str) or not self.schedule_id:
            raise ValueError("schedule_id must be non-empty")
        rates = tuple(self.rates)
        if not rates or any(not isinstance(item, FeeRate) for item in rates):
            raise ValueError("rates must contain FeeRate values")
        ordered = tuple(sorted(rates, key=lambda item: item.effective_from))
        if len({item.effective_from for item in ordered}) != len(ordered):
            raise ValueError("fee rates must have unique effective dates")
        object.__setattr__(self, "rates", ordered)

    def rate_on(self, day: date) -> FeeRate | None:
        if type(day) is not date:
            raise ValueError("day must be a date")
        visible = tuple(item for item in self.rates if item.effective_from <= day)
        return visible[-1] if visible else None

    def calculate(
        self,
        day: date,
        side: OrderSide,
        notional: Decimal,
    ) -> FeeBreakdown | None:
        rate = self.rate_on(day)
        if rate is None:
            return None
        value = to_decimal(notional)
        if value < 0:
            raise ValueError("notional must be non-negative")
        if not isinstance(side, OrderSide):
            raise ValueError("side must be OrderSide")
        with calculation_context():
            divisor = Decimal("10000")
            commission = max(
                rate.minimum_commission,
                value * rate.brokerage_bps / divisor,
            )
            return FeeBreakdown(
                commission=commission,
                exchange_fee=value * rate.exchange_bps / divisor,
                transfer_fee=value * rate.transfer_bps / divisor,
                stamp_duty=(
                    value * rate.stamp_duty_bps / divisor
                    if side is OrderSide.SELL
                    else Decimal("0")
                ),
            )


@dataclass(frozen=True)
class Fill:
    order_id: str
    security_id: str
    side: OrderSide
    execution_date: date
    quantity: int
    raw_open: Decimal
    execution_price: Decimal
    notional: Decimal
    slippage_cost: Decimal
    fees: FeeBreakdown
    cash_change: Decimal

    def __post_init__(self) -> None:
        if self.quantity <= 0 or isinstance(self.quantity, bool):
            raise ValueError("fill quantity must be positive")
        for field_name in (
            "raw_open",
            "execution_price",
            "notional",
            "slippage_cost",
            "cash_change",
        ):
            object.__setattr__(self, field_name, to_decimal(getattr(self, field_name)))
        if self.raw_open <= 0 or self.execution_price <= 0 or self.notional <= 0:
            raise ValueError("fill prices and notional must be positive")
        if self.slippage_cost < 0:
            raise ValueError("slippage_cost must be non-negative")

    @property
    def total_fees(self) -> Decimal:
        return self.fees.total


def create_fill(
    order: PlannedOrder,
    *,
    execution_date: date,
    raw_open: Decimal,
    quantity: int,
    fee_schedule: FeeSchedule,
) -> Fill:
    """Create the deterministic fill for an already-allocated quantity."""

    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
        or quantity > order.requested_quantity
    ):
        raise ValueError("allocated fill quantity is outside order bounds")
    if order.side is OrderSide.BUY and quantity % 100:
        raise ValueError("buy fill quantity must use 100-share lots")
    if type(execution_date) is not date:
        raise ValueError("execution_date must be a date")
    open_price = to_decimal(raw_open)
    if open_price <= 0:
        raise ValueError("raw_open must be positive")
    with calculation_context():
        execution_price = open_price * (
            Decimal("1.001")
            if order.side is OrderSide.BUY
            else Decimal("0.999")
        )
        notional = execution_price * Decimal(quantity)
        fees = fee_schedule.calculate(execution_date, order.side, notional)
        if fees is None:
            raise ValueError("fee schedule does not cover execution_date")
        cash_change = (
            -(notional + fees.total)
            if order.side is OrderSide.BUY
            else notional - fees.total
        )
        return Fill(
            order_id=order.order_id,
            security_id=order.security_id,
            side=order.side,
            execution_date=execution_date,
            quantity=quantity,
            raw_open=open_price,
            execution_price=execution_price,
            notional=notional,
            slippage_cost=abs(execution_price - open_price) * Decimal(quantity),
            fees=fees,
            cash_change=cash_change,
        )


@dataclass(frozen=True)
class ExecutionAttempt:
    status: OrderStatus
    remaining_quantity: int
    attempt_number: int
    fill: Fill | None
    issues: tuple[str, ...] = ()


def attempt_order(
    order: PlannedOrder,
    *,
    remaining_quantity: int,
    attempt_number: int,
    execution_date: date,
    raw_open: Decimal,
    tradeability: Tradeability,
    participation: ParticipationResult,
    fee_schedule: FeeSchedule,
    available_cash: Decimal,
    sellable_quantity: int,
) -> ExecutionAttempt:
    """Attempt one trading day; every blocked day consumes the five-day clock."""

    if order.status is OrderStatus.PENDING_OUT_OF_COVERAGE:
        return ExecutionAttempt(
            OrderStatus.PENDING_OUT_OF_COVERAGE,
            remaining_quantity,
            attempt_number,
            None,
            ("MARKET_OUT_OF_COVERAGE",),
        )
    if not 1 <= attempt_number <= order.max_execution_days:
        raise ValueError("attempt_number must be between 1 and 5")
    if execution_date < order.first_execution_date:
        raise ValueError("execution_date precedes first_execution_date")
    if remaining_quantity <= 0 or remaining_quantity > order.requested_quantity:
        raise ValueError("remaining_quantity is outside order bounds")
    open_price = to_decimal(raw_open)
    cash = to_decimal(available_cash)
    if open_price <= 0 or cash < 0:
        raise ValueError("raw_open must be positive and available_cash non-negative")
    if sellable_quantity < 0:
        raise ValueError("sellable_quantity must be non-negative")

    issues = _execution_issues(order.side, tradeability, participation, fee_schedule, execution_date)
    if issues:
        return _no_fill(order, remaining_quantity, attempt_number, issues)

    assert participation.max_daily_notional is not None
    with calculation_context():
        slippage_rate = Decimal("0.001")
        execution_price = open_price * (
            Decimal("1") + slippage_rate
            if order.side is OrderSide.BUY
            else Decimal("1") - slippage_rate
        )
        participation_quantity = int(
            (participation.max_daily_notional / execution_price).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        quantity = min(remaining_quantity, participation_quantity)
        if order.side is OrderSide.BUY:
            quantity = quantity // 100 * 100
            quantity = _fit_buy_to_cash(
                quantity,
                execution_price,
                execution_date,
                fee_schedule,
                cash,
            )
        else:
            quantity = min(quantity, sellable_quantity)
            if quantity == 0:
                return _no_fill(
                    order,
                    remaining_quantity,
                    attempt_number,
                    ("T_PLUS_ONE_BLOCKED",),
                )
        if quantity <= 0:
            return _no_fill(
                order,
                remaining_quantity,
                attempt_number,
                ("PARTICIPATION_OR_CASH_LIMIT_ZERO",),
            )
        fill = create_fill(
            order,
            execution_date=execution_date,
            raw_open=open_price,
            quantity=quantity,
            fee_schedule=fee_schedule,
        )
        remaining = remaining_quantity - quantity
        return ExecutionAttempt(
            status=(
                OrderStatus.FILLED
                if remaining == 0
                else OrderStatus.CANCELED_EXPIRED
                if attempt_number >= order.max_execution_days
                else OrderStatus.PARTIALLY_FILLED
            ),
            remaining_quantity=remaining,
            attempt_number=attempt_number,
            fill=fill,
        )


def _execution_issues(
    side: OrderSide,
    tradeability: Tradeability,
    participation: ParticipationResult,
    fee_schedule: FeeSchedule,
    day: date,
) -> tuple[str, ...]:
    if (
        not participation.complete
        or participation.window_end is None
        or participation.window_end >= day
    ):
        return (participation.issue_code or "PARTICIPATION_RATE_UNKNOWN",)
    if tradeability.evidence_ref is None or tradeability.paused is None:
        return ("TRADEABILITY_UNKNOWN",)
    if side is OrderSide.BUY and (
        tradeability.can_buy is None or tradeability.at_upper_limit is None
    ):
        return ("TRADEABILITY_UNKNOWN",)
    if side is OrderSide.SELL and (
        tradeability.can_sell is None or tradeability.at_lower_limit is None
    ):
        return ("TRADEABILITY_UNKNOWN",)
    if tradeability.paused:
        return ("PAUSED",)
    if side is OrderSide.BUY and (
        tradeability.can_buy is False or tradeability.at_upper_limit is True
    ):
        return ("BUY_BLOCKED",)
    if side is OrderSide.SELL and (
        tradeability.can_sell is False or tradeability.at_lower_limit is True
    ):
        return ("SELL_BLOCKED",)
    if fee_schedule.rate_on(day) is None:
        return ("COST_RATE_UNKNOWN",)
    return ()


def _fit_buy_to_cash(
    quantity: int,
    price: Decimal,
    day: date,
    schedule: FeeSchedule,
    cash: Decimal,
) -> int:
    while quantity > 0:
        notional = price * Decimal(quantity)
        fees = schedule.calculate(day, OrderSide.BUY, notional)
        assert fees is not None
        if notional + fees.total <= cash:
            return quantity
        quantity -= 100
    return 0


def _no_fill(
    order: PlannedOrder,
    remaining: int,
    attempt_number: int,
    issues: tuple[str, ...],
) -> ExecutionAttempt:
    return ExecutionAttempt(
        status=(
            OrderStatus.CANCELED_EXPIRED
            if attempt_number >= order.max_execution_days
            else OrderStatus.PENDING
        ),
        remaining_quantity=remaining,
        attempt_number=attempt_number,
        fill=None,
        issues=issues,
    )


__all__ = [
    "ExecutionAttempt",
    "FeeBreakdown",
    "FeeRate",
    "FeeSchedule",
    "Fill",
    "ParticipationDay",
    "ParticipationResult",
    "Tradeability",
    "attempt_order",
    "calculate_participation_limit",
    "create_fill",
]
