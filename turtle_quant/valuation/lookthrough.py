"""Look-through return based on shared distributable-cash capacity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from turtle_quant.core.result import ResultStatus
from turtle_quant.core.types import UnitRatio, calculation_context, to_decimal


@dataclass(frozen=True)
class DividendEvent:
    paid_on: date | None
    amount: Decimal | None
    is_ordinary: bool | None
    is_paid: bool | None


@dataclass(frozen=True)
class BuybackEvent:
    executed_on: date | None
    amount: Decimal | None
    cancellation_verified: bool | None
    is_executed: bool | None = True


@dataclass(frozen=True)
class BuybackQualification:
    """Verified input for the main-path shared-capacity calculation."""

    status: ResultStatus
    qualified_buybacks: Decimal | None
    executed_buyback_365d: Decimal | None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))


def aggregate_dividends(
    events: tuple[DividendEvent, ...], as_of: date
) -> Decimal | None:
    """Aggregate ordinary paid dividends, preserving relevant unknowns."""
    with calculation_context():
        window_start = as_of - timedelta(days=365)
        total = Decimal("0")
        for event in events:
            if not (
                event.is_ordinary is True
                or event.is_ordinary is False
                or event.is_ordinary is None
            ):
                raise ValueError("is_ordinary must be true, false, or unknown")
            if not (
                event.is_paid is True
                or event.is_paid is False
                or event.is_paid is None
            ):
                raise ValueError("is_paid must be true, false, or unknown")

            # A definitively special or unpaid event cannot contribute to D,
            # so its other unknown fields are irrelevant.
            if event.is_ordinary is False or event.is_paid is False:
                continue
            if event.paid_on is None:
                return None
            if type(event.paid_on) is not date:
                raise ValueError("paid_on must be a date or unknown")
            if not window_start < event.paid_on <= as_of:
                continue
            if (
                event.is_ordinary is None
                or event.is_paid is None
                or event.amount is None
            ):
                return None
            amount = to_decimal(event.amount)
            if amount < 0:
                raise ValueError("dividend amount must be non-negative")
            total += amount
        return total


def aggregate_buybacks_365d(
    events: tuple[BuybackEvent, ...], as_of: date
) -> Decimal | None:
    """Aggregate verified buybacks, preserving relevant unknown states."""
    with calculation_context():
        window_start = as_of - timedelta(days=365)
        total = Decimal("0")
        for event in events:
            if not (
                event.is_executed is True
                or event.is_executed is False
                or event.is_executed is None
            ):
                raise ValueError("is_executed must be true, false, or unknown")
            if not (
                event.cancellation_verified is True
                or event.cancellation_verified is False
                or event.cancellation_verified is None
            ):
                raise ValueError(
                    "cancellation_verified must be true, false, or unknown"
                )
            if (
                event.is_executed is False
                or event.cancellation_verified is False
            ):
                continue
            if event.executed_on is None:
                return None
            if type(event.executed_on) is not date:
                raise ValueError("executed_on must be a date or unknown")
            if not window_start <= event.executed_on <= as_of:
                continue
            if (
                event.is_executed is None
                or event.cancellation_verified is None
                or event.amount is None
            ):
                return None
            amount = to_decimal(event.amount)
            if amount < 0:
                raise ValueError("buyback amount must be non-negative")
            total += amount
        return total


def qualify_buybacks(
    events: tuple[BuybackEvent, ...],
    *,
    as_of: date,
    latest_complete_calendar_year_amount: Decimal | None,
    latest_calendar_year_coverage_complete: bool,
) -> BuybackQualification:
    """Qualify recurring buybacks for the main GG path.

    The observed 365-day amount is always reported separately. The qualified
    amount remains UNKNOWN when the required latest-complete-calendar-year
    coverage cannot be verified; it is never silently substituted with zero.
    """
    executed_365d = aggregate_buybacks_365d(events, as_of)
    if (
        not latest_calendar_year_coverage_complete
        or latest_complete_calendar_year_amount is None
    ):
        return BuybackQualification(
            status=ResultStatus.UNKNOWN,
            qualified_buybacks=None,
            executed_buyback_365d=executed_365d,
            reasons=("calendar_year_coverage_unknown",),
        )
    if executed_365d is None:
        return BuybackQualification(
            status=ResultStatus.UNKNOWN,
            qualified_buybacks=None,
            executed_buyback_365d=None,
            reasons=("buyback_event_state_unknown",),
        )

    # RULE_SPEC intentionally defines this as an exact 3 × 365-day window,
    # not three calendar years; leap-day expansion would change the rule.
    three_year_start = as_of - timedelta(days=3 * 365)
    verified_events: list[BuybackEvent] = []
    for event in events:
        if (
            event.is_executed is False
            or event.cancellation_verified is False
        ):
            continue
        if event.executed_on is None:
            return BuybackQualification(
                status=ResultStatus.UNKNOWN,
                qualified_buybacks=None,
                executed_buyback_365d=executed_365d,
                reasons=("buyback_event_state_unknown",),
            )
        if type(event.executed_on) is not date:
            raise ValueError("executed_on must be a date or unknown")
        if not three_year_start <= event.executed_on <= as_of:
            continue
        if (
            event.is_executed is None
            or event.cancellation_verified is None
        ):
            return BuybackQualification(
                status=ResultStatus.UNKNOWN,
                qualified_buybacks=None,
                executed_buyback_365d=executed_365d,
                reasons=("buyback_event_state_unknown",),
            )
        verified_events.append(event)
    execution_days = {event.executed_on for event in verified_events}
    is_sustained = False
    if verified_events:
        earliest = min(execution_days)
        latest = max(execution_days)
        is_sustained = (
            len(execution_days) >= 3
            and (latest - earliest).days >= 180
            and len({event.executed_on.year for event in verified_events}) >= 2
            and latest >= as_of - timedelta(days=120)
        )

    if not is_sustained:
        return BuybackQualification(
            status=ResultStatus.PASS,
            qualified_buybacks=Decimal("0"),
            executed_buyback_365d=executed_365d,
            reasons=("buyback_continuity_not_met",),
        )

    return BuybackQualification(
        status=ResultStatus.PASS,
        qualified_buybacks=min(
            executed_365d,
            to_decimal(latest_complete_calendar_year_amount),
        ),
        executed_buyback_365d=executed_365d,
    )


@dataclass(frozen=True)
class LookthroughInputs:
    capacity: Decimal | None
    dividends: Decimal | None
    qualified_buybacks: Decimal | None
    market_value: Decimal | None
    price: Decimal | None
    required_return_pct: Decimal | None
    tax_rate: UnitRatio


@dataclass(frozen=True)
class LookthroughResult:
    status: ResultStatus
    missing_fields: tuple[str, ...] = ()
    dividend_allocation: Decimal | None = None
    buyback_allocation: Decimal | None = None
    shareholder_cash_net: Decimal | None = None
    gg_pct: Decimal | None = None
    kk_pct: Decimal | None = None
    observe_price: Decimal | None = None
    heavy_price: Decimal | None = None
    standard_price: Decimal | None = None


def calculate_lookthrough(inputs: LookthroughInputs) -> LookthroughResult:
    """Calculate GG and price ladder without substituting missing cash events."""
    with calculation_context():
        return _calculate_lookthrough(inputs)


def _calculate_lookthrough(inputs: LookthroughInputs) -> LookthroughResult:
    missing_fields = tuple(
        field_name
        for field_name, value in (
            ("capacity", inputs.capacity),
            ("dividends", inputs.dividends),
            ("qualified_buybacks", inputs.qualified_buybacks),
            ("market_value", inputs.market_value),
            ("price", inputs.price),
            ("required_return_pct", inputs.required_return_pct),
        )
        if value is None
    )
    if missing_fields:
        return LookthroughResult(
            status=ResultStatus.UNKNOWN,
            missing_fields=missing_fields,
        )

    capacity = to_decimal(inputs.capacity)
    dividends = to_decimal(inputs.dividends)
    qualified_buybacks = to_decimal(inputs.qualified_buybacks)
    market_value = to_decimal(inputs.market_value)
    price = to_decimal(inputs.price)
    required_return = to_decimal(inputs.required_return_pct)
    if market_value <= 0:
        raise ValueError("market_value must be positive")
    if price <= 0:
        raise ValueError("price must be positive")
    if required_return <= 0:
        raise ValueError("required_return_pct must be positive")

    distributable_capacity = max(capacity, Decimal("0"))
    dividend_allocation = min(max(dividends, Decimal("0")), distributable_capacity)
    remaining_capacity = max(Decimal("0"), distributable_capacity - dividend_allocation)
    buyback_allocation = min(
        max(qualified_buybacks, Decimal("0")),
        remaining_capacity,
    )
    shareholder_cash_net = (
        dividend_allocation * (Decimal("1") - inputs.tax_rate.value)
        + buyback_allocation
    )
    gg_pct = shareholder_cash_net / market_value * Decimal("100")
    kk_pct = gg_pct - required_return

    if gg_pct <= 0:
        return LookthroughResult(
            status=ResultStatus.FAIL,
            dividend_allocation=dividend_allocation,
            buyback_allocation=buyback_allocation,
            shareholder_cash_net=shareholder_cash_net,
            gg_pct=gg_pct,
            kk_pct=kk_pct,
        )

    observe_price = price * gg_pct / required_return
    heavy_price = price * gg_pct / max(Decimal("10"), required_return)
    standard_price = (observe_price + heavy_price) / Decimal("2")
    return LookthroughResult(
        status=(
            ResultStatus.PASS
            if gg_pct >= required_return
            else ResultStatus.FAIL
        ),
        dividend_allocation=dividend_allocation,
        buyback_allocation=buyback_allocation,
        shareholder_cash_net=shareholder_cash_net,
        gg_pct=gg_pct,
        kk_pct=kk_pct,
        observe_price=observe_price,
        heavy_price=heavy_price,
        standard_price=standard_price,
    )
