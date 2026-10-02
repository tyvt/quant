"""Baostock adapter for calendar, security master and factor evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import time
from typing import Any

from turtle_quant.storage.snapshot import _canonical_json

from .security import is_main_board_security, normalize_security_id


_SME_MERGER_DATE = date(2021, 4, 6)
_SME_LAST_DATE = date(2021, 4, 5)


def _hash_row(row: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(dict(row)).encode("utf-8")).hexdigest()


def _result_rows(result: object) -> list[dict[str, str]]:
    if getattr(result, "error_code", None) != "0":
        raise RuntimeError(
            f"Baostock query failed: {getattr(result, 'error_code', '?')} "
            f"{getattr(result, 'error_msg', '')}"
        )
    fields = list(getattr(result, "fields", []))
    rows: list[dict[str, str]] = []
    while result.next():
        values = result.get_row_data()
        rows.append(dict(zip(fields, values)))
    return rows


def _optional_date(value: object) -> str | None:
    if value in (None, "", "1900-01-01", "2200-01-01"):
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid Baostock date: {value!r}") from exc


def _decimal(value: object, field: str) -> Decimal:
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid Baostock {field}: {value!r}") from exc
    if not converted.is_finite():
        raise ValueError(f"Baostock {field} must be finite")
    return converted


def _board_intervals(
    security_id: str,
    listing_date: str,
    delisting_date: str | None,
) -> tuple[tuple[str, str, str | None], ...]:
    listing = date.fromisoformat(listing_date)
    delisting = (
        date.fromisoformat(delisting_date) if delisting_date else None
    )
    if security_id.startswith("sz.002") and listing < _SME_MERGER_DATE:
        first_end = min(
            delisting if delisting is not None else _SME_LAST_DATE,
            _SME_LAST_DATE,
        )
        intervals: list[tuple[str, str, str | None]] = [
            ("sme", listing.isoformat(), first_end.isoformat())
        ]
        if delisting is None or delisting >= _SME_MERGER_DATE:
            intervals.append(
                (
                    "main_board",
                    _SME_MERGER_DATE.isoformat(),
                    delisting.isoformat() if delisting else None,
                )
            )
        return tuple(intervals)
    return (
        (
            (
                "main_board"
                if is_main_board_security(security_id)
                else "other"
            ),
            listing_date,
            delisting_date,
        ),
    )


class BaostockAdapter:
    def __init__(
        self,
        module: object | None = None,
        *,
        login_attempts: int = 3,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        if module is None:
            import baostock as module
        if login_attempts < 1:
            raise ValueError("login_attempts must be positive")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        self._module = module
        self._logged_in = False
        self._login_attempts = login_attempts
        self._retry_delay_seconds = retry_delay_seconds

    @property
    def version(self) -> str:
        return str(getattr(self._module, "__version__", "unknown"))

    def __enter__(self) -> "BaostockAdapter":
        response = None
        for attempt in range(1, self._login_attempts + 1):
            response = self._module.login()
            if getattr(response, "error_code", None) == "0":
                self._logged_in = True
                return self
            if attempt < self._login_attempts and self._retry_delay_seconds:
                time.sleep(self._retry_delay_seconds * attempt)
        raise RuntimeError(
            f"Baostock login failed after {self._login_attempts} attempts: "
            f"{getattr(response, 'error_code', '?')} "
            f"{getattr(response, 'error_msg', '')}"
        )

    def __exit__(self, *_exc: object) -> None:
        if self._logged_in:
            self._module.logout()
            self._logged_in = False

    def _require_login(self) -> None:
        if not self._logged_in:
            raise RuntimeError("BaostockAdapter must be used as a context manager")

    def fetch_calendar(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        self._require_login()
        raw_rows = _result_rows(
            self._module.query_trade_dates(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
        )
        result: list[dict[str, object]] = []
        for raw in raw_rows:
            calendar_date = _optional_date(raw.get("calendar_date"))
            if calendar_date is None:
                raise ValueError("Baostock calendar row has no date")
            flag = raw.get("is_trading_day")
            if flag not in {"0", "1"}:
                raise ValueError("Baostock is_trading_day must be 0 or 1")
            result.append(
                {
                    "exchange": "cn",
                    "date": calendar_date,
                    "is_trading_day": flag == "1",
                    "schema_version": 1,
                    "normalization_version": "cn_calendar_v1",
                    "source_name": "baostock",
                    "source_row_hash": _hash_row(raw),
                    "evidence_ref": f"baostock:trade_dates:{calendar_date}",
                }
            )
        return result

    def fetch_security_master(self) -> list[dict[str, object]]:
        self._require_login()
        raw_rows = _result_rows(self._module.query_stock_basic())
        result: list[dict[str, object]] = []
        for raw in raw_rows:
            if raw.get("type") not in (None, "", "1"):
                continue
            raw_code = raw.get("code")
            if not isinstance(raw_code, str):
                continue
            try:
                normalized = normalize_security_id(
                    raw_code, source="baostock"
                )
            except ValueError:
                continue
            listing = _optional_date(raw.get("ipoDate"))
            if listing is None:
                continue
            delisting = _optional_date(raw.get("outDate"))
            for board, effective_from, effective_to in _board_intervals(
                normalized.security_id, listing, delisting
            ):
                result.append(
                    {
                        "security_id": normalized.security_id,
                        "raw_code": normalized.raw_code,
                        "vendor_symbol": normalized.vendor_symbol,
                        "exchange": normalized.exchange,
                        "display_name": raw.get("code_name") or None,
                        "board": board,
                        "board_effective_from": effective_from,
                        "board_effective_to": effective_to,
                        "listing_date": listing,
                        "delisting_date": delisting,
                        "delisting_date_semantics": "provider_out_date",
                        "provider_status": raw.get("status") or None,
                        "schema_version": 1,
                        "normalization_version": (
                            normalized.normalization_version
                        ),
                        "source_name": "baostock",
                        "source_row_hash": _hash_row(raw),
                        "evidence_ref": (
                            f"baostock:stock_basic:"
                            f"{normalized.vendor_symbol}:{board}"
                        ),
                    }
                )
        return sorted(
            result,
            key=lambda row: (
                str(row["security_id"]),
                str(row["board_effective_from"]),
            ),
        )

    def fetch_adjustment_factors(
        self,
        security_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        self._require_login()
        normalized = normalize_security_id(security_id, source="baostock")
        raw_rows = _result_rows(
            self._module.query_adjust_factor(
                code=normalized.security_id,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
        )
        result: list[dict[str, object]] = []
        for raw in raw_rows:
            ex_date = _optional_date(raw.get("dividOperateDate"))
            if ex_date is None:
                continue
            factor = _decimal(raw.get("adjustFactor"), "adjustFactor")
            if factor <= 0:
                raise ValueError("Baostock adjustment factor must be positive")
            result.append(
                {
                    "security_id": normalized.security_id,
                    "ex_date": ex_date,
                    "factor": factor,
                    "factor_source": "baostock_adjustFactor",
                    "available_at": ex_date,
                    "schema_version": 1,
                    "normalization_version": "adjustment_factor_v1",
                    "source_name": "baostock",
                    "source_row_hash": _hash_row(raw),
                    "evidence_ref": (
                        f"baostock:adjust_factor:"
                        f"{normalized.security_id}:{ex_date}"
                    ),
                }
            )
        return result
