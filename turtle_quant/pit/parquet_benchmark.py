"""Verified H00985 snapshot reader with snapshot-scoped audit timestamp."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
from pathlib import Path

from turtle_quant.adapters.csindex_benchmark import (
    APPROVED_EXCLUSION_RULE_VERSIONS,
    BenchmarkObservation,
    CURRENT_EXCLUSION_RULE_VERSION,
    EXCLUSION_POLICY,
    INDEX_CODE,
    parse_official_response,
)
from turtle_quant.storage.benchmark import (
    BENCHMARK_COLUMNS,
    BENCHMARK_DOMAIN,
    PARQUET_RELATIVE_PATH,
    RAW_RELATIVE_PATH,
    benchmark_snapshot_rows,
    expected_benchmark_dates,
)
from turtle_quant.storage.parquet import read_parquet_rows
from turtle_quant.storage.snapshot import normalize_fetch_time_utc
from turtle_quant.storage.verification import verify_published_domain


class ParquetBenchmarkReader:
    """Read one snapshot and attach its own provenance to every returned row.

    Fetch time comes from ``source_provenance.csindex.fetch_time_utc``. The
    exclusion marker, full date list and structured evidence are snapshot-wide:
    queries do not filter them by their requested date interval.
    """

    def __init__(self, storage_root: str | Path, snapshot_id: str) -> None:
        self.storage_root = Path(storage_root)
        self.snapshot_id = snapshot_id
        verified = verify_published_domain(self.storage_root, snapshot_id, BENCHMARK_DOMAIN)
        paths = {
            path.relative_to(verified.snapshot_path).as_posix(): path
            for path in verified.file_paths
        }
        if set(paths) != {RAW_RELATIVE_PATH, PARQUET_RELATIVE_PATH}:
            raise ValueError("benchmark snapshot file whitelist is invalid")
        details = verified.domain_details
        try:
            start = date.fromisoformat(_required_text(details.get("start_date"), "start_date"))
            end = date.fromisoformat(_required_text(details.get("end_date"), "end_date"))
            calendar_id = _required_text(details.get("calendar_snapshot_id"), "calendar_snapshot_id")
            response_hash = _required_text(details.get("response_hash"), "response_hash")
        except ValueError as exc:
            raise ValueError("benchmark snapshot details are invalid") from exc
        if end < start:
            raise ValueError("benchmark snapshot date range is invalid")
        source = verified.source_provenance.get("csindex")
        if not isinstance(source, Mapping):
            raise ValueError("benchmark snapshot lacks source_provenance.csindex")
        fetch_time_text = _required_text(source.get("fetch_time_utc"), "fetch_time_utc")
        if normalize_fetch_time_utc(fetch_time_text) != fetch_time_text:
            raise ValueError("benchmark audit fetch_time_utc must use canonical UTC text")
        fetched_at = datetime.fromisoformat(fetch_time_text.replace("Z", "+00:00"))
        if fetched_at.tzinfo != timezone.utc:
            raise ValueError("benchmark audit fetch_time_utc must be UTC")
        if source.get("response_hash") != response_hash:
            raise ValueError("benchmark audit response hash differs from domain details")
        raw = paths[RAW_RELATIVE_PATH].read_bytes()
        if hashlib.sha256(raw).hexdigest() != response_hash:
            raise ValueError("benchmark raw response hash differs from metadata")
        stored_evidence = details.get("exclusion_evidence", ())
        if not isinstance(stored_evidence, tuple):
            raise ValueError("benchmark exclusion evidence must be a list")
        evidence_version: str | None = None
        if stored_evidence:
            if not all(isinstance(item, Mapping) for item in stored_evidence):
                raise ValueError("benchmark exclusion evidence must contain objects")
            versions = tuple(item.get("rule_version") for item in stored_evidence)
            if (
                any(type(item) is not str or item not in APPROVED_EXCLUSION_RULE_VERSIONS
                    for item in versions)
                or len(set(versions)) != 1
            ):
                raise ValueError("benchmark exclusion evidence has an unapproved rule version")
            evidence_version = versions[0]
        expected = expected_benchmark_dates(self.storage_root, calendar_id, start, end)
        parsed = parse_official_response(
            raw,
            start=start,
            end=end,
            expected_trading_dates=expected,
            fetched_at_utc=fetched_at,
            exclusion_rule_version=evidence_version or CURRENT_EXCLUSION_RULE_VERSION,
        )
        excluded_dates = tuple(item.excluded_date for item in parsed.exclusions)
        encoded_dates = tuple(item.isoformat() for item in excluded_dates)
        stored_dates = details.get("benchmark_excluded_dates", ())
        marker = "benchmark_excluded_dates"
        if (
            not isinstance(stored_dates, tuple)
            or stored_dates != encoded_dates
            or not isinstance(stored_evidence, tuple)
            or stored_evidence != tuple(item.to_dict() for item in parsed.exclusions)
            or (marker in verified.quality_flags) != bool(parsed.exclusions)
            or (marker in verified.snapshot_quality_flags) != bool(parsed.exclusions)
        ):
            raise ValueError("benchmark exclusion metadata differs from raw response")
        if parsed.exclusions and (
            source.get("exclusion_policy") != EXCLUSION_POLICY
            or details.get("exclusion_policy") != EXCLUSION_POLICY
            or details.get("raw_row_count") != len(parsed.observations) + len(parsed.exclusions)
        ):
            raise ValueError("benchmark exclusion policy or raw count is invalid")
        physical = read_parquet_rows(paths[PARQUET_RELATIVE_PATH])
        stable_rows = benchmark_snapshot_rows(parsed)
        normalized_rows = tuple(
            {
                key: str(value) if isinstance(value, Decimal) else value
                for key, value in row.items()
            }
            for row in stable_rows
        )
        if (
            verified.row_count != len(normalized_rows)
            or len(physical) != len(normalized_rows)
            or any(set(row) != set(BENCHMARK_COLUMNS) for row in physical)
            or tuple(physical) != normalized_rows
        ):
            raise ValueError("benchmark Parquet rows differ from verified raw response")
        self.calendar_snapshot_id = calendar_id
        self.start_date = start
        self.end_date = end
        self.response_hash = response_hash
        self.fetched_at_utc = fetched_at
        self.observations = parsed.observations
        self.quality_flags = verified.quality_flags
        self.excluded_dates = excluded_dates
        self.exclusion_evidence = parsed.exclusions
        self.exclusion_rule_version = evidence_version

    def values(self, index_id: str, start: date, end: date) -> tuple[BenchmarkObservation, ...]:
        if index_id != INDEX_CODE:
            raise ValueError("benchmark index_id must be H00985")
        if type(start) is not date or type(end) is not date or end < start:
            raise ValueError("benchmark request dates must be ordered dates")
        if start < self.start_date or end > self.end_date:
            raise ValueError("benchmark request exceeds snapshot coverage")
        expected = expected_benchmark_dates(
            self.storage_root, self.calendar_snapshot_id, start, end
        )
        selected = tuple(
            item for item in self.observations if start <= item.trade_date <= end
        )
        if tuple(item.trade_date for item in selected) != expected:
            raise ValueError("benchmark query is not complete against its calendar")
        return selected


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be non-empty text")
    return value


__all__ = ["ParquetBenchmarkReader"]
