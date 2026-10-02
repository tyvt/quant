"""Direct ChinaBond 10-year government-yield ingestion.

AKShare's source is used only as local endpoint documentation.  Production
requests are made directly to ChinaBond and the response is stored with its
request evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from io import StringIO
from typing import Any

from turtle_quant.storage.snapshot import _canonical_json


CHINABOND_HISTORY_ENDPOINT = (
    "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"
)
CHINABOND_GOVERNMENT_CURVE_NAME = "中债国债收益率曲线"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}


class NoValidYieldError(ValueError):
    """A valid ChinaBond table contains no usable government 10Y row."""


def build_history_request(
    start_date: date,
    end_date: date,
) -> tuple[str, dict[str, str]]:
    if end_date < start_date:
        raise ValueError("end_date cannot precede start_date")
    return CHINABOND_HISTORY_ENDPOINT, {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "gjqx": "0",
        "qxId": "ycqx",
        "locale": "cn_ZH",
    }


def year_slices(
    start_date: date,
    end_date: date,
) -> tuple[tuple[date, date], ...]:
    if end_date < start_date:
        raise ValueError("end_date cannot precede start_date")
    slices: list[tuple[date, date]] = []
    current = start_date
    while current <= end_date:
        year_end = date(current.year, 12, 31)
        current_end = min(year_end, end_date)
        slices.append((current, current_end))
        current = current_end + timedelta(days=1)
    return tuple(slices)


def _flatten_column(value: object) -> str:
    if isinstance(value, tuple):
        return "".join(str(item) for item in value if "Unnamed" not in str(item))
    return str(value)


def parse_history_html(html: str) -> list[dict[str, object]]:
    """Extract date and 10-year yield from a ChinaBond history response."""
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - optional sync dependency
        raise RuntimeError("pandas is required to parse ChinaBond HTML") from exc
    try:
        tables = pd.read_html(StringIO(html.replace("&nbsp", "")), header=0)
    except ValueError as exc:
        raise ValueError("ChinaBond response contains no HTML table") from exc
    selected = None
    curve_column = None
    date_column = None
    yield_column = None
    for table in tables:
        columns = {_flatten_column(column): column for column in table.columns}
        candidate_date = next(
            (original for flat, original in columns.items() if "日期" in flat),
            None,
        )
        candidate_yield = next(
            (
                original
                for flat, original in columns.items()
                if "10年" in flat
            ),
            None,
        )
        candidate_curve = next(
            (
                original
                for flat, original in columns.items()
                if "曲线名称" in flat
            ),
            None,
        )
        if (
            candidate_curve is not None
            and candidate_date is not None
            and candidate_yield is not None
        ):
            selected = table
            curve_column = candidate_curve
            date_column = candidate_date
            yield_column = candidate_yield
            break
    if (
        selected is None
        or curve_column is None
        or date_column is None
        or yield_column is None
    ):
        raise ValueError(
            "ChinaBond response lacks 曲线名称, 日期 or 10年 columns"
        )

    result: list[dict[str, object]] = []
    for _, row in selected.iterrows():
        if str(row[curve_column]).strip() != CHINABOND_GOVERNMENT_CURVE_NAME:
            continue
        raw_date = str(row[date_column])[:10]
        try:
            obs_date = date.fromisoformat(raw_date)
            yield_value = Decimal(str(row[yield_column]))
        except (ValueError, InvalidOperation):
            continue
        if not yield_value.is_finite() or yield_value < 0:
            continue
        result.append(
            {
                "obs_date": obs_date.isoformat(),
                "yield_10y_pct": yield_value,
            }
        )
    if not result:
        raise NoValidYieldError(
            "ChinaBond response contains no valid government 10-year yields"
        )
    return sorted(result, key=lambda item: str(item["obs_date"]))


class ChinabondAdapter:
    def __init__(self, session: object | None = None) -> None:
        if session is None:
            import requests

            session = requests.Session()
        self._session = session
        self._last_gaps: tuple[str, ...] = ()

    @property
    def last_gaps(self) -> tuple[str, ...]:
        return self._last_gaps

    def fetch_10y(
        self,
        start_date: date,
        end_date: date,
        *,
        available_at_resolver: Callable[[date], date],
    ) -> list[dict[str, object]]:
        result_by_date: dict[str, dict[str, object]] = {}
        gaps: list[str] = []
        for slice_start, slice_end in year_slices(start_date, end_date):
            endpoint, params = build_history_request(slice_start, slice_end)
            response = self._session.get(
                endpoint,
                params=params,
                headers=_HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            request_fingerprint = hashlib.sha256(
                _canonical_json(
                    {"endpoint": endpoint, "params": params}
                ).encode("utf-8")
            ).hexdigest()
            try:
                parsed_rows = parse_history_html(response.text)
            except NoValidYieldError:
                gaps.append(str(slice_start.year))
                continue
            for raw in parsed_rows:
                obs_date = date.fromisoformat(str(raw["obs_date"]))
                available_at = available_at_resolver(obs_date)
                if available_at < obs_date:
                    raise ValueError(
                        "yield available_at cannot precede observation date"
                    )
                evidence_ref = (
                    f"chinabond:historyQuery:{request_fingerprint}:"
                    f"{obs_date.isoformat()}"
                )
                source_row = {
                    "obs_date": obs_date.isoformat(),
                    "yield_10y_pct": raw["yield_10y_pct"],
                    "curve_id": "ycqx",
                    "curve_name": CHINABOND_GOVERNMENT_CURVE_NAME,
                    "tenor": "10Y",
                    "available_at": available_at.isoformat(),
                    "schema_version": 1,
                    "normalization_version": "chinabond_10y_v1",
                    "source_name": "chinabond",
                    "evidence_ref": evidence_ref,
                }
                source_row["source_row_hash"] = hashlib.sha256(
                    _canonical_json(source_row).encode("utf-8")
                ).hexdigest()
                result_by_date[obs_date.isoformat()] = source_row
        self._last_gaps = tuple(gaps)
        if not result_by_date:
            raise NoValidYieldError(
                "ChinaBond returned no valid government 10-year yields"
            )
        return [
            result_by_date[key]
            for key in sorted(result_by_date)
        ]
