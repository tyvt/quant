"""Validated unit types used by the domain layer.

External missing values must be represented as ``None`` before validation and
turned into an explicit UNKNOWN result by the caller. These types never fill
missing data with defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext


NumericLike = Decimal | int | str | float
CALCULATION_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


def calculation_context():
    """Use a stable Decimal context for deterministic domain calculations."""
    return localcontext(CALCULATION_CONTEXT)


def to_decimal(value: NumericLike) -> Decimal:
    """Convert a finite numeric value to Decimal without implicit rounding."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric quantity")
    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
    if not converted.is_finite():
        raise ValueError(f"decimal value must be finite: {value!r}")
    return converted


@dataclass(frozen=True, init=False)
class NonNegativePct:
    """A non-negative percentage represented as 5 for 5%."""

    value: Decimal

    def __init__(self, value: NumericLike) -> None:
        converted = to_decimal(value)
        if converted < 0:
            raise ValueError("percentage must be non-negative")
        object.__setattr__(self, "value", converted)


@dataclass(frozen=True, init=False)
class SignedPct:
    """A finite percentage which may be negative."""

    value: Decimal

    def __init__(self, value: NumericLike) -> None:
        object.__setattr__(self, "value", to_decimal(value))


@dataclass(frozen=True, init=False)
class UnitRatio:
    """A closed [0, 1] ratio, for example a tax rate."""

    value: Decimal

    def __init__(self, value: NumericLike) -> None:
        converted = to_decimal(value)
        if not Decimal("0") <= converted <= Decimal("1"):
            raise ValueError("ratio must be between 0 and 1")
        object.__setattr__(self, "value", converted)


@dataclass(frozen=True, init=False)
class SignedRatio:
    """A finite dimensionless ratio, for example -0.20 for -20%."""

    value: Decimal

    def __init__(self, value: NumericLike) -> None:
        object.__setattr__(self, "value", to_decimal(value))


@dataclass(frozen=True, init=False)
class BasisPoints:
    """A non-negative number of basis points."""

    value: Decimal

    def __init__(self, value: NumericLike) -> None:
        converted = to_decimal(value)
        if not Decimal("0") <= converted <= Decimal("10000"):
            raise ValueError("basis points must be between 0 and 10000")
        object.__setattr__(self, "value", converted)


@dataclass(frozen=True)
class NonNegativeDays:
    """A non-negative whole-day quantity."""

    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ValueError("days must be an integer")
        if self.value < 0:
            raise ValueError("days must be non-negative")


@dataclass(frozen=True, init=False)
class Money:
    """A signed amount with an explicit ISO-like currency code."""

    amount: Decimal
    currency: str

    def __init__(self, amount: NumericLike, currency: str) -> None:
        converted = to_decimal(amount)
        normalized_currency = currency.strip().upper()
        if not normalized_currency:
            raise ValueError("currency must be non-empty")
        object.__setattr__(self, "amount", converted)
        object.__setattr__(self, "currency", normalized_currency)
