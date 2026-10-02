"""Evidence-complete market-position profile from RULE_SPEC v1.3.0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from turtle_quant.core.result import ResultStatus
from turtle_quant.core.types import calculation_context, to_decimal


@dataclass(frozen=True)
class PositionDay:
    """One expected trading day in an ADJUSTED_TO_AS_OF price view."""

    trade_date: date
    adjusted_close: Decimal | None
    paused: bool | None
    evidence_ref: str | None

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")
        if self.adjusted_close is not None:
            value = to_decimal(self.adjusted_close)
            object.__setattr__(self, "adjusted_close", value)
        if self.paused is not None and type(self.paused) is not bool:
            raise ValueError("paused must be bool or None")
        if self.evidence_ref is not None and (
            not isinstance(self.evidence_ref, str) or not self.evidence_ref
        ):
            raise ValueError("evidence_ref must be non-empty or None")


@dataclass(frozen=True)
class MarketPositionResult:
    status: ResultStatus
    sample_size: int
    position_pct: Decimal | None = None
    drawdown_from_high_pct: Decimal | None = None
    market_position_score: Decimal | None = None
    label: str | None = None
    quality_flags: tuple[str, ...] = ()
    factor_view_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_flags", tuple(sorted(set(self.quality_flags))))


def analyze_market_position(
    days: tuple[PositionDay, ...],
    *,
    as_of: date,
    expected_trading_dates: tuple[date, ...],
    valuation_price: Decimal,
    factor_view_hash: str,
    valuation_factor_view_hash: str,
) -> MarketPositionResult:
    """Calculate the 756/504-day position against an explicit trading calendar."""

    if type(as_of) is not date:
        raise ValueError("as_of must be a date")
    price = to_decimal(valuation_price)
    if price <= 0:
        raise ValueError("valuation_price must be positive")
    _hash_identity(factor_view_hash, "factor_view_hash")
    _hash_identity(valuation_factor_view_hash, "valuation_factor_view_hash")
    if factor_view_hash != valuation_factor_view_hash:
        return MarketPositionResult(
            status=ResultStatus.NEEDS_REVIEW,
            sample_size=0,
            quality_flags=("FACTOR_VIEW_MISMATCH",),
            factor_view_hash=factor_view_hash,
        )

    expected = tuple(expected_trading_dates)
    if not expected or any(type(item) is not date for item in expected):
        raise ValueError("expected_trading_dates must contain dates")
    if tuple(sorted(expected)) != expected or len(set(expected)) != len(expected):
        raise ValueError("expected_trading_dates must be sorted and unique")
    if expected[-1] != as_of:
        raise ValueError("expected_trading_dates must end at as_of")
    observations = tuple(days)
    if any(not isinstance(item, PositionDay) for item in observations):
        raise ValueError("days must contain PositionDay values")
    visible = tuple(item for item in observations if item.trade_date <= as_of)
    dates = tuple(item.trade_date for item in visible)
    if len(set(dates)) != len(dates):
        raise ValueError("position days must have unique trading dates")
    window_dates = expected[-756:]
    by_date = {item.trade_date: item for item in visible}
    window = tuple(by_date.get(day) for day in window_dates)

    as_of_day = window[-1]
    if as_of_day is None or as_of_day.adjusted_close is None:
        return MarketPositionResult(
            status=ResultStatus.NEEDS_REVIEW,
            sample_size=0,
            quality_flags=("CURRENT_PRICE_MISSING",),
            factor_view_hash=factor_view_hash,
        )
    if as_of_day.evidence_ref is None:
        return MarketPositionResult(
            status=ResultStatus.NEEDS_REVIEW,
            sample_size=0,
            quality_flags=("EVIDENCE_MISSING",),
            factor_view_hash=factor_view_hash,
        )
    if as_of_day.adjusted_close != price:
        return MarketPositionResult(
            status=ResultStatus.NEEDS_REVIEW,
            sample_size=0,
            quality_flags=("VALUATION_PRICE_MISMATCH",),
            factor_view_hash=factor_view_hash,
        )

    closes: list[Decimal] = []
    flags: set[str] = set()
    for observation in window:
        if observation is None:
            flags.add("MISSING_BAR")
            continue
        if observation.adjusted_close is None:
            if observation.paused is True and observation.evidence_ref is not None:
                continue
            flags.add("MISSING_BAR")
            continue
        if observation.adjusted_close <= 0:
            flags.add("NON_POSITIVE_CLOSE")
            continue
        if observation.evidence_ref is None:
            flags.add("EVIDENCE_MISSING")
            continue
        closes.append(observation.adjusted_close)

    if flags:
        return MarketPositionResult(
            status=ResultStatus.NEEDS_REVIEW,
            sample_size=len(closes),
            quality_flags=tuple(flags),
            factor_view_hash=factor_view_hash,
        )
    if len(closes) < 504:
        return MarketPositionResult(
            status=ResultStatus.UNKNOWN,
            sample_size=len(closes),
            quality_flags=("INSUFFICIENT_PRICE_HISTORY",),
            factor_view_hash=factor_view_hash,
        )

    with calculation_context():
        lower = sum(value < price for value in closes)
        equal = sum(value == price for value in closes)
        position = (
            Decimal(lower) + Decimal("0.5") * Decimal(equal)
        ) / Decimal(len(closes)) * Decimal("100")
        drawdown = (price / max(closes) - Decimal("1")) * Decimal("100")
        return MarketPositionResult(
            status=ResultStatus.PASS,
            sample_size=len(closes),
            position_pct=position,
            drawdown_from_high_pct=drawdown,
            market_position_score=Decimal("100") - position,
            label=_position_label(position),
            factor_view_hash=factor_view_hash,
        )


def _hash_identity(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _position_label(position: Decimal) -> str:
    if position <= Decimal("20"):
        return "LOW"
    if position <= Decimal("40"):
        return "LOWER_MID"
    if position <= Decimal("60"):
        return "MID"
    if position <= Decimal("80"):
        return "UPPER_MID"
    return "HIGH"


__all__ = ["MarketPositionResult", "PositionDay", "analyze_market_position"]
