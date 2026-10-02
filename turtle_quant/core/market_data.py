"""Immutable stage-A market, factor, rate, and coverage value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import re
from typing import Iterable

from .types import NonNegativePct


_SECURITY_ID_PATTERN = re.compile(r"^(sh|sz)\.\d{6}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RATE_SERIES_ID = "CN_GOVT_10Y_YIELD_PCT"


def _canonical_security_id(value: object) -> str:
    if not isinstance(value, str) or not _SECURITY_ID_PATTERN.fullmatch(value):
        raise ValueError("security_id must use canonical sh.600000 form")
    return value


def _date(value: object, field: str) -> date:
    if type(value) is not date:
        raise ValueError(f"{field} must be a date without a time component")
    return value


def _decimal(
    value: object,
    field: str,
    *,
    strictly_positive: bool = False,
) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")
    if strictly_positive and value <= 0:
        raise ValueError(f"{field} must be positive")
    if not strictly_positive and value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_nonempty(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field)


def _source_hash(value: object, *, optional: bool) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError("source_row_hash must be a lowercase SHA-256")
    return value


class CoverageIssueType(str, Enum):
    SECURITY_NOT_COVERED = "SECURITY_NOT_COVERED"
    MISSING_BAR = "MISSING_BAR"
    PAUSE_STATUS_UNKNOWN = "PAUSE_STATUS_UNKNOWN"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"


@dataclass(frozen=True)
class RawPriceBar:
    security_id: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    amount: Decimal | None
    paused: bool | None
    evidence_ref: str | None
    source_row_hash: str | None
    adjust_type: str = "RAW"

    def __post_init__(self) -> None:
        _canonical_security_id(self.security_id)
        _date(self.trade_date, "trade_date")
        for field in ("open", "high", "low", "close"):
            _decimal(getattr(self, field), field)
        _optional_decimal(self.volume, "volume")
        _optional_decimal(self.amount, "amount")
        if self.paused is not None and type(self.paused) is not bool:
            raise ValueError("paused must be bool or None")
        _optional_nonempty(self.evidence_ref, "evidence_ref")
        _source_hash(self.source_row_hash, optional=True)
        if self.adjust_type != "RAW":
            raise ValueError("adjust_type must be RAW")


@dataclass(frozen=True)
class CoverageIssue:
    issue_type: CoverageIssueType
    security_id: str
    date_range: tuple[date, date]
    evidence_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.issue_type, CoverageIssueType):
            raise ValueError("issue_type must be a CoverageIssueType")
        _canonical_security_id(self.security_id)
        if not isinstance(self.date_range, tuple) or len(self.date_range) != 2:
            raise ValueError("date_range must be a two-date tuple")
        start = _date(self.date_range[0], "date_range start")
        end = _date(self.date_range[1], "date_range end")
        if end < start:
            raise ValueError("date_range end cannot precede start")
        _optional_nonempty(self.evidence_ref, "evidence_ref")


def _issue_key(issue: CoverageIssue) -> tuple[str, date, date, str]:
    return (
        issue.security_id,
        issue.date_range[0],
        issue.date_range[1],
        issue.issue_type.value,
    )


@dataclass(frozen=True)
class PriceBarSeries:
    bars: tuple[RawPriceBar, ...]
    coverage_issues: tuple[CoverageIssue, ...]
    quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        bars = tuple(self.bars)
        issues = tuple(self.coverage_issues)
        if any(not isinstance(item, RawPriceBar) for item in bars):
            raise ValueError("bars must contain RawPriceBar values")
        if any(not isinstance(item, CoverageIssue) for item in issues):
            raise ValueError("coverage_issues must contain CoverageIssue values")
        bar_keys = tuple((item.security_id, item.trade_date) for item in bars)
        if bar_keys != tuple(sorted(bar_keys)):
            raise ValueError("bars must be sorted by security_id and trade_date")
        if len(set(bar_keys)) != len(bar_keys):
            raise ValueError("bars must have unique security_id/trade_date keys")
        issue_keys = tuple(_issue_key(item) for item in issues)
        if issue_keys != tuple(sorted(issue_keys)):
            raise ValueError("coverage_issues must be stably sorted")
        flags = tuple(self.quality_flags)
        if any(not isinstance(item, str) or not item for item in flags):
            raise ValueError("quality_flags must contain non-empty strings")
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "coverage_issues", issues)
        object.__setattr__(self, "quality_flags", tuple(sorted(set(flags))))

    @property
    def coverage_complete(self) -> bool:
        return not self.coverage_issues


@dataclass(frozen=True)
class AdjustmentFactorObservation:
    security_id: str
    ex_date: date
    available_at: date
    cumulative_factor: Decimal
    factor_source: str
    evidence_ref: str
    source_row_hash: str

    def __post_init__(self) -> None:
        _canonical_security_id(self.security_id)
        ex_date = _date(self.ex_date, "ex_date")
        available_at = _date(self.available_at, "available_at")
        if available_at < ex_date:
            raise ValueError("available_at cannot precede ex_date")
        _decimal(
            self.cumulative_factor,
            "cumulative_factor",
            strictly_positive=True,
        )
        _nonempty(self.factor_source, "factor_source")
        _nonempty(self.evidence_ref, "evidence_ref")
        _source_hash(self.source_row_hash, optional=False)


@dataclass(frozen=True)
class RateObservation:
    series: str
    obs_date: date
    available_at: date
    value: NonNegativePct
    curve_id: str
    curve_name: str
    tenor: str
    evidence_ref: str
    source_row_hash: str

    def __post_init__(self) -> None:
        if self.series != RATE_SERIES_ID:
            raise ValueError(f"series must be {RATE_SERIES_ID}")
        obs_date = _date(self.obs_date, "obs_date")
        available_at = _date(self.available_at, "available_at")
        if available_at < obs_date:
            raise ValueError("available_at cannot precede obs_date")
        if not isinstance(self.value, NonNegativePct):
            raise ValueError("value must be NonNegativePct")
        if self.curve_id != "ycqx":
            raise ValueError("curve_id must be ycqx")
        _nonempty(self.curve_name, "curve_name")
        if self.tenor != "10Y":
            raise ValueError("tenor must be 10Y")
        _nonempty(self.evidence_ref, "evidence_ref")
        _source_hash(self.source_row_hash, optional=False)


def cumulative_factor_on(
    observations: Iterable[AdjustmentFactorObservation],
    *,
    security_id: str,
    day: date,
    as_of: date,
) -> Decimal:
    """Return the latest cumulative level at ``day`` from one as-of view."""

    _canonical_security_id(security_id)
    day = _date(day, "day")
    as_of = _date(as_of, "as_of")
    if day > as_of:
        raise ValueError("day cannot follow as_of")

    visible: list[AdjustmentFactorObservation] = []
    values_by_key: dict[tuple[str, date, date], Decimal] = {}
    for observation in observations:
        if not isinstance(observation, AdjustmentFactorObservation):
            raise ValueError("observations must contain AdjustmentFactorObservation")
        if observation.security_id != security_id:
            continue
        if observation.available_at > as_of or observation.ex_date > day:
            continue
        key = (
            observation.security_id,
            observation.ex_date,
            observation.available_at,
        )
        existing = values_by_key.get(key)
        if existing is not None and existing != observation.cumulative_factor:
            raise ValueError(
                "conflicting cumulative factors for one PIT ordering key"
            )
        values_by_key[key] = observation.cumulative_factor
        visible.append(observation)
    if not visible:
        return Decimal("1")
    selected = max(
        visible,
        key=lambda item: (
            item.ex_date,
            item.available_at,
            item.evidence_ref,
            item.source_row_hash,
        ),
    )
    return selected.cumulative_factor


__all__ = [
    "AdjustmentFactorObservation",
    "CoverageIssue",
    "CoverageIssueType",
    "PriceBarSeries",
    "RATE_SERIES_ID",
    "RateObservation",
    "RawPriceBar",
    "cumulative_factor_on",
]
