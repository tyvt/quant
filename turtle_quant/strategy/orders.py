"""Signal-time order planning for the frozen monthly strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from enum import Enum
import re
from typing import Mapping

from turtle_quant.core.types import calculation_context, to_decimal
from turtle_quant.strategy.selection import MonthlySelection


_SECURITY_ID = re.compile(r"^(sh|sz)\.\d{6}$")


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PENDING_OUT_OF_COVERAGE = "PENDING_OUT_OF_COVERAGE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED_EXPIRED = "CANCELED_EXPIRED"


@dataclass(frozen=True)
class PlannedOrder:
    order_id: str
    signal_date: date
    first_execution_date: date
    security_id: str
    side: OrderSide
    requested_quantity: int
    priority_score: Decimal | None
    status: OrderStatus
    max_execution_days: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.order_id, str) or not self.order_id:
            raise ValueError("order_id must be non-empty")
        if type(self.signal_date) is not date or type(self.first_execution_date) is not date:
            raise ValueError("order dates must be dates")
        if self.first_execution_date <= self.signal_date:
            raise ValueError("first_execution_date must follow signal_date")
        if not _SECURITY_ID.fullmatch(self.security_id):
            raise ValueError("security_id must use canonical sh.600000 form")
        if not isinstance(self.side, OrderSide):
            raise ValueError("side must be OrderSide")
        if (
            isinstance(self.requested_quantity, bool)
            or not isinstance(self.requested_quantity, int)
            or self.requested_quantity <= 0
        ):
            raise ValueError("requested_quantity must be a positive integer")
        if self.priority_score is not None:
            object.__setattr__(self, "priority_score", to_decimal(self.priority_score))
        if not isinstance(self.status, OrderStatus):
            raise ValueError("status must be OrderStatus")
        if self.max_execution_days != 5:
            raise ValueError("max_execution_days is frozen at 5")


def plan_rebalance(
    selection: MonthlySelection,
    *,
    signal_date: date,
    first_execution_date: date,
    signal_nav: Decimal,
    signal_raw_closes: Mapping[str, Decimal],
    current_quantities: Mapping[str, int],
    market_coverage_end: date,
) -> tuple[PlannedOrder, ...]:
    """Freeze target shares from signal NAV and signal-day RAW closes."""

    if not selection.official_selection or selection.diagnostic_only:
        raise ValueError("orders require an official, non-diagnostic selection")
    if type(signal_date) is not date or type(first_execution_date) is not date:
        raise ValueError("signal and execution dates must be dates")
    if first_execution_date <= signal_date:
        raise ValueError("execution must occur after the signal close")
    if type(market_coverage_end) is not date:
        raise ValueError("market_coverage_end must be a date")
    nav = to_decimal(signal_nav)
    if nav <= 0:
        raise ValueError("signal_nav must be positive")

    current: dict[str, int] = {}
    for security_id, quantity in current_quantities.items():
        _validate_security_id(security_id)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise ValueError("current quantities must be non-negative integers")
        current[security_id] = quantity

    target: dict[str, int] = {}
    with calculation_context():
        for security_id, weight_raw in selection.target_weights.items():
            _validate_security_id(security_id)
            if security_id not in signal_raw_closes:
                raise ValueError(f"missing signal RAW close for {security_id}")
            weight = to_decimal(weight_raw)
            close = to_decimal(signal_raw_closes[security_id])
            if not Decimal("0") <= weight <= Decimal("0.05"):
                raise ValueError("target weight exceeds the frozen 5% cap")
            if close <= 0:
                raise ValueError("signal RAW close must be positive")
            lots = (nav * weight / close / Decimal("100")).to_integral_value(
                rounding=ROUND_FLOOR
            )
            target[security_id] = int(lots) * 100

    priority = {
        item.security_id: item.composite_score for item in selection.ranked_candidates
    }
    status = (
        OrderStatus.PENDING
        if first_execution_date <= market_coverage_end
        else OrderStatus.PENDING_OUT_OF_COVERAGE
    )
    sells: list[PlannedOrder] = []
    buys: list[PlannedOrder] = []
    for security_id in sorted(set(current) | set(target)):
        existing = current.get(security_id, 0)
        desired = target.get(security_id, 0)
        delta = desired - existing
        if delta == 0:
            continue
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        quantity = abs(delta)
        if side is OrderSide.BUY:
            quantity = quantity // 100 * 100
            if quantity == 0:
                continue
        planned = PlannedOrder(
            order_id=f"{signal_date.isoformat()}:{security_id}:{side.value}",
            signal_date=signal_date,
            first_execution_date=first_execution_date,
            security_id=security_id,
            side=side,
            requested_quantity=quantity,
            priority_score=priority.get(security_id),
            status=status,
        )
        (buys if side is OrderSide.BUY else sells).append(planned)
    sells.sort(key=lambda item: item.security_id)
    buys.sort(
        key=lambda item: (
            -(item.priority_score if item.priority_score is not None else Decimal("-Infinity")),
            item.security_id,
        )
    )
    return tuple(sells + buys)


def _validate_security_id(value: object) -> str:
    if not isinstance(value, str) or not _SECURITY_ID.fullmatch(value):
        raise ValueError("security_id must use canonical sh.600000 form")
    return value


__all__ = [
    "OrderSide",
    "OrderStatus",
    "PlannedOrder",
    "plan_rebalance",
]
