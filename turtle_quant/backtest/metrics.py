"""Deterministic performance metrics frozen by RULE_SPEC v1.3.0."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from turtle_quant.core.types import calculation_context, to_decimal


@dataclass(frozen=True)
class NavPoint:
    trade_date: date
    nav: Decimal
    cash: Decimal
    holdings_count: int

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")
        nav = to_decimal(self.nav)
        cash = to_decimal(self.cash)
        if nav <= 0 or cash < 0:
            raise ValueError("NAV must be positive and cash non-negative")
        if (
            isinstance(self.holdings_count, bool)
            or not isinstance(self.holdings_count, int)
            or self.holdings_count < 0
        ):
            raise ValueError("holdings_count must be a non-negative integer")
        object.__setattr__(self, "nav", nav)
        object.__setattr__(self, "cash", cash)


@dataclass(frozen=True)
class BenchmarkPoint:
    trade_date: date
    close: Decimal

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")
        close = to_decimal(self.close)
        if close <= 0:
            raise ValueError("benchmark close must be positive")
        object.__setattr__(self, "close", close)


@dataclass(frozen=True)
class TradeNotional:
    trade_date: date
    absolute_notional: Decimal

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")
        value = to_decimal(self.absolute_notional)
        if value < 0:
            raise ValueError("absolute_notional must be non-negative")
        object.__setattr__(self, "absolute_notional", value)


@dataclass(frozen=True)
class PerformanceResult:
    complete: bool
    quality_flags: tuple[str, ...]
    start_nav: Decimal
    end_nav: Decimal
    cumulative_return: Decimal
    cagr: Decimal | None
    annualized_volatility: Decimal | None
    max_drawdown: Decimal
    max_drawdown_peak: date
    max_drawdown_trough: date
    sharpe: Decimal | None
    benchmark_cagr: Decimal | None
    excess_cagr: Decimal | None
    tracking_error: Decimal | None
    information_ratio: Decimal | None
    monthly_win_rate: Decimal | None
    annual_returns: Mapping[int, Decimal] = field(default_factory=dict)
    one_way_turnover: Decimal | None = None
    average_cash_ratio: Decimal | None = None
    average_holdings_count: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_flags", tuple(sorted(set(self.quality_flags))))
        object.__setattr__(self, "annual_returns", MappingProxyType(dict(self.annual_returns)))


def calculate_performance(
    nav_points: tuple[NavPoint, ...],
    *,
    benchmark_points: tuple[BenchmarkPoint, ...],
    risk_free_yields_pct: Mapping[date, Decimal],
    trades: tuple[TradeNotional, ...],
    expected_trading_dates: tuple[date, ...],
    calendar_complete_through: date,
) -> PerformanceResult:
    """Calculate metrics without filling missing benchmark or rate observations."""

    nav = _ordered_unique(nav_points, NavPoint, "NAV")
    if not nav:
        raise ValueError("nav_points cannot be empty")
    expected = tuple(expected_trading_dates)
    if (
        not expected
        or any(type(item) is not date for item in expected)
        or tuple(sorted(expected)) != expected
        or len(set(expected)) != len(expected)
    ):
        raise ValueError("expected_trading_dates must be non-empty, sorted and unique")
    if type(calendar_complete_through) is not date or expected[-1] > calendar_complete_through:
        raise ValueError("calendar_complete_through must cover expected_trading_dates")
    if any(item.trade_date not in expected for item in nav):
        raise ValueError("NAV dates must belong to expected_trading_dates")
    benchmark = _ordered_unique(benchmark_points, BenchmarkPoint, "benchmark")
    trade_values = tuple(trades)
    if any(not isinstance(item, TradeNotional) for item in trade_values):
        raise ValueError("trades must contain TradeNotional values")
    if any(item.trade_date not in expected for item in trade_values):
        raise ValueError("trade dates must belong to expected_trading_dates")
    yield_map: dict[date, Decimal] = {}
    for day, value in risk_free_yields_pct.items():
        if type(day) is not date:
            raise ValueError("risk-free keys must be dates")
        converted = to_decimal(value)
        if converted < 0:
            raise ValueError("risk-free yields must be non-negative")
        yield_map[day] = converted

    with calculation_context():
        returns = tuple(
            nav[index].nav / nav[index - 1].nav - Decimal("1")
            for index in range(1, len(nav))
        )
        flags: set[str] = set()
        if tuple(item.trade_date for item in nav) != expected:
            flags.add("NAV_INCOMPLETE")
        if len(returns) < 2:
            flags.add("INSUFFICIENT_RETURN_SAMPLE")
        cumulative = nav[-1].nav / nav[0].nav - Decimal("1")
        cagr = _cagr(nav[0].nav, nav[-1].nav, nav[0].trade_date, nav[-1].trade_date)
        volatility = (
            _sample_std(returns) * Decimal("252").sqrt()
            if len(returns) >= 2
            else None
        )
        max_drawdown, peak, trough = _max_drawdown(nav)

        return_dates = tuple(item.trade_date for item in nav[1:])
        if all(day in yield_map for day in return_dates) and len(returns) >= 2:
            excess = tuple(
                value
                - (
                    (Decimal("1") + yield_map[day] / Decimal("100"))
                    ** (Decimal("1") / Decimal("252"))
                    - Decimal("1")
                )
                for day, value in zip(return_dates, returns)
            )
            excess_std = _sample_std(excess)
            sharpe = (
                _mean(excess) / excess_std * Decimal("252").sqrt()
                if excess_std != 0
                else None
            )
            if excess_std == 0:
                flags.add("SHARPE_DENOMINATOR_ZERO")
        else:
            flags.add("RISK_FREE_INCOMPLETE")
            sharpe = None

        benchmark_by_date = {item.trade_date: item.close for item in benchmark}
        benchmark_complete = all(item.trade_date in benchmark_by_date for item in nav)
        benchmark_cagr: Decimal | None = None
        excess_cagr: Decimal | None = None
        tracking_error: Decimal | None = None
        information_ratio: Decimal | None = None
        monthly_win_rate: Decimal | None = None
        if benchmark_complete:
            benchmark_returns = tuple(
                benchmark_by_date[nav[index].trade_date]
                / benchmark_by_date[nav[index - 1].trade_date]
                - Decimal("1")
                for index in range(1, len(nav))
            )
            benchmark_cagr = _cagr(
                benchmark_by_date[nav[0].trade_date],
                benchmark_by_date[nav[-1].trade_date],
                nav[0].trade_date,
                nav[-1].trade_date,
            )
            if cagr is not None and benchmark_cagr is not None:
                excess_cagr = cagr - benchmark_cagr
            if len(returns) >= 2:
                active = tuple(
                    value - benchmark_value
                    for value, benchmark_value in zip(returns, benchmark_returns)
                )
                active_std = _sample_std(active)
                tracking_error = active_std * Decimal("252").sqrt()
                information_ratio = (
                    _mean(active) / active_std * Decimal("252").sqrt()
                    if active_std != 0
                    else None
                )
                if active_std == 0:
                    flags.add("ACTIVE_RETURN_DENOMINATOR_ZERO")
            monthly_win_rate = _monthly_win_rate(
                nav, benchmark_by_date, expected, calendar_complete_through
            )
            if monthly_win_rate is None:
                flags.add("MONTHLY_WIN_RATE_UNAVAILABLE")
        else:
            flags.add("BENCHMARK_INCOMPLETE")

        annual_returns = _annual_returns(nav)
        mean_nav = _mean(tuple(item.nav for item in nav))
        turnover = (
            sum((item.absolute_notional for item in trade_values), Decimal("0"))
            / (Decimal("2") * mean_nav)
            if mean_nav > 0
            else None
        )
        cash_ratio = _mean(tuple(item.cash / item.nav for item in nav))
        holdings = _mean(tuple(Decimal(item.holdings_count) for item in nav))
        return PerformanceResult(
            complete=not flags,
            quality_flags=tuple(flags),
            start_nav=nav[0].nav,
            end_nav=nav[-1].nav,
            cumulative_return=cumulative,
            cagr=cagr,
            annualized_volatility=volatility,
            max_drawdown=max_drawdown,
            max_drawdown_peak=peak,
            max_drawdown_trough=trough,
            sharpe=sharpe,
            benchmark_cagr=benchmark_cagr,
            excess_cagr=excess_cagr,
            tracking_error=tracking_error,
            information_ratio=information_ratio,
            monthly_win_rate=monthly_win_rate,
            annual_returns=annual_returns,
            one_way_turnover=turnover,
            average_cash_ratio=cash_ratio,
            average_holdings_count=holdings,
        )


def _ordered_unique(values: tuple[object, ...], expected_type: type, label: str):
    rows = tuple(values)
    if any(not isinstance(item, expected_type) for item in rows):
        raise ValueError(f"{label} points contain invalid values")
    dates = tuple(item.trade_date for item in rows)  # type: ignore[attr-defined]
    if tuple(sorted(dates)) != dates or len(set(dates)) != len(dates):
        raise ValueError(f"{label} dates must be sorted and unique")
    return rows


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("mean requires values")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _sample_std(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        raise ValueError("sample standard deviation needs at least two values")
    mean = _mean(values)
    variance = sum(((item - mean) ** 2 for item in values), Decimal("0")) / Decimal(
        len(values) - 1
    )
    return variance.sqrt()


def _cagr(start: Decimal, end: Decimal, start_date: date, end_date: date) -> Decimal | None:
    days = (end_date - start_date).days
    if days <= 0:
        return None
    years = Decimal(days) / Decimal("365.2425")
    return (end / start) ** (Decimal("1") / years) - Decimal("1")


def _max_drawdown(nav: tuple[NavPoint, ...]) -> tuple[Decimal, date, date]:
    peak_value = nav[0].nav
    peak_date = nav[0].trade_date
    worst = Decimal("0")
    worst_peak = peak_date
    worst_trough = peak_date
    for point in nav:
        if point.nav > peak_value:
            peak_value = point.nav
            peak_date = point.trade_date
        drawdown = point.nav / peak_value - Decimal("1")
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak_date
            worst_trough = point.trade_date
    return worst, worst_peak, worst_trough


def _monthly_win_rate(
    nav: tuple[NavPoint, ...],
    benchmark: Mapping[date, Decimal],
    expected_trading_dates: tuple[date, ...],
    calendar_complete_through: date,
) -> Decimal | None:
    expected_month_ends: dict[tuple[int, int], date] = {}
    for day in expected_trading_dates:
        expected_month_ends[(day.year, day.month)] = day
    month_ends: dict[tuple[int, int], NavPoint] = {}
    for point in nav:
        key = (point.trade_date.year, point.trade_date.month)
        if (
            date(key[0], key[1], calendar.monthrange(*key)[1]) <= calendar_complete_through
            and point.trade_date == expected_month_ends[key]
        ):
            month_ends[key] = point
    ordered = tuple(month_ends[key] for key in sorted(month_ends))
    if len(ordered) < 2:
        return None
    wins = 0
    comparisons = 0
    for previous, current in zip(ordered, ordered[1:]):
        if previous.trade_date not in benchmark or current.trade_date not in benchmark:
            continue
        strategy_return = current.nav / previous.nav - Decimal("1")
        benchmark_return = benchmark[current.trade_date] / benchmark[previous.trade_date] - Decimal("1")
        comparisons += 1
        wins += strategy_return > benchmark_return
    return Decimal(wins) / Decimal(comparisons) if comparisons else None


def _annual_returns(nav: tuple[NavPoint, ...]) -> dict[int, Decimal]:
    by_year: dict[int, list[NavPoint]] = {}
    for point in nav:
        by_year.setdefault(point.trade_date.year, []).append(point)
    return {
        year: points[-1].nav / points[0].nav - Decimal("1")
        for year, points in sorted(by_year.items())
        if len(points) >= 2
    }


__all__ = [
    "BenchmarkPoint",
    "NavPoint",
    "PerformanceResult",
    "TradeNotional",
    "calculate_performance",
]
