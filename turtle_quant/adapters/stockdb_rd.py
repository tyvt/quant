"""Read-only adapter for the local StockDB ``rd`` tables."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
from pathlib import Path
import sys
from typing import Any

from turtle_quant.storage.snapshot import _canonical_json

from .security import normalize_security_id


@dataclass(frozen=True)
class StockDBSecurityCode:
    security_id: str
    raw_code: str
    exchange: str
    is_in_delisted_table: bool


def _execute(query: object) -> object:
    do = getattr(query, "do", None)
    return do() if callable(do) else query


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid StockDB decimal value: {value!r}") from exc
    if not converted.is_finite():
        raise ValueError(f"StockDB decimal value must be finite: {value!r}")
    return converted


def _provider_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value in {0, 1}:
            return bool(value)
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "y", "yes"}:
            return True
        if normalized in {"0", "false", "n", "no"}:
            return False
    return None


def _source_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def load_local_rd(
    pybao_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 7899,
) -> object:
    """Import the local SDK explicitly and return its native read client."""
    path = str(Path(pybao_path).resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    sdk = importlib.import_module("stock_sdk")
    return sdk.init(host=host, port=port, warm=False)


class StockDBLocalAdapter:
    def __init__(
        self,
        *,
        rd: object | None = None,
        pybao_path: str | Path = r"d:\repository\stockdb\pybao",
    ) -> None:
        self.rd = rd if rd is not None else load_local_rd(pybao_path)

    def list_security_codes(self) -> tuple[StockDBSecurityCode, ...]:
        grouped = _execute(self.rd.get("股票代码"))
        if not isinstance(grouped, Mapping):
            raise ValueError("StockDB 股票代码 must return a mapping")
        raw_delisted = _execute(self.rd.vals("退市*"))
        if not isinstance(raw_delisted, Iterable) or isinstance(
            raw_delisted, (str, bytes, Mapping)
        ):
            raise ValueError("StockDB 退市* must return an iterable")
        delisted = {
            str(item.get("code") if isinstance(item, Mapping) else item)
            for item in raw_delisted
        }
        codes: set[str] = set()
        for values in grouped.values():
            if isinstance(values, Iterable) and not isinstance(
                values, (str, bytes, Mapping)
            ):
                codes.update(str(item) for item in values)
        codes.update(delisted)
        normalized: list[StockDBSecurityCode] = []
        for raw_code in codes:
            try:
                security = normalize_security_id(raw_code, source="stockdb")
            except ValueError:
                continue
            normalized.append(
                StockDBSecurityCode(
                    security_id=security.security_id,
                    raw_code=security.raw_code,
                    exchange=security.exchange,
                    is_in_delisted_table=security.raw_code in delisted,
                )
            )
        return tuple(sorted(normalized, key=lambda item: item.security_id))

    def fetch_raw_daily(
        self,
        security_id: str,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        normalized = normalize_security_id(security_id, source="stockdb")
        query = f"{start_date:%Y%m%d}>{end_date:%Y%m%d}"
        raw_rows = _execute(self.rd.vals("日k", normalized.raw_code, query))
        if not isinstance(raw_rows, list):
            raise ValueError("StockDB 日k query must return a list")
        result: list[dict[str, object]] = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            raw_date = str(raw.get("date", ""))
            if len(raw_date) != 8 or not raw_date.isdigit():
                raise ValueError(f"invalid StockDB daily date: {raw_date!r}")
            trade_date = date(
                int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:])
            ).isoformat()
            code = str(raw.get("code", normalized.raw_code))
            if code != normalized.raw_code:
                raise ValueError(
                    f"StockDB row code mismatch: {code} != {normalized.raw_code}"
                )
            open_price = _decimal_or_none(raw.get("open"))
            high = _decimal_or_none(raw.get("high"))
            low = _decimal_or_none(raw.get("low"))
            close = _decimal_or_none(raw.get("close"))
            volume = _decimal_or_none(raw.get("volume"))
            amount = _decimal_or_none(
                raw.get("amount", raw.get("money"))
            )
            if "paused" in raw:
                paused = _provider_bool(raw["paused"])
                pause_status_source = (
                    "provider" if paused is not None else "unknown"
                )
            elif (
                open_price == high == low == Decimal("0")
                and close is not None
                and close > 0
                and volume == Decimal("0")
                and amount == Decimal("0")
            ):
                paused = True
                pause_status_source = "derived_zero_ohlc"
            else:
                paused = None
                pause_status_source = "unknown"
            result.append(
                {
                    "security_id": normalized.security_id,
                    "trade_date": trade_date,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "paused": paused,
                    "pause_status_source": pause_status_source,
                    "adjust_type": "RAW",
                    "schema_version": 1,
                    "normalization_version": "market_raw_v1",
                    "source_name": "stockdb_rd",
                    "source_row_hash": _source_hash(dict(raw)),
                    "evidence_ref": (
                        f"stockdb_rd:日k:{normalized.raw_code}:{raw_date}"
                    ),
                }
            )
        return result

    def fetch_adjustment_factors(
        self,
        security_ids: set[str] | None = None,
    ) -> list[dict[str, object]]:
        wanted_codes = (
            {
                normalize_security_id(item, source="stockdb").raw_code
                for item in security_ids
            }
            if security_ids is not None
            else None
        )
        query = self.rd.get("复权*")
        get_field = getattr(query, "get", None)
        if callable(get_field):
            query = get_field("cum")
        raw_rows = _execute(query)
        if not isinstance(raw_rows, list):
            raise ValueError("StockDB 复权* cum query must return a list")
        result: list[dict[str, object]] = []
        for item in raw_rows:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            key, value = item
            parts = str(key).split(":")
            if len(parts) < 3:
                continue
            code, raw_date = parts[-2], parts[-1][:8]
            if wanted_codes is not None and code not in wanted_codes:
                continue
            try:
                normalized = normalize_security_id(code, source="stockdb")
                ex_date = date(
                    int(raw_date[:4]),
                    int(raw_date[4:6]),
                    int(raw_date[6:]),
                ).isoformat()
            except (ValueError, IndexError):
                continue
            factor = _decimal_or_none(value)
            if factor is None or factor <= 0:
                raise ValueError(
                    f"StockDB cumulative factor must be positive: {item!r}"
                )
            result.append(
                {
                    "security_id": normalized.security_id,
                    "ex_date": ex_date,
                    "factor": factor,
                    "factor_source": "stockdb_cum",
                    "available_at": ex_date,
                    "schema_version": 1,
                    "normalization_version": "adjustment_factor_v1",
                    "source_name": "stockdb_rd",
                    "source_row_hash": _source_hash(
                        {"key": str(key), "cum": factor}
                    ),
                    "evidence_ref": f"stockdb_rd:{key}:cum",
                }
            )
        return sorted(
            result,
            key=lambda row: (str(row["security_id"]), str(row["ex_date"])),
        )


def adjusted_close_to_as_of(
    *,
    raw_close: Decimal,
    factor_on_bar_date: Decimal,
    factor_as_of: Decimal,
) -> Decimal:
    """Apply StockDB cumulative factors on the as-of date's raw-price scale."""
    if (
        not raw_close.is_finite()
        or not factor_on_bar_date.is_finite()
        or not factor_as_of.is_finite()
        or raw_close <= 0
        or factor_on_bar_date <= 0
        or factor_as_of <= 0
    ):
        raise ValueError("price and factors must be finite and positive")
    return raw_close * factor_on_bar_date / factor_as_of
