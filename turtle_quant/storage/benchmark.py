"""Immutable H00985 snapshot publication using the v1 content identity."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from turtle_quant.adapters.csindex_benchmark import (
    BenchmarkFetch,
    CURRENT_EXCLUSION_RULE_VERSION,
    ENDPOINT,
    EXCLUSION_POLICY,
    INDEX_CODE,
    SOURCE_ID,
    build_request,
    parse_official_response,
)
from turtle_quant.storage.parquet import read_parquet_rows, write_parquet_rows
from turtle_quant.storage.snapshot import (
    IngestConfig,
    SnapshotSession,
    _canonical_json,
    normalize_fetch_time_utc,
)
from turtle_quant.storage.verification import verify_published_domain


BENCHMARK_DOMAIN = "benchmark"
RAW_RELATIVE_PATH = "raw/response.json"
PARQUET_RELATIVE_PATH = "benchmark/values.parquet"
NORMALIZATION_VERSION = "csindex_benchmark_v1"
BENCHMARK_COLUMNS = (
    "schema_version",
    "normalization_version",
    "source_name",
    "source_row_hash",
    "evidence_ref",
    "trade_date",
    "index_code",
    "index_name_cn_all",
    "index_name_en_all",
    "close",
    "response_hash",
)


def expected_benchmark_dates(
    storage_root: str | Path,
    calendar_snapshot_id: str,
    start: date,
    end: date,
) -> tuple[date, ...]:
    """Derive every Chinese trading day from an explicit verified calendar."""

    build_request(start, end)
    verified = verify_published_domain(storage_root, calendar_snapshot_id, "calendar")
    by_date: dict[date, bool] = {}
    for path in verified.file_paths:
        if path.suffix != ".parquet":
            raise ValueError("calendar domain contains a non-Parquet data file")
        for row in read_parquet_rows(path):
            if row.get("exchange") != "cn":
                continue
            raw_day = row.get("date")
            if not isinstance(raw_day, str):
                raise ValueError("calendar row date must be ISO text")
            day = date.fromisoformat(raw_day)
            if not start <= day <= end:
                continue
            value = row.get("is_trading_day")
            if type(value) is not bool or day in by_date:
                raise ValueError("calendar row is ambiguous or duplicated")
            by_date[day] = value
    span = tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))
    if any(day not in by_date for day in span):
        raise ValueError("calendar snapshot has a date gap in benchmark range")
    return tuple(day for day in span if by_date[day])


def benchmark_snapshot_rows(fetch: BenchmarkFetch) -> tuple[dict[str, object], ...]:
    """Create stable physical Parquet rows; fetch time is audit-only meta."""

    payload = json.loads(fetch.raw_response.decode("utf-8"), parse_float=Decimal)
    raw_hashes = {
        row["tradeDate"]: hashlib.sha256(_canonical_json(row).encode("utf-8")).hexdigest()
        for row in payload["data"]
    }
    rows: list[dict[str, object]] = []
    for observation in fetch.observations:
        source_row = {
            "trade_date": observation.trade_date.isoformat(),
            "index_code": observation.index_code,
            "index_name_cn_all": observation.index_name_cn_all,
            "index_name_en_all": observation.index_name_en_all,
            "close": observation.close,
        }
        rows.append({
            "schema_version": 1,
            "normalization_version": NORMALIZATION_VERSION,
            "source_name": SOURCE_ID,
            "source_row_hash": raw_hashes[observation.trade_date.strftime("%Y%m%d")],
            "evidence_ref": observation.evidence_ref,
            **source_row,
            "response_hash": fetch.source_response_hash,
        })
    return tuple(rows)


def publish_benchmark_snapshot(
    storage_root: str | Path,
    fetch: BenchmarkFetch,
    *,
    calendar_snapshot_id: str,
    start: date,
    end: date,
) -> str:
    """Publish one benchmark cohort after rechecking raw bytes and calendar."""

    if not isinstance(fetch, BenchmarkFetch):
        raise ValueError("fetch must be BenchmarkFetch")
    root = Path(storage_root).resolve()
    expected = expected_benchmark_dates(root, calendar_snapshot_id, start, end)
    if not expected:
        raise ValueError("benchmark range contains no trading days")
    if any(
        item.rule_version != CURRENT_EXCLUSION_RULE_VERSION
        for item in fetch.exclusions
    ):
        raise ValueError("new benchmark snapshots require the current exclusion rule version")
    audited_time = normalize_fetch_time_utc(fetch.fetched_at_utc)
    parsed = parse_official_response(
        fetch.raw_response,
        start=start,
        end=end,
        expected_trading_dates=expected,
        fetched_at_utc=fetch.fetched_at_utc,
    )
    if (
        parsed.source_response_hash != fetch.source_response_hash
        or parsed.observations != fetch.observations
        or parsed.exclusions != fetch.exclusions
    ):
        raise ValueError("benchmark fetch object differs from the raw response")
    stable_source = {
        "csindex": {
            "source_id": SOURCE_ID,
            "endpoint": ENDPOINT,
            "index_code": INDEX_CODE,
            "calendar_snapshot_id": calendar_snapshot_id,
        }
    }
    # The interval end is a stable cohort label, not the actual fetch date.
    config = IngestConfig(
        ingest_calendar_date=end,
        steps=(BENCHMARK_DOMAIN,),
        start_date=start,
        end_date=end,
        max_symbols=None,
        board_filter_version="benchmark_not_applicable_v1",
        source_provenance_template=stable_source,
    )
    session = SnapshotSession.start(root, config)
    session.set_source_provenance("csindex", {
        "fetch_time_utc": audited_time,
        "response_hash": parsed.source_response_hash,
        "exclusion_policy": EXCLUSION_POLICY,
    })
    raw_path = session.staging_path / RAW_RELATIVE_PATH
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(parsed.raw_response)
    parquet_path = session.staging_path / PARQUET_RELATIVE_PATH
    write_parquet_rows(parquet_path, benchmark_snapshot_rows(parsed), sort_keys=("trade_date",))
    session.complete_domain(
        BENCHMARK_DOMAIN,
        files=(raw_path, parquet_path),
        row_count=len(parsed.observations),
        quality_flags=("benchmark_excluded_dates",) if parsed.exclusions else (),
        details={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "calendar_snapshot_id": calendar_snapshot_id,
            "response_hash": parsed.source_response_hash,
            "normalization_version": NORMALIZATION_VERSION,
            "exclusion_policy": EXCLUSION_POLICY,
            "benchmark_excluded_dates": [
                item.excluded_date.isoformat() for item in parsed.exclusions
            ],
            "exclusion_evidence": [item.to_dict() for item in parsed.exclusions],
            "raw_row_count": len(parsed.observations) + len(parsed.exclusions),
        },
    )
    universe_hash = hashlib.sha256(b"benchmark-index:H00985:v1").hexdigest()
    return session.publish(universe_hash=universe_hash, source_descriptors=stable_source)


__all__ = [
    "BENCHMARK_COLUMNS", "BENCHMARK_DOMAIN", "NORMALIZATION_VERSION",
    "PARQUET_RELATIVE_PATH", "RAW_RELATIVE_PATH", "benchmark_snapshot_rows",
    "expected_benchmark_dates", "publish_benchmark_snapshot",
]
