"""Blocking and non-blocking quality checks for raw snapshot domains."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class QualityGateError(ValueError):
    """Raised when a domain cannot be published safely."""


@dataclass(frozen=True)
class QualityResult:
    row_count: int
    blocking_issues: tuple[str, ...] = ()
    warning_issues: tuple[str, ...] = ()


def _finite_decimal(value: object, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise QualityGateError(f"{field} must be a finite decimal")
    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QualityGateError(f"{field} must be a finite decimal") from exc
    if not converted.is_finite():
        raise QualityGateError(f"{field} must be finite")
    return converted


def validate_raw_daily_rows(
    rows: Iterable[Mapping[str, object]],
) -> QualityResult:
    """Validate raw daily bars without repairing or filling their values."""
    materialized = list(rows)
    seen: set[tuple[object, object]] = set()
    warnings: list[str] = []
    required_metadata = (
        "schema_version",
        "normalization_version",
        "source_name",
        "source_row_hash",
        "evidence_ref",
    )
    for index, row in enumerate(materialized):
        if row.get("adjust_type") != "RAW":
            raise QualityGateError(
                f"row {index}: adjust_type must be RAW"
            )
        key = (row.get("security_id"), row.get("trade_date"))
        if not all(isinstance(item, str) and item for item in key):
            raise QualityGateError(
                f"row {index}: security_id and trade_date are required"
            )
        if key in seen:
            raise QualityGateError(f"duplicate raw daily primary key: {key}")
        seen.add(key)
        for field in required_metadata:
            if row.get(field) in (None, ""):
                raise QualityGateError(f"row {index}: {field} is required")

        open_price = _finite_decimal(row.get("open"), "open")
        high = _finite_decimal(row.get("high"), "high")
        low = _finite_decimal(row.get("low"), "low")
        close = _finite_decimal(row.get("close"), "close")
        volume = _finite_decimal(row.get("volume"), "volume")
        amount = _finite_decimal(row.get("amount"), "amount")
        if volume < 0 or amount < 0:
            raise QualityGateError(
                f"row {index}: volume and amount must be non-negative"
            )
        zero_ohlc_placeholder = (
            open_price == high == low == Decimal("0")
            and close > 0
            and volume == amount == Decimal("0")
            and row.get("paused") is True
        )
        if zero_ohlc_placeholder:
            warnings.append(
                "market_daily:zero_ohlc_placeholder:warning:"
                f"{key[0]}:{key[1]}"
            )
            continue
        if min(open_price, high, low, close) <= 0:
            raise QualityGateError(
                f"row {index} {key}: prices must be positive"
            )
        if high < max(open_price, close) or low > min(open_price, close):
            warnings.append(f"market_daily:ohlc:warning:{key[0]}:{key[1]}")
        if high < low:
            warnings.append(
                f"market_daily:ohlc_range:warning:{key[0]}:{key[1]}"
            )

    return QualityResult(
        row_count=len(materialized),
        warning_issues=tuple(warnings),
    )
