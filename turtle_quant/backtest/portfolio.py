"""Immutable portfolio accounting with explicit T+1 and corporate actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from turtle_quant.backtest.execution import Fill
from turtle_quant.core.types import calculation_context, to_decimal
from turtle_quant.strategy.orders import OrderSide


@dataclass(frozen=True)
class PositionLot:
    security_id: str
    quantity: int
    acquired_on: date
    unit_cost: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.security_id, str) or not self.security_id:
            raise ValueError("security_id must be non-empty")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        if type(self.acquired_on) is not date:
            raise ValueError("acquired_on must be a date")
        cost = to_decimal(self.unit_cost)
        if cost < 0:
            raise ValueError("unit_cost must be non-negative")
        object.__setattr__(self, "unit_cost", cost)


@dataclass(frozen=True)
class PortfolioState:
    cash: Decimal
    lots: tuple[PositionLot, ...]
    complete: bool = True
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        cash = to_decimal(self.cash)
        if cash < 0:
            raise ValueError("cash must be non-negative")
        lots = tuple(self.lots)
        if any(not isinstance(item, PositionLot) for item in lots):
            raise ValueError("lots must contain PositionLot values")
        lots = tuple(sorted(lots, key=lambda item: (item.security_id, item.acquired_on, item.unit_cost)))
        if type(self.complete) is not bool:
            raise ValueError("complete must be bool")
        flags = tuple(self.quality_flags)
        if any(not isinstance(item, str) or not item for item in flags):
            raise ValueError("quality_flags must contain non-empty strings")
        object.__setattr__(self, "cash", cash)
        object.__setattr__(self, "lots", lots)
        object.__setattr__(self, "quality_flags", tuple(sorted(set(flags))))

    def quantity(self, security_id: str) -> int:
        return sum(item.quantity for item in self.lots if item.security_id == security_id)

    def sellable_quantity(self, security_id: str, on_date: date) -> int:
        if type(on_date) is not date:
            raise ValueError("on_date must be a date")
        return sum(
            item.quantity
            for item in self.lots
            if item.security_id == security_id and item.acquired_on < on_date
        )


def apply_fill(state: PortfolioState, fill: Fill) -> PortfolioState:
    """Apply one already-validated fill, consuming oldest sellable lots."""

    if fill.side is OrderSide.BUY:
        cash = state.cash + fill.cash_change
        if cash < 0:
            raise ValueError("buy fill would make cash negative")
        lots = state.lots + (
            PositionLot(
                fill.security_id,
                fill.quantity,
                fill.execution_date,
                (fill.notional + fill.total_fees) / Decimal(fill.quantity),
            ),
        )
        return PortfolioState(cash, lots, state.complete, state.quality_flags)

    if state.sellable_quantity(fill.security_id, fill.execution_date) < fill.quantity:
        raise ValueError("sell fill exceeds T+1 sellable quantity")
    remaining = fill.quantity
    lots: list[PositionLot] = []
    for lot in state.lots:
        if (
            remaining > 0
            and lot.security_id == fill.security_id
            and lot.acquired_on < fill.execution_date
        ):
            consumed = min(remaining, lot.quantity)
            remaining -= consumed
            if consumed < lot.quantity:
                lots.append(
                    PositionLot(
                        lot.security_id,
                        lot.quantity - consumed,
                        lot.acquired_on,
                        lot.unit_cost,
                    )
                )
        else:
            lots.append(lot)
    if remaining:
        raise AssertionError("sellable quantity check and lot consumption diverged")
    return PortfolioState(
        state.cash + fill.cash_change,
        tuple(lots),
        state.complete,
        state.quality_flags,
    )


@dataclass(frozen=True)
class CashDividend:
    security_id: str
    paid_on: date | None
    amount_per_share: Decimal | None
    is_paid: bool | None
    evidence_ref: str | None
    record_date: date | None = None
    entitled_quantity: int | None = None
    entitlement_evidence_ref: str | None = None


def apply_cash_dividend(state: PortfolioState, event: CashDividend) -> PortfolioState:
    if event.is_paid is False:
        return state
    if (
        event.is_paid is not True
        or event.paid_on is None
        or event.amount_per_share is None
        or not event.evidence_ref
    ):
        return _incomplete(state, "DIVIDEND_STATE_UNKNOWN")
    if type(event.paid_on) is not date:
        raise ValueError("paid_on must be a date")
    if (
        event.record_date is None
        or event.entitled_quantity is None
        or not event.entitlement_evidence_ref
    ):
        return _incomplete(state, "DIVIDEND_ENTITLEMENT_UNKNOWN")
    if type(event.record_date) is not date or event.record_date > event.paid_on:
        raise ValueError("record_date must be a date no later than paid_on")
    if (
        isinstance(event.entitled_quantity, bool)
        or not isinstance(event.entitled_quantity, int)
        or event.entitled_quantity < 0
    ):
        raise ValueError("entitled_quantity must be a non-negative integer")
    amount = to_decimal(event.amount_per_share)
    if amount < 0:
        raise ValueError("amount_per_share must be non-negative")
    cash = state.cash + amount * Decimal(event.entitled_quantity)
    return PortfolioState(cash, state.lots, state.complete, state.quality_flags)


@dataclass(frozen=True)
class SplitEvent:
    security_id: str
    ex_date: date
    share_ratio: Decimal
    evidence_ref: str


@dataclass(frozen=True)
class DelistingSettlement:
    security_id: str
    settled_on: date
    cash_per_share: Decimal | None
    evidence_ref: str | None


@dataclass(frozen=True)
class UnsupportedCorporateAction:
    security_id: str
    effective_on: date
    action_type: str
    evidence_ref: str | None


def apply_split(state: PortfolioState, event: SplitEvent) -> PortfolioState:
    if type(event.ex_date) is not date:
        raise ValueError("ex_date must be a date")
    if not isinstance(event.evidence_ref, str) or not event.evidence_ref:
        return _incomplete(state, "SPLIT_EVIDENCE_UNKNOWN")
    ratio = to_decimal(event.share_ratio)
    if ratio <= 0:
        raise ValueError("share_ratio must be positive")
    lots: list[PositionLot] = []
    with calculation_context():
        for lot in state.lots:
            if lot.security_id != event.security_id:
                lots.append(lot)
                continue
            quantity = Decimal(lot.quantity) * ratio
            if quantity != quantity.to_integral_value():
                raise ValueError("split produces a fractional share quantity")
            lots.append(
                PositionLot(
                    lot.security_id,
                    int(quantity),
                    lot.acquired_on,
                    lot.unit_cost / ratio,
                )
            )
    return PortfolioState(state.cash, tuple(lots), state.complete, state.quality_flags)


def settle_delisting(
    state: PortfolioState,
    *,
    security_id: str,
    settled_on: date,
    cash_per_share: Decimal | None,
    evidence_ref: str | None,
) -> PortfolioState:
    if type(settled_on) is not date:
        raise ValueError("settled_on must be a date")
    if cash_per_share is None or evidence_ref is None:
        return _incomplete(state, "DELISTING_EXIT_UNKNOWN")
    amount = to_decimal(cash_per_share)
    if amount < 0:
        raise ValueError("cash_per_share must be non-negative")
    quantity = state.quantity(security_id)
    lots = tuple(item for item in state.lots if item.security_id != security_id)
    return PortfolioState(
        state.cash + amount * Decimal(quantity),
        lots,
        state.complete,
        state.quality_flags,
    )


def _incomplete(state: PortfolioState, flag: str) -> PortfolioState:
    return PortfolioState(
        state.cash,
        state.lots,
        False,
        state.quality_flags + (flag,),
    )


__all__ = [
    "CashDividend",
    "DelistingSettlement",
    "PortfolioState",
    "PositionLot",
    "SplitEvent",
    "UnsupportedCorporateAction",
    "apply_cash_dividend",
    "apply_fill",
    "apply_split",
    "settle_delisting",
]
