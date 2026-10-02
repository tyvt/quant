"""Six-year absolute cash-payback valuation.

The formulas are frozen in RULE_SPEC.md. This module contains no data-source
access and returns UNKNOWN rather than silently replacing missing financial
inputs with zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from turtle_quant.core.result import ResultStatus
from turtle_quant.core.types import calculation_context, to_decimal


@dataclass(frozen=True)
class AttributionInputs:
    operating_cash_flow: Decimal
    capex: Decimal
    lease_cash_not_already_deducted: Decimal
    cash: Decimal
    liquid_assets: Decimal
    interest_bearing_debt: Decimal
    attributable_equity: Decimal
    minority_interest: Decimal


@dataclass(frozen=True)
class AttributionResult:
    alpha: Decimal
    fcf_ordinary: Decimal
    fcf_conservative: Decimal
    net_cash: Decimal


def derive_attribution(inputs: AttributionInputs) -> AttributionResult:
    """Derive attributable FCF and net cash using the frozen alpha bridge."""
    with calculation_context():
        return _derive_attribution(inputs)


def _derive_attribution(inputs: AttributionInputs) -> AttributionResult:
    attributable_equity = to_decimal(inputs.attributable_equity)
    minority_interest = to_decimal(inputs.minority_interest)
    if attributable_equity <= 0:
        raise ValueError("attributable_equity must be positive")

    denominator = attributable_equity + max(minority_interest, Decimal("0"))
    if denominator <= 0:
        raise ValueError("equity denominator must be positive")

    alpha = attributable_equity / denominator
    operating_cash_flow = to_decimal(inputs.operating_cash_flow)
    capex = to_decimal(inputs.capex)
    lease_cash = to_decimal(inputs.lease_cash_not_already_deducted)
    cash = to_decimal(inputs.cash)
    liquid_assets = to_decimal(inputs.liquid_assets)
    debt = to_decimal(inputs.interest_bearing_debt)

    return AttributionResult(
        alpha=alpha,
        fcf_ordinary=(operating_cash_flow - capex) * alpha,
        fcf_conservative=(operating_cash_flow - capex - lease_cash) * alpha,
        net_cash=(cash + liquid_assets - debt) * alpha,
    )


@dataclass(frozen=True)
class AbsoluteValuationInputs:
    """Inputs for D-group valuation.

    ``annual_fcf_newest_to_oldest`` is ordered F1 through F5. The order is a
    time contract, not a numeric sort order, because F1/F2/F3 determine A3.
    """

    price: Decimal
    market_value: Decimal
    net_cash: Decimal
    annual_fcf_newest_to_oldest: tuple[Decimal, ...]
    latest_annualized_fcf: Decimal | None
    previous_annualized_fcf: Decimal | None
    material_decline: bool = False
    decline_g: Decimal | None = None


@dataclass(frozen=True)
class AbsoluteValuationResult:
    status: ResultStatus
    missing_fields: tuple[str, ...] = ()
    f_norm: Decimal | None = None
    f0: Decimal | None = None
    delta_base: Decimal | None = None
    delta_base_reason: str | None = None
    delta_used: Decimal | None = None
    f_path: tuple[Decimal, ...] = ()
    coverage: Mapping[int, Decimal] = field(default_factory=dict)
    flat_coverage: Mapping[int, Decimal] = field(default_factory=dict)
    support_price: Mapping[int, Decimal] = field(default_factory=dict)
    payback: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))
        object.__setattr__(self, "f_path", tuple(self.f_path))
        object.__setattr__(
            self, "coverage", MappingProxyType(dict(self.coverage))
        )
        object.__setattr__(
            self, "flat_coverage", MappingProxyType(dict(self.flat_coverage))
        )
        object.__setattr__(
            self, "support_price", MappingProxyType(dict(self.support_price))
        )


def calculate_absolute_valuation(
    inputs: AbsoluteValuationInputs,
) -> AbsoluteValuationResult:
    """Calculate six-year cash-payback metrics for complete standard inputs."""
    with calculation_context():
        return _calculate_absolute_valuation(inputs)


def _calculate_absolute_valuation(
    inputs: AbsoluteValuationInputs,
) -> AbsoluteValuationResult:
    missing_fields: list[str] = []
    if inputs.latest_annualized_fcf is None:
        missing_fields.append("latest_annualized_fcf")
    if len(inputs.annual_fcf_newest_to_oldest) != 5:
        missing_fields.append("annual_fcf_newest_to_oldest")
    if missing_fields:
        return AbsoluteValuationResult(
            status=ResultStatus.UNKNOWN,
            missing_fields=tuple(missing_fields),
        )

    price = to_decimal(inputs.price)
    market_value = to_decimal(inputs.market_value)
    net_cash = to_decimal(inputs.net_cash)
    if price <= 0:
        raise ValueError("price must be positive")
    if market_value <= 0:
        raise ValueError("market_value must be positive")

    annual_fcf = tuple(
        to_decimal(value)
        for value in inputs.annual_fcf_newest_to_oldest
    )
    latest = to_decimal(inputs.latest_annualized_fcf)
    previous = (
        to_decimal(inputs.previous_annualized_fcf)
        if inputs.previous_annualized_fcf is not None
        else None
    )

    f_norm = _normalised_fcf(annual_fcf)
    f0 = max(Decimal("0"), min(f_norm, max(Decimal("0"), latest)))
    delta_base, delta_base_reason = _delta_base(f0, latest, previous)
    delta_used = _delta_used(
        delta_base=delta_base,
        f0=f0,
        material_decline=inputs.material_decline,
        decline_g=inputs.decline_g,
    )

    f_path = tuple(
        max(Decimal("0"), f0 + Decimal(year) * delta_used)
        for year in range(1, 7)
    )
    coverage, flat_coverage, support_price = _coverage_metrics(
        price=price,
        market_value=market_value,
        net_cash=net_cash,
        f0=f0,
        f_path=f_path,
    )
    payback = _payback(market_value, net_cash, f_path)
    status = (
        ResultStatus.PASS
        if coverage[6] >= Decimal("1")
        else ResultStatus.FAIL
    )

    return AbsoluteValuationResult(
        status=status,
        f_norm=f_norm,
        f0=f0,
        delta_base=delta_base,
        delta_base_reason=delta_base_reason,
        delta_used=delta_used,
        f_path=f_path,
        coverage=coverage,
        flat_coverage=flat_coverage,
        support_price=support_price,
        payback=payback,
    )


def _normalised_fcf(annual_fcf: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(annual_fcf)
    median = ordered[len(ordered) // 2]
    average_three = sum(annual_fcf[:3], Decimal("0")) / Decimal("3")
    if median == 0 and average_three != 0:
        return average_three
    if average_three == 0 and median != 0:
        return median
    return min(median, average_three)


def _delta_base(
    f0: Decimal, latest: Decimal, previous: Decimal | None
) -> tuple[Decimal, str | None]:
    if f0 <= 0:
        return Decimal("0"), "f0_non_positive"
    if latest <= 0:
        return Decimal("0"), "latest_fcf_non_positive"
    if previous is None:
        return Decimal("0"), "previous_fcf_missing_or_non_positive"
    if previous <= 0:
        return Decimal("0"), "previous_fcf_missing_or_non_positive"
    raw_delta = latest - previous
    bound = Decimal("0.10") * f0
    return max(-bound, min(bound, raw_delta)), None


def _delta_used(
    *,
    delta_base: Decimal,
    f0: Decimal,
    material_decline: bool,
    decline_g: Decimal | None,
) -> Decimal:
    if not material_decline:
        return delta_base
    g = Decimal("0") if decline_g is None else to_decimal(decline_g)
    if g > 0:
        raise ValueError("decline_g must be non-positive")
    return min(delta_base, f0 * g)


def _coverage_metrics(
    *,
    price: Decimal,
    market_value: Decimal,
    net_cash: Decimal,
    f0: Decimal,
    f_path: tuple[Decimal, ...],
) -> tuple[dict[int, Decimal], dict[int, Decimal], dict[int, Decimal]]:
    coverage: dict[int, Decimal] = {}
    flat_coverage: dict[int, Decimal] = {}
    support_price: dict[int, Decimal] = {}
    accumulated = net_cash
    for year, flow in enumerate(f_path, start=1):
        accumulated += flow
        coverage[year] = accumulated / market_value
        flat_value = net_cash + Decimal(year) * f0
        flat_coverage[year] = flat_value / market_value
        support_market_value = max(Decimal("0"), accumulated)
        support_price[year] = price * support_market_value / market_value
    return coverage, flat_coverage, support_price


def _payback(
    market_value: Decimal, net_cash: Decimal, f_path: tuple[Decimal, ...]
) -> Decimal | None:
    if net_cash >= market_value:
        return Decimal("0")
    accumulated = net_cash
    for year, flow in enumerate(f_path, start=1):
        previous = accumulated
        accumulated += flow
        if accumulated >= market_value:
            return (
                Decimal(year - 1)
                + (market_value - previous) / flow
            )
    return None
