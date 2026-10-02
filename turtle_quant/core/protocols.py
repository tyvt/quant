"""Data-source-neutral read protocols.

Adapters may implement these protocols later. The domain layer receives
standardized values and never imports an adapter implementation.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from .market_data import (
    AdjustmentFactorObservation,
    PriceBarSeries,
    RateObservation,
)
from .pit import FinancialRecord


class FinancialDataReader(Protocol):
    def get_financial_record(
        self, security_id: str, period_end: date, *, as_of: date
    ) -> FinancialRecord | None:
        """Return only the version visible on or before ``as_of``."""


class SecurityMasterReader(Protocol):
    def security_ids_as_of(self, as_of: date) -> tuple[str, ...]:
        """Return the historical universe, including then-active delisted names."""


class CorporateActionsReader(Protocol):
    def adjustment_factor_series(
        self, security_id: str, start: date, end: date, *, as_of: date
    ) -> tuple[AdjustmentFactorObservation, ...]:
        """Return versioned factors for ADJUSTED_TO_AS_OF research prices."""


class MarketDataReader(Protocol):
    def price_bars(
        self, security_id: str, start: date, end: date, *, as_of: date
    ) -> PriceBarSeries:
        """Return raw bars plus typed, local coverage issues at ``as_of``."""


class RateCurveReader(Protocol):
    def value_on(self, series: str, *, as_of: date) -> RateObservation | None:
        """Return a traceable historical rate value or None when unavailable."""


class TradingCalendarReader(Protocol):
    def calendar_day(self, exchange: str, day: date) -> bool | None:
        """Return trading-day state within research coverage."""

    def previous_trading_day(self, exchange: str, day: date) -> date | None:
        """Return the nearest covered trading day strictly before ``day``."""

    def next_trading_day(self, exchange: str, day: date) -> date | None:
        """Return the nearest trading day after ``day`` under buffer rules."""
