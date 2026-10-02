"""Read-only direct CSI H00985 response adapter.

The fetch timestamp returned by this adapter is an audit fact. On publication
it belongs in snapshot meta ``source_provenance.csindex.fetch_time_utc``, not
in content-identified Parquet rows. The ParquetBenchmarkReader attaches that
exact snapshot's timestamp to returned observations; response hashes do not
select a timestamp across different snapshots.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
from types import MappingProxyType

from turtle_quant.storage.snapshot import _canonical_json


SOURCE_ID = "csindex_official_index_perf_v1"
ENDPOINT = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
INDEX_CODE = "H00985"
INDEX_NAME_CN_ALL = "中证全指全收益指数"
INDEX_NAME_EN_ALL = "CSI All Share Total Return Index"
_DATE_TEXT = re.compile(r"^[0-9]{8}$")
EXCLUSION_POLICY = "explicit_whitelist_v1"
CURRENT_EXCLUSION_RULE_VERSION = "v1.3.1"
APPROVED_EXCLUSION_RULE_VERSIONS = frozenset({"v1.3.0", "v1.3.1"})
_EXCLUSION_REASON = "官方接口返回非交易日行，日历与交易所公告一致"
# The dates are individually approved; no date-range or weekday pattern is allowed.
_EXCLUDED_OFFICIAL_CLOSES = MappingProxyType({
    date(2005, 1, 1): Decimal("984.40"),
    date(2018, 6, 18): Decimal("5161.74"),
})


@dataclass(frozen=True)
class BenchmarkObservation:
    trade_date: date
    index_code: str
    index_name_cn_all: str
    index_name_en_all: str
    close: Decimal
    source_response_hash: str
    fetched_at_utc: datetime
    evidence_ref: str
    quality_flags: tuple[str, ...] = ()
    excluded_dates: tuple[date, ...] = ()
    exclusion_evidence: tuple[BenchmarkExclusion, ...] = ()


@dataclass(frozen=True)
class BenchmarkExclusion:
    excluded_date: date
    official_close: Decimal
    calendar_verdict: str
    exclusion_reason: str
    evidence_ref: str
    rule_version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "excluded_date": self.excluded_date.isoformat(),
            "official_close": str(self.official_close),
            "calendar_verdict": self.calendar_verdict,
            "exclusion_reason": self.exclusion_reason,
            "evidence_ref": self.evidence_ref,
            "rule_version": self.rule_version,
        }


@dataclass(frozen=True)
class BenchmarkFetch:
    raw_response: bytes
    source_response_hash: str
    fetched_at_utc: datetime
    observations: tuple[BenchmarkObservation, ...]
    exclusions: tuple[BenchmarkExclusion, ...] = ()


def build_request(start: date, end: date) -> tuple[str, dict[str, str]]:
    if type(start) is not date or type(end) is not date or end < start:
        raise ValueError("benchmark request dates must be ordered dates")
    return ENDPOINT, {
        "indexCode": INDEX_CODE,
        "startDate": start.strftime("%Y%m%d"),
        "endDate": end.strftime("%Y%m%d"),
    }


def parse_official_response(
    raw_response: bytes,
    *,
    start: date,
    end: date,
    expected_trading_dates: tuple[date, ...],
    fetched_at_utc: datetime,
    exclusion_rule_version: str = CURRENT_EXCLUSION_RULE_VERSION,
) -> BenchmarkFetch:
    """Reject identity drift, invalid closes, duplicate dates and calendar gaps."""

    build_request(start, end)
    if (
        not isinstance(exclusion_rule_version, str)
        or exclusion_rule_version not in APPROVED_EXCLUSION_RULE_VERSIONS
    ):
        raise ValueError("benchmark exclusion rule version is not approved")
    expected = tuple(expected_trading_dates)
    if (
        not expected
        or any(type(day) is not date or day < start or day > end for day in expected)
        or tuple(sorted(expected)) != expected
        or len(set(expected)) != len(expected)
    ):
        raise ValueError("expected_trading_dates must be sorted unique dates inside the request")
    if (
        not isinstance(fetched_at_utc, datetime)
        or fetched_at_utc.tzinfo is None
        or fetched_at_utc.utcoffset() != timezone.utc.utcoffset(None)
    ):
        raise ValueError("fetched_at_utc must be timezone-aware UTC")
    if not isinstance(raw_response, bytes) or not raw_response:
        raise ValueError("raw_response must be non-empty bytes")
    response_hash = hashlib.sha256(raw_response).hexdigest()
    try:
        payload = json.loads(
            raw_response.decode("utf-8"),
            parse_float=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("benchmark response must be UTF-8 JSON") from exc
    if not isinstance(payload, dict) or payload.get("code") != "200":
        raise ValueError("CSI benchmark response was not successful")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("CSI benchmark data must be a list")
    observations: list[BenchmarkObservation] = []
    exclusions: list[BenchmarkExclusion] = []
    expected_set = set(expected)
    seen_dates: set[date] = set()
    for row_index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError("CSI benchmark row must be an object")
        raw_day = row.get("tradeDate")
        if not isinstance(raw_day, str) or not _DATE_TEXT.fullmatch(raw_day):
            raise ValueError("CSI benchmark tradeDate must be YYYYMMDD")
        try:
            day = date(int(raw_day[:4]), int(raw_day[4:6]), int(raw_day[6:]))
        except ValueError as exc:
            raise ValueError("CSI benchmark tradeDate is invalid") from exc
        if day < start or day > end:
            raise ValueError("CSI benchmark row exceeds requested range")
        if day in seen_dates:
            raise ValueError(
                "CSI benchmark rows do not match expected trading calendar: "
                f"duplicate date {day}"
            )
        seen_dates.add(day)
        if (
            row.get("indexCode") != INDEX_CODE
            or row.get("indexNameCnAll") != INDEX_NAME_CN_ALL
            or row.get("indexNameEnAll") != INDEX_NAME_EN_ALL
        ):
            raise ValueError("CSI benchmark identity drift")
        raw_close = row.get("close")
        if type(raw_close) not in (int, Decimal):
            raise ValueError("CSI benchmark close must be numeric")
        close = Decimal(raw_close)
        if not close.is_finite() or close <= 0:
            raise ValueError("CSI benchmark close must be finite and positive")
        if day in _EXCLUDED_OFFICIAL_CLOSES:
            if day in expected_set:
                raise ValueError("approved exclusion date is marked trading by calendar")
            if close != _EXCLUDED_OFFICIAL_CLOSES[day]:
                raise ValueError("approved exclusion official close changed")
            row_hash = hashlib.sha256(_canonical_json(row).encode("utf-8")).hexdigest()
            exclusions.append(BenchmarkExclusion(
                excluded_date=day,
                official_close=close,
                calendar_verdict="NON_TRADING_DAY",
                exclusion_reason=_EXCLUSION_REASON,
                evidence_ref=f"{SOURCE_ID}:{response_hash}:data[{row_index}]:{row_hash}",
                rule_version=exclusion_rule_version,
            ))
            continue
        observations.append(BenchmarkObservation(
            trade_date=day,
            index_code=INDEX_CODE,
            index_name_cn_all=INDEX_NAME_CN_ALL,
            index_name_en_all=INDEX_NAME_EN_ALL,
            close=close,
            source_response_hash=response_hash,
            fetched_at_utc=fetched_at_utc,
            evidence_ref=f"{SOURCE_ID}:{response_hash}:{raw_day}",
        ))
    observations.sort(key=lambda item: item.trade_date)
    actual_dates = tuple(item.trade_date for item in observations)
    if actual_dates != expected:
        actual_set = set(actual_dates)
        expected_set = set(expected)
        duplicates = sorted(day for day, count in Counter(actual_dates).items() if count > 1)
        raise ValueError(
            "CSI benchmark rows do not match expected trading calendar: "
            f"missing={sorted(expected_set - actual_set)[:10]}, "
            f"extra={sorted(actual_set - expected_set)[:10]}, "
            f"duplicates={duplicates[:10]}"
        )
    exclusions.sort(key=lambda item: item.excluded_date)
    excluded_dates = tuple(item.excluded_date for item in exclusions)
    flags = ("benchmark_excluded_dates",) if exclusions else ()
    return BenchmarkFetch(
        raw_response,
        response_hash,
        fetched_at_utc,
        tuple(
            BenchmarkObservation(
                trade_date=item.trade_date,
                index_code=item.index_code,
                index_name_cn_all=item.index_name_cn_all,
                index_name_en_all=item.index_name_en_all,
                close=item.close,
                source_response_hash=item.source_response_hash,
                fetched_at_utc=item.fetched_at_utc,
                evidence_ref=item.evidence_ref,
                quality_flags=flags,
                excluded_dates=excluded_dates,
                exclusion_evidence=tuple(exclusions),
            )
            for item in observations
        ),
        tuple(exclusions),
    )


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def fetch_official_benchmark(
    start: date,
    end: date,
    *,
    expected_trading_dates: tuple[date, ...],
    transport: Callable[[str, Mapping[str, str]], bytes] | None = None,
    fetched_at_utc: datetime | None = None,
) -> BenchmarkFetch:
    """Fetch official bytes directly; the caller must publish an immutable snapshot."""

    endpoint, params = build_request(start, end)
    if transport is None:
        import requests  # optional sync dependency

        def transport(url: str, query: Mapping[str, str]) -> bytes:
            response = requests.get(
                url,
                params=query,
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
            return response.content

    raw = transport(endpoint, params)
    return parse_official_response(
        raw,
        start=start,
        end=end,
        expected_trading_dates=expected_trading_dates,
        fetched_at_utc=fetched_at_utc or datetime.now(timezone.utc),
    )


__all__ = [
    "APPROVED_EXCLUSION_RULE_VERSIONS", "BenchmarkExclusion", "BenchmarkFetch",
    "BenchmarkObservation", "CURRENT_EXCLUSION_RULE_VERSION", "ENDPOINT",
    "EXCLUSION_POLICY", "INDEX_CODE", "SOURCE_ID",
    "build_request", "fetch_official_benchmark", "parse_official_response",
]
