"""Fail-closed stage-A PIT reader for explicitly selected Parquet snapshots."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from types import MappingProxyType

from turtle_quant.core.manifest import RunManifest
from turtle_quant.core.market_data import (
    AdjustmentFactorObservation,
    CoverageIssue,
    CoverageIssueType,
    PriceBarSeries,
    RATE_SERIES_ID,
    RateObservation,
    RawPriceBar,
)
from turtle_quant.core.types import NonNegativePct
from turtle_quant.storage.verification import (
    VerifiedSnapshotDomain,
    verify_published_domain,
)


RULES_VERSION = "v1.2.0"
_CANONICAL_SECURITY = re.compile(r"^(sh|sz)\.\d{6}$")
_MARKET_SHARD = re.compile(r"^part-(\d{5})\.parquet$")


class ParquetFoundationError(ValueError):
    """Base class for trusted-reader contract failures."""


class SnapshotCoverageError(ParquetFoundationError):
    """Raised when a research request exceeds frozen snapshot coverage."""


class ParquetSchemaError(ParquetFoundationError):
    """Raised when a Parquet domain does not match its explicit whitelist."""


class ParquetDataIntegrityError(ParquetFoundationError):
    """Raised when rows are internally ambiguous or inconsistent."""


@dataclass(frozen=True)
class _Coverage:
    start: date
    end: date


@dataclass(frozen=True)
class _SecurityInterval:
    security_id: str
    listing_date: date
    delisting_date: date | None
    board_effective_from: date
    board_effective_to: date | None

    def active_on(self, day: date) -> bool:
        return (
            self.listing_date <= day
            and (self.delisting_date is None or day <= self.delisting_date)
            and self.board_effective_from <= day
            and (
                self.board_effective_to is None
                or day <= self.board_effective_to
            )
        )


_DOMAIN_CONTRACTS: Mapping[str, tuple[int, str, frozenset[str]]] = {
    "security_master": (
        1,
        "cn_equity_v1",
        frozenset(
            {
                "security_id",
                "board",
                "board_effective_from",
                "board_effective_to",
                "listing_date",
                "delisting_date",
                "schema_version",
                "normalization_version",
                "source_row_hash",
                "evidence_ref",
            }
        ),
    ),
    "market_daily": (
        1,
        "market_raw_v1",
        frozenset(
            {
                "security_id",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "paused",
                "adjust_type",
                "schema_version",
                "normalization_version",
                "source_row_hash",
                "evidence_ref",
            }
        ),
    ),
    "adjustment_factors": (
        1,
        "adjustment_factor_v1",
        frozenset(
            {
                "security_id",
                "ex_date",
                "factor",
                "factor_source",
                "available_at",
                "schema_version",
                "normalization_version",
                "source_row_hash",
                "evidence_ref",
            }
        ),
    ),
    "calendar": (
        1,
        "cn_calendar_v1",
        frozenset(
            {
                "exchange",
                "date",
                "is_trading_day",
                "schema_version",
                "normalization_version",
                "source_row_hash",
                "evidence_ref",
            }
        ),
    ),
    "chinabond_10y": (
        1,
        "chinabond_10y_v1",
        frozenset(
            {
                "obs_date",
                "yield_10y_pct",
                "curve_id",
                "curve_name",
                "tenor",
                "available_at",
                "schema_version",
                "normalization_version",
                "source_row_hash",
                "evidence_ref",
            }
        ),
    ),
}


def _require_pyarrow() -> tuple[object, object]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError(
            "pyarrow is required for the Parquet foundation reader"
        ) from exc
    return pa, pq


def _strict_date(value: object, field: str) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ParquetDataIntegrityError(
                f"{field} must be an ISO date"
            ) from exc
        if parsed.isoformat() != value:
            raise ParquetDataIntegrityError(f"{field} must be a canonical ISO date")
        return parsed
    raise ParquetDataIntegrityError(f"{field} must be a date or ISO date string")


def _request_date(value: object, field: str) -> date:
    if type(value) is not date:
        raise ValueError(f"{field} must be a date without a time component")
    return value


def _canonical_security(value: object) -> str:
    if not isinstance(value, str) or not _CANONICAL_SECURITY.fullmatch(value):
        raise ValueError("security_id must use canonical sh.600000 form")
    return value


def _decimal(value: object, field: str, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    if isinstance(value, bool):
        raise ParquetDataIntegrityError(f"{field} must be numeric")
    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ParquetDataIntegrityError(f"{field} must be numeric") from exc
    if not converted.is_finite():
        raise ParquetDataIntegrityError(f"{field} must be finite")
    return converted


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise ParquetDataIntegrityError(f"{field} must be a non-empty string")
    return value


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


class ParquetFoundationReader:
    """Read only the five v1.2.0 stage-A domains from verified snapshots."""

    def __init__(
        self,
        storage_root: str | Path,
        *,
        security_master_snapshot_id: str,
        market_daily_snapshot_id: str,
        adjustment_factors_snapshot_id: str,
        calendar_snapshot_id: str,
        rate_snapshot_id: str,
    ) -> None:
        if not (
            security_master_snapshot_id
            == market_daily_snapshot_id
            == adjustment_factors_snapshot_id
        ):
            raise ValueError(
                "security_master, market_daily, and adjustment_factors must use "
                "the same snapshot"
            )
        _require_pyarrow()
        self.storage_root = Path(storage_root)
        selected_ids = {
            "security_master": security_master_snapshot_id,
            "market_daily": market_daily_snapshot_id,
            "adjustment_factors": adjustment_factors_snapshot_id,
            "calendar": calendar_snapshot_id,
            "chinabond_10y": rate_snapshot_id,
        }
        verified = {
            domain: verify_published_domain(
                self.storage_root, snapshot_id, domain
            )
            for domain, snapshot_id in selected_ids.items()
        }
        self._domains: Mapping[str, VerifiedSnapshotDomain] = MappingProxyType(
            verified
        )
        self._coverage: Mapping[str, _Coverage] = MappingProxyType(
            {
                domain: self._parse_coverage(item)
                for domain, item in verified.items()
            }
        )
        for domain, item in verified.items():
            self._validate_domain_schema(domain, item)

        primary_hashes = {
            verified[domain].universe_hash
            for domain in (
                "security_master",
                "market_daily",
                "adjustment_factors",
            )
        }
        if len(primary_hashes) != 1:
            raise ParquetDataIntegrityError(
                "primary stage-A domains disagree on universe_hash"
            )
        self.universe_hash = next(iter(primary_hashes))
        self.snapshot_ids = tuple(sorted(set(selected_ids.values())))
        self.data_quality_flags = tuple(
            sorted(
                {
                    flag
                    for item in verified.values()
                    for flag in item.quality_flags
                }
            )
        )
        self.source_versions = MappingProxyType(
            self._source_versions(verified)
        )

        self._security_intervals = self._load_security_intervals()
        by_security: dict[str, list[_SecurityInterval]] = defaultdict(list)
        for interval in self._security_intervals:
            by_security[interval.security_id].append(interval)
        self._security_by_id: Mapping[str, tuple[_SecurityInterval, ...]] = (
            MappingProxyType(
                {
                    key: tuple(sorted(value, key=lambda item: item.board_effective_from))
                    for key, value in by_security.items()
                }
            )
        )
        self._calendar = MappingProxyType(self._load_calendar())
        self._market_shards, self._market_generic_files = self._index_market_files()
        raw_missing = verified["market_daily"].domain_details.get(
            "missing_security_ids", ()
        )
        if not isinstance(raw_missing, tuple):
            raise ParquetDataIntegrityError(
                "market_daily missing_security_ids must be a list"
            )
        missing: set[str] = set()
        for security_id in raw_missing:
            try:
                missing.add(_canonical_security(security_id))
            except ValueError as exc:
                raise ParquetDataIntegrityError(
                    "market_daily missing_security_ids contains a noncanonical ID"
                ) from exc
        self._missing_market_security_ids = frozenset(missing)

    @staticmethod
    def _parse_coverage(item: VerifiedSnapshotDomain) -> _Coverage:
        raw_start = item.config.get("start_date")
        raw_end = item.config.get("end_date")
        if not isinstance(raw_start, str) or not isinstance(raw_end, str):
            raise SnapshotCoverageError(
                f"{item.domain} snapshot has no explicit start_date/end_date"
            )
        try:
            start = date.fromisoformat(raw_start)
            end = date.fromisoformat(raw_end)
        except ValueError as exc:
            raise SnapshotCoverageError(
                f"{item.domain} snapshot coverage is not ISO date data"
            ) from exc
        if end < start:
            raise SnapshotCoverageError(
                f"{item.domain} snapshot coverage end precedes start"
            )
        return _Coverage(start, end)

    @staticmethod
    def _source_versions(
        verified: Mapping[str, VerifiedSnapshotDomain],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for domain, item in sorted(verified.items()):
            for source, descriptor in sorted(item.source_descriptors.items()):
                result[f"{domain}:{source}"] = json.dumps(
                    _jsonable(descriptor),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
        return result

    @staticmethod
    def _column_values(file_path: Path, column: str) -> set[object]:
        _pa, pq = _require_pyarrow()
        parquet = pq.ParquetFile(file_path)
        index = parquet.schema_arrow.get_field_index(column)
        if index < 0:
            raise ParquetSchemaError(f"{file_path} has no {column} column")
        values: set[object] = set()
        fallback_groups: list[int] = []
        for row_group in range(parquet.num_row_groups):
            metadata = parquet.metadata.row_group(row_group).column(index)
            statistics = metadata.statistics
            if (
                statistics is not None
                and statistics.has_min_max
                and statistics.min == statistics.max
            ):
                values.add(statistics.min)
            else:
                fallback_groups.append(row_group)
        for row_group in fallback_groups:
            table = parquet.read_row_group(row_group, columns=[column])
            values.update(table.column(column).to_pylist())
        return values

    def _validate_domain_schema(
        self, domain: str, item: VerifiedSnapshotDomain
    ) -> None:
        expected_schema, expected_normalization, required = _DOMAIN_CONTRACTS[
            domain
        ]
        _pa, pq = _require_pyarrow()
        row_count = 0
        for file_path in item.file_paths:
            if file_path.suffix.lower() != ".parquet":
                raise ParquetSchemaError(
                    f"{domain} whitelist contains a non-Parquet file"
                )
            try:
                parquet = pq.ParquetFile(file_path)
            except Exception as exc:
                raise ParquetSchemaError(
                    f"cannot open {domain} Parquet file: {file_path}"
                ) from exc
            file_rows = parquet.metadata.num_rows
            row_count += file_rows
            columns = set(parquet.schema_arrow.names)
            # The ingestion writer can produce one zero-row, zero-column shard
            # when every selected security in that prefix has no provider bars.
            # Its identity is still verified by the snapshot hash and its
            # securities are recorded in missing_security_ids.  There are no
            # row versions to validate; non-empty files never receive this
            # exception.
            if file_rows == 0 and not columns:
                continue
            missing = sorted(required.difference(columns))
            if missing:
                raise ParquetSchemaError(
                    f"{domain} file {file_path.name} is missing required "
                    f"columns: {missing}"
                )
            if self._column_values(file_path, "schema_version") != {
                expected_schema
            }:
                raise ParquetSchemaError(
                    f"{domain} schema_version is not whitelisted"
                )
            if self._column_values(file_path, "normalization_version") != {
                expected_normalization
            }:
                raise ParquetSchemaError(
                    f"{domain} normalization_version is not whitelisted"
                )
        if row_count != item.row_count:
            raise ParquetDataIntegrityError(
                f"{domain} Parquet row count disagrees with verified metadata"
            )

    @staticmethod
    def _read_rows(
        file_paths: Sequence[Path],
        *,
        columns: Sequence[str],
        filters: Sequence[tuple[str, str, object]] | None = None,
        domain: str,
    ) -> list[dict[str, object]]:
        _pa, pq = _require_pyarrow()
        rows: list[dict[str, object]] = []
        for file_path in file_paths:
            try:
                table = pq.read_table(
                    file_path,
                    columns=list(columns),
                    filters=list(filters) if filters is not None else None,
                )
            except Exception as exc:
                raise ParquetDataIntegrityError(
                    f"failed to read verified {domain} file {file_path}"
                ) from exc
            rows.extend(table.to_pylist())
        return rows

    def _load_security_intervals(self) -> tuple[_SecurityInterval, ...]:
        rows = self._read_rows(
            self._domains["security_master"].file_paths,
            columns=(
                "security_id",
                "board",
                "board_effective_from",
                "board_effective_to",
                "listing_date",
                "delisting_date",
            ),
            domain="security_master",
        )
        result: list[_SecurityInterval] = []
        keys: set[tuple[str, date]] = set()
        for row in rows:
            if row.get("board") != "main_board":
                continue
            try:
                security_id = _canonical_security(row.get("security_id"))
            except ValueError as exc:
                raise ParquetDataIntegrityError(
                    "security_master contains a noncanonical security_id"
                ) from exc
            listing = _strict_date(row.get("listing_date"), "listing_date")
            raw_delisting = row.get("delisting_date")
            delisting = (
                _strict_date(raw_delisting, "delisting_date")
                if raw_delisting is not None
                else None
            )
            effective_from = _strict_date(
                row.get("board_effective_from"), "board_effective_from"
            )
            raw_effective_to = row.get("board_effective_to")
            effective_to = (
                _strict_date(raw_effective_to, "board_effective_to")
                if raw_effective_to is not None
                else None
            )
            if delisting is not None and delisting < listing:
                raise ParquetDataIntegrityError(
                    "security_master delisting precedes listing"
                )
            if effective_to is not None and effective_to < effective_from:
                raise ParquetDataIntegrityError(
                    "security_master board interval is reversed"
                )
            key = (security_id, effective_from)
            if key in keys:
                raise ParquetDataIntegrityError(
                    "security_master contains a duplicate board interval"
                )
            keys.add(key)
            result.append(
                _SecurityInterval(
                    security_id,
                    listing,
                    delisting,
                    effective_from,
                    effective_to,
                )
            )
        return tuple(
            sorted(result, key=lambda item: (item.security_id, item.board_effective_from))
        )

    def _load_calendar(self) -> dict[date, bool]:
        rows = self._read_rows(
            self._domains["calendar"].file_paths,
            columns=(
                "exchange",
                "date",
                "is_trading_day",
                "evidence_ref",
                "source_row_hash",
            ),
            domain="calendar",
        )
        result: dict[date, bool] = {}
        for row in rows:
            if row.get("exchange") != "cn":
                raise ParquetDataIntegrityError(
                    "calendar contains an unsupported exchange"
                )
            day = _strict_date(row.get("date"), "calendar date")
            trading = row.get("is_trading_day")
            if type(trading) is not bool:
                raise ParquetDataIntegrityError(
                    "calendar is_trading_day must be bool"
                )
            _text(row.get("evidence_ref"), "calendar evidence_ref")
            _text(row.get("source_row_hash"), "calendar source_row_hash")
            if day in result:
                raise ParquetDataIntegrityError(
                    "calendar contains duplicate dates"
                )
            result[day] = trading
        coverage = self._coverage["calendar"]
        cursor = coverage.start
        buffer_end = coverage.end + timedelta(days=10)
        while cursor <= buffer_end:
            if cursor not in result:
                raise ParquetDataIntegrityError(
                    f"calendar coverage has a missing date: {cursor}"
                )
            cursor += timedelta(days=1)
        return result

    def _index_market_files(
        self,
    ) -> tuple[Mapping[str, tuple[Path, ...]], tuple[Path, ...]]:
        shards: dict[str, list[Path]] = defaultdict(list)
        generic: list[Path] = []
        for file_path in self._domains["market_daily"].file_paths:
            match = _MARKET_SHARD.fullmatch(file_path.name)
            if match is None:
                generic.append(file_path)
            else:
                shards[match.group(1)].append(file_path)
        return (
            MappingProxyType(
                {
                    key: tuple(sorted(paths))
                    for key, paths in shards.items()
                }
            ),
            tuple(sorted(generic)),
        )

    def _require_day(self, domain: str, day: date) -> None:
        coverage = self._coverage[domain]
        if day < coverage.start or day > coverage.end:
            raise SnapshotCoverageError(
                f"{domain} requested date {day} is outside "
                f"[{coverage.start}, {coverage.end}]"
            )

    def _query_range(
        self,
        domain: str,
        start: date,
        end: date,
        as_of: date,
    ) -> date:
        start = _request_date(start, "start")
        end = _request_date(end, "end")
        as_of = _request_date(as_of, "as_of")
        if end < start:
            raise ValueError("end cannot precede start")
        if start > as_of:
            raise ValueError("start cannot follow as_of")
        self._require_day(domain, start)
        self._require_day(domain, end)
        self._require_day(domain, as_of)
        return min(end, as_of)

    @staticmethod
    def _exchange(exchange: object) -> str:
        if exchange != "cn":
            raise ValueError('exchange must be "cn"')
        return "cn"

    def security_ids_as_of(self, as_of: date) -> tuple[str, ...]:
        as_of = _request_date(as_of, "as_of")
        self._require_day("security_master", as_of)
        return tuple(
            sorted(
                {
                    interval.security_id
                    for interval in self._security_intervals
                    if interval.active_on(as_of)
                }
            )
        )

    def calendar_day(self, exchange: str, day: date) -> bool | None:
        self._exchange(exchange)
        day = _request_date(day, "day")
        self._require_day("calendar", day)
        return self._calendar.get(day)

    def previous_trading_day(self, exchange: str, day: date) -> date | None:
        self._exchange(exchange)
        day = _request_date(day, "day")
        self._require_day("calendar", day)
        coverage = self._coverage["calendar"]
        cursor = day - timedelta(days=1)
        while cursor >= coverage.start:
            state = self._calendar.get(cursor)
            if state is None:
                raise ParquetDataIntegrityError(
                    f"calendar coverage has a missing date: {cursor}"
                )
            if state:
                return cursor
            cursor -= timedelta(days=1)
        return None

    def next_trading_day(self, exchange: str, day: date) -> date | None:
        self._exchange(exchange)
        day = _request_date(day, "day")
        self._require_day("calendar", day)
        coverage = self._coverage["calendar"]
        limit = (
            coverage.end + timedelta(days=10)
            if day == coverage.end
            else coverage.end
        )
        cursor = day + timedelta(days=1)
        while cursor <= limit:
            state = self._calendar.get(cursor)
            if state is None:
                raise ParquetDataIntegrityError(
                    f"calendar coverage has a missing date: {cursor}"
                )
            if state:
                return cursor
            cursor += timedelta(days=1)
        return None

    def _trading_dates(self, start: date, end: date) -> tuple[date, ...]:
        result: list[date] = []
        cursor = start
        while cursor <= end:
            state = self._calendar.get(cursor)
            if state is None:
                raise ParquetDataIntegrityError(
                    f"calendar coverage has a missing date: {cursor}"
                )
            if state:
                result.append(cursor)
            cursor += timedelta(days=1)
        return tuple(result)

    def _security_active(self, security_id: str, day: date) -> bool:
        return any(
            interval.active_on(day)
            for interval in self._security_by_id.get(security_id, ())
        )

    @staticmethod
    def _market_bar(row: Mapping[str, object]) -> RawPriceBar:
        try:
            security_id = _canonical_security(row.get("security_id"))
        except ValueError as exc:
            raise ParquetDataIntegrityError(
                "market_daily contains a noncanonical security_id"
            ) from exc
        paused = row.get("paused")
        if paused is not None and type(paused) is not bool:
            raise ParquetDataIntegrityError("market_daily paused must be bool or null")
        try:
            return RawPriceBar(
                security_id=security_id,
                trade_date=_strict_date(row.get("trade_date"), "trade_date"),
                open=_decimal(row.get("open"), "open"),  # type: ignore[arg-type]
                high=_decimal(row.get("high"), "high"),  # type: ignore[arg-type]
                low=_decimal(row.get("low"), "low"),  # type: ignore[arg-type]
                close=_decimal(row.get("close"), "close"),  # type: ignore[arg-type]
                volume=_decimal(row.get("volume"), "volume", optional=True),
                amount=_decimal(row.get("amount"), "amount", optional=True),
                paused=paused,
                evidence_ref=_text(
                    row.get("evidence_ref"), "evidence_ref", optional=True
                ),
                source_row_hash=_text(
                    row.get("source_row_hash"),
                    "source_row_hash",
                    optional=True,
                ),
                adjust_type=str(row.get("adjust_type")),
            )
        except ValueError as exc:
            raise ParquetDataIntegrityError(
                f"invalid market_daily row for {security_id}"
            ) from exc

    def _market_files_for(self, security_id: str) -> tuple[Path, ...]:
        prefix = security_id.split(".", 1)[1][:5]
        return tuple(
            sorted(
                set(self._market_shards.get(prefix, ())).union(
                    self._market_generic_files
                )
            )
        )

    @staticmethod
    def _issue_locator(bar: RawPriceBar) -> str | None:
        if bar.evidence_ref is not None:
            return bar.evidence_ref
        if bar.source_row_hash is not None:
            return f"source_row_hash:{bar.source_row_hash}"
        return None

    @staticmethod
    def _group_issues(
        issue_type: CoverageIssueType,
        security_id: str,
        affected: Sequence[tuple[date, str | None]],
        trading_order: Mapping[date, int],
    ) -> list[CoverageIssue]:
        if not affected:
            return []
        ordered = sorted(set(affected), key=lambda item: item[0])
        result: list[CoverageIssue] = []
        group_start, group_end = ordered[0][0], ordered[0][0]
        evidence = ordered[0][1]
        for day, current_evidence in ordered[1:]:
            adjacent = (
                trading_order.get(day) is not None
                and trading_order.get(group_end) is not None
                and trading_order[day] == trading_order[group_end] + 1
            )
            if adjacent and current_evidence == evidence:
                group_end = day
                continue
            result.append(
                CoverageIssue(
                    issue_type,
                    security_id,
                    (group_start, group_end),
                    evidence,
                )
            )
            group_start = group_end = day
            evidence = current_evidence
        result.append(
            CoverageIssue(
                issue_type,
                security_id,
                (group_start, group_end),
                evidence,
            )
        )
        return result

    def _not_covered_series(
        self, security_id: str, start: date, end: date
    ) -> PriceBarSeries:
        issue = CoverageIssue(
            CoverageIssueType.SECURITY_NOT_COVERED,
            security_id,
            (start, end),
            None,
        )
        return PriceBarSeries(
            (),
            (issue,),
            self._domains["market_daily"].quality_flags,
        )

    def price_bars(
        self,
        security_id: str,
        start: date,
        end: date,
        *,
        as_of: date,
    ) -> PriceBarSeries:
        security_id = _canonical_security(security_id)
        effective_end = self._query_range(
            "market_daily", start, end, as_of
        )
        self._query_range("security_master", start, end, as_of)
        self._query_range("calendar", start, effective_end, as_of)
        if security_id in self._missing_market_security_ids:
            return self._not_covered_series(security_id, start, effective_end)
        if security_id not in self._security_by_id:
            return self._not_covered_series(security_id, start, effective_end)
        files = self._market_files_for(security_id)
        if not files:
            return self._not_covered_series(security_id, start, effective_end)
        rows = self._read_rows(
            files,
            columns=(
                "security_id",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "paused",
                "adjust_type",
                "evidence_ref",
                "source_row_hash",
            ),
            filters=(
                ("security_id", "=", security_id),
                ("trade_date", ">=", start.isoformat()),
                ("trade_date", "<=", effective_end.isoformat()),
            ),
            domain="market_daily",
        )
        bars = tuple(
            sorted(
                (self._market_bar(row) for row in rows),
                key=lambda item: (item.security_id, item.trade_date),
            )
        )
        keys = {(bar.security_id, bar.trade_date) for bar in bars}
        if len(keys) != len(bars):
            raise ParquetDataIntegrityError(
                "market_daily contains duplicate security/date rows"
            )
        if any(bar.security_id != security_id for bar in bars):
            raise ParquetDataIntegrityError(
                "market_daily filter returned another security"
            )

        trading_dates = self._trading_dates(start, effective_end)
        trading_set = set(trading_dates)
        expected = tuple(
            day
            for day in trading_dates
            if self._security_active(security_id, day)
        )
        for bar in bars:
            if bar.trade_date not in trading_set:
                raise ParquetDataIntegrityError(
                    "market_daily contains a bar on a non-trading date"
                )
            if not self._security_active(security_id, bar.trade_date):
                raise ParquetDataIntegrityError(
                    "market_daily contains a bar outside the security interval"
                )
        bars_by_day = {bar.trade_date: bar for bar in bars}
        trading_order = {day: index for index, day in enumerate(trading_dates)}
        issues: list[CoverageIssue] = []
        issues.extend(
            self._group_issues(
                CoverageIssueType.MISSING_BAR,
                security_id,
                tuple((day, None) for day in expected if day not in bars_by_day),
                trading_order,
            )
        )
        issues.extend(
            self._group_issues(
                CoverageIssueType.PAUSE_STATUS_UNKNOWN,
                security_id,
                tuple(
                    (bar.trade_date, self._issue_locator(bar))
                    for bar in bars
                    if bar.paused is None
                ),
                trading_order,
            )
        )
        issues.extend(
            self._group_issues(
                CoverageIssueType.EVIDENCE_MISSING,
                security_id,
                tuple(
                    (bar.trade_date, self._issue_locator(bar))
                    for bar in bars
                    if bar.evidence_ref is None or bar.source_row_hash is None
                ),
                trading_order,
            )
        )
        issues.sort(
            key=lambda item: (
                item.security_id,
                item.date_range[0],
                item.date_range[1],
                item.issue_type.value,
            )
        )
        return PriceBarSeries(
            bars,
            tuple(issues),
            self._domains["market_daily"].quality_flags,
        )

    @staticmethod
    def _factor(row: Mapping[str, object]) -> AdjustmentFactorObservation:
        try:
            security_id = _canonical_security(row.get("security_id"))
        except ValueError as exc:
            raise ParquetDataIntegrityError(
                "adjustment_factors contains a noncanonical security_id"
            ) from exc
        try:
            return AdjustmentFactorObservation(
                security_id=security_id,
                ex_date=_strict_date(row.get("ex_date"), "ex_date"),
                available_at=_strict_date(
                    row.get("available_at"), "available_at"
                ),
                cumulative_factor=_decimal(
                    row.get("factor"), "factor"
                ),  # type: ignore[arg-type]
                factor_source=_text(
                    row.get("factor_source"), "factor_source"
                ),  # type: ignore[arg-type]
                evidence_ref=_text(
                    row.get("evidence_ref"), "evidence_ref"
                ),  # type: ignore[arg-type]
                source_row_hash=_text(
                    row.get("source_row_hash"), "source_row_hash"
                ),  # type: ignore[arg-type]
            )
        except ValueError as exc:
            raise ParquetDataIntegrityError(
                f"invalid adjustment factor row for {security_id}"
            ) from exc

    def adjustment_factor_series(
        self,
        security_id: str,
        start: date,
        end: date,
        *,
        as_of: date,
    ) -> tuple[AdjustmentFactorObservation, ...]:
        security_id = _canonical_security(security_id)
        effective_end = self._query_range(
            "adjustment_factors", start, end, as_of
        )
        rows = self._read_rows(
            self._domains["adjustment_factors"].file_paths,
            columns=(
                "security_id",
                "ex_date",
                "factor",
                "factor_source",
                "available_at",
                "evidence_ref",
                "source_row_hash",
            ),
            filters=(
                ("security_id", "=", security_id),
                ("ex_date", "<=", effective_end.isoformat()),
                ("available_at", "<=", as_of.isoformat()),
            ),
            domain="adjustment_factors",
        )
        observations = [self._factor(row) for row in rows]
        by_key: dict[
            tuple[str, date, date], AdjustmentFactorObservation
        ] = {}
        for observation in observations:
            key = (
                observation.security_id,
                observation.ex_date,
                observation.available_at,
            )
            existing = by_key.get(key)
            if (
                existing is not None
                and existing.cumulative_factor != observation.cumulative_factor
            ):
                raise ParquetDataIntegrityError(
                    "conflicting cumulative factors for one PIT ordering key"
                )
            if existing is None or (
                observation.evidence_ref,
                observation.source_row_hash,
            ) < (existing.evidence_ref, existing.source_row_hash):
                by_key[key] = observation
        visible = tuple(
            sorted(
                by_key.values(),
                key=lambda item: (
                    item.ex_date,
                    item.available_at,
                    item.evidence_ref,
                ),
            )
        )
        before = [item for item in visible if item.ex_date < start]
        baseline_date = max((item.ex_date for item in before), default=None)
        return tuple(
            item
            for item in visible
            if item.ex_date >= start
            or (baseline_date is not None and item.ex_date == baseline_date)
        )

    @staticmethod
    def _rate(row: Mapping[str, object]) -> RateObservation:
        try:
            value = _decimal(row.get("yield_10y_pct"), "yield_10y_pct")
            assert value is not None
            return RateObservation(
                series=RATE_SERIES_ID,
                obs_date=_strict_date(row.get("obs_date"), "obs_date"),
                available_at=_strict_date(
                    row.get("available_at"), "available_at"
                ),
                value=NonNegativePct(value),
                curve_id=_text(
                    row.get("curve_id"), "curve_id"
                ),  # type: ignore[arg-type]
                curve_name=_text(
                    row.get("curve_name"), "curve_name"
                ),  # type: ignore[arg-type]
                tenor=_text(row.get("tenor"), "tenor"),  # type: ignore[arg-type]
                evidence_ref=_text(
                    row.get("evidence_ref"), "evidence_ref"
                ),  # type: ignore[arg-type]
                source_row_hash=_text(
                    row.get("source_row_hash"), "source_row_hash"
                ),  # type: ignore[arg-type]
            )
        except ValueError as exc:
            raise ParquetDataIntegrityError("invalid chinabond_10y row") from exc

    def _open_interval_trading_days(
        self, available_at: date, as_of: date
    ) -> int:
        coverage = self._coverage["calendar"]
        if available_at < coverage.start or as_of > coverage.end:
            raise SnapshotCoverageError(
                "rate staleness interval exceeds calendar research coverage"
            )
        cursor = available_at + timedelta(days=1)
        count = 0
        while cursor < as_of:
            state = self._calendar.get(cursor)
            if state is None:
                raise ParquetDataIntegrityError(
                    f"calendar coverage has a missing date: {cursor}"
                )
            if state:
                count += 1
            cursor += timedelta(days=1)
        return count

    def value_on(self, series: str, *, as_of: date) -> RateObservation | None:
        if series != RATE_SERIES_ID:
            raise ValueError(f"unknown rate series: {series!r}")
        as_of = _request_date(as_of, "as_of")
        self._require_day("chinabond_10y", as_of)
        self._require_day("calendar", as_of)
        rows = self._read_rows(
            self._domains["chinabond_10y"].file_paths,
            columns=(
                "obs_date",
                "yield_10y_pct",
                "curve_id",
                "curve_name",
                "tenor",
                "available_at",
                "evidence_ref",
                "source_row_hash",
            ),
            filters=(("available_at", "<=", as_of.isoformat()),),
            domain="chinabond_10y",
        )
        observations = [self._rate(row) for row in rows]
        values_by_key: dict[tuple[date, date], Decimal] = {}
        for observation in observations:
            key = (observation.obs_date, observation.available_at)
            existing = values_by_key.get(key)
            if existing is not None and existing != observation.value.value:
                raise ParquetDataIntegrityError(
                    "conflicting rates for one PIT ordering key"
                )
            values_by_key[key] = observation.value.value
        if not observations:
            return None
        selected = max(
            observations,
            key=lambda item: (
                item.available_at,
                item.obs_date,
                item.evidence_ref,
                item.source_row_hash,
            ),
        )
        if self._open_interval_trading_days(selected.available_at, as_of) > 0:
            return None
        return selected

    def build_run_manifest(
        self,
        *,
        run_id: str,
        as_of: date,
        code_version: str,
        config_hash: str,
        manifest_version: str = "1",
    ) -> RunManifest:
        as_of = _request_date(as_of, "as_of")
        for domain in self._domains:
            self._require_day(domain, as_of)
        return RunManifest(
            manifest_version=manifest_version,
            run_id=run_id,
            as_of=as_of,
            code_version=code_version,
            rules_version=RULES_VERSION,
            config_hash=config_hash,
            universe_hash=self.universe_hash,
            snapshot_ids=self.snapshot_ids,
            source_versions=self.source_versions,
            treasury_yield_source_used="chinabond:ycqx:10Y",
            fallback_policy="none",
            data_quality_flags=self.data_quality_flags,
        )


__all__ = [
    "ParquetDataIntegrityError",
    "ParquetFoundationError",
    "ParquetFoundationReader",
    "ParquetSchemaError",
    "SnapshotCoverageError",
]
