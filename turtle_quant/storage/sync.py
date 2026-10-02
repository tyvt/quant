"""Foundation-domain synchronization into an immutable snapshot."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import gc
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from .checkpoint import (
    checkpoint_payload,
    should_skip_completed_shard,
    write_checkpoint,
)
from .parquet import read_parquet_rows, write_parquet_rows
from .quality import validate_raw_daily_rows
from .snapshot import (
    BatchLock,
    IngestConfig,
    SnapshotSession,
    compute_batch_id,
    compute_universe_hash,
    sha256_file,
)


FOUNDATION_STEP_ORDER = (
    "security_master",
    "calendar",
    "market_daily",
    "adjustment_factors",
    "chinabond_10y",
)
_FOUNDATION_STEPS = frozenset(FOUNDATION_STEP_ORDER)
_SNAPSHOT_ID_PATTERN = re.compile(r"^snapshot-[0-9a-f]{16}$")


def validate_foundation_steps(steps: Sequence[str]) -> None:
    selected = set(steps)
    unknown = selected.difference(_FOUNDATION_STEPS)
    if unknown:
        raise ValueError(f"unknown foundation steps: {sorted(unknown)}")
    if selected.intersection({"market_daily", "adjustment_factors"}) and (
        "security_master" not in selected
    ):
        raise ValueError(
            "security_master is required for market_daily or adjustment_factors"
        )
    if "chinabond_10y" in selected and "calendar" not in selected:
        raise ValueError("calendar is required for chinabond_10y")


def _utc_now_text() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class FoundationSyncRunner:
    def __init__(
        self,
        *,
        storage_root: str | Path,
        config: IngestConfig,
        stockdb: object,
        baostock: object,
        chinabond: object,
        progress: Callable[[str], None] | None = None,
        parent_security_master_snapshot: str | None = None,
    ) -> None:
        validate_foundation_steps(config.steps)
        if (
            set(config.steps).difference({"security_master"})
            and (config.start_date is None or config.end_date is None)
        ):
            raise ValueError(
                "start_date and end_date are required for dated domains"
            )
        self.storage_root = Path(storage_root)
        self.config = config
        self.stockdb = stockdb
        self.baostock = baostock
        self.chinabond = chinabond
        self._progress = progress or (lambda _message: None)
        if (
            parent_security_master_snapshot is not None
            and not _SNAPSHOT_ID_PATTERN.fullmatch(
                parent_security_master_snapshot
            )
        ):
            raise ValueError("invalid parent security-master snapshot ID")
        self.parent_security_master_snapshot = (
            parent_security_master_snapshot
        )

    def run(
        self,
        *,
        batch_id: str | None = None,
        resume: bool = False,
    ) -> str:
        resolved_batch = batch_id or compute_batch_id(self.config)
        recovered = SnapshotSession.finish_interrupted_publish(
            self.storage_root, resolved_batch
        )
        if recovered is not None:
            self._progress(f"published {recovered}")
            return recovered
        self._progress(f"batch {resolved_batch}: starting")
        lock_path = self.storage_root / ".locks" / f"{resolved_batch}.lock"
        with BatchLock(lock_path):
            if resume:
                session = SnapshotSession.resume(
                    self.storage_root, resolved_batch, self.config
                )
            else:
                session = SnapshotSession.start(
                    self.storage_root,
                    self.config,
                    batch_id=resolved_batch,
                )
            fetched_at = _utc_now_text()
            for source in self.config.source_provenance_template:
                session.set_acquisition_provenance(
                    source, {"fetch_time_utc": fetched_at}
                )

            master_rows = self._run_security_master(session)
            self._progress(
                f"security_master: {len(master_rows)} normalized rows"
            )
            calendar_rows = self._run_calendar(session)
            if calendar_rows:
                self._progress(f"calendar: {len(calendar_rows)} rows")
            selected = self._select_market_securities(master_rows)
            self._progress(
                f"universe: {len(selected)} securities selected"
            )
            self._run_market_daily(session, selected)
            self._run_adjustment_factors(session, selected)
            self._run_chinabond(session, calendar_rows)

            universe_hash = compute_universe_hash(selected)
            snapshot_id = session.publish(
                universe_hash=universe_hash,
                source_descriptors=self.config.source_provenance_template,
            )
            self._progress(f"published {snapshot_id}")
            return snapshot_id

    def _run_security_master(
        self, session: SnapshotSession
    ) -> list[dict[str, object]]:
        path = session.staging_path / "security_master" / "part.parquet"
        if session.is_domain_complete("security_master"):
            return read_parquet_rows(path)
        if "security_master" not in self.config.steps:
            raise ValueError("foundation snapshots require security_master")
        try:
            if self.parent_security_master_snapshot is not None:
                return self._reuse_parent_security_master(session, path)
            rows = self.baostock.fetch_security_master()
            if not rows:
                raise ValueError("security_master returned no rows")
            if not any(row.get("delisting_date") for row in rows):
                raise ValueError(
                    "security_master contains no delisted security"
                )
            stockdb_codes = {
                item.security_id: item
                for item in self.stockdb.list_security_codes()
            }
            keys: set[tuple[object, object]] = set()
            normalized_rows: list[dict[str, object]] = []
            for original in rows:
                row = dict(original)
                key = (
                    row.get("security_id"),
                    row.get("board_effective_from"),
                )
                if key in keys:
                    raise ValueError(f"duplicate security master key: {key}")
                keys.add(key)
                local = stockdb_codes.get(str(row.get("security_id")))
                row["stockdb_present"] = local is not None
                row["stockdb_delisted_table"] = (
                    local.is_in_delisted_table if local is not None else False
                )
                normalized_rows.append(row)
            provider_ids = {
                str(row["security_id"]) for row in normalized_rows
            }
            missing_from_stockdb = sum(
                not bool(row["stockdb_present"]) for row in normalized_rows
            )
            missing_from_provider = len(
                set(stockdb_codes).difference(provider_ids)
            )
            quality_flags: list[str] = []
            if missing_from_stockdb:
                quality_flags.append(
                    "security_master:stockdb_missing:warning:"
                    f"{missing_from_stockdb}"
                )
            if missing_from_provider:
                quality_flags.append(
                    "security_master:baostock_missing:warning:"
                    f"{missing_from_provider}"
                )
            write_parquet_rows(
                path,
                normalized_rows,
                sort_keys=("security_id", "board_effective_from"),
            )
            session.complete_domain(
                "security_master",
                files=(path,),
                row_count=len(normalized_rows),
                quality_flags=tuple(quality_flags),
            )
            return normalized_rows
        except Exception as exc:
            session.fail_domain("security_master", str(exc))
            raise

    def _reuse_parent_security_master(
        self,
        session: SnapshotSession,
        destination: Path,
    ) -> list[dict[str, object]]:
        assert self.parent_security_master_snapshot is not None
        parent_root = (
            self.storage_root
            / "snapshots"
            / self.parent_security_master_snapshot
        )
        meta_path = parent_root / "meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(
                "parent security-master snapshot is not published"
            )
        meta = json.loads(meta_path.read_text("utf-8"))
        if (
            meta.get("status") != "complete"
            or meta.get("snapshot_id")
            != self.parent_security_master_snapshot
        ):
            raise ValueError("parent snapshot is not complete")
        descriptor = self.config.source_provenance_template.get(
            "parent_security_master"
        )
        if not isinstance(descriptor, Mapping) or descriptor.get(
            "snapshot_id"
        ) != self.parent_security_master_snapshot:
            raise ValueError(
                "config source descriptor must pin parent snapshot ID"
            )
        domain = meta.get("domains", {}).get("security_master", {})
        if domain.get("status") != "complete":
            raise ValueError("parent security_master domain is not complete")
        file_hashes = domain.get("file_hashes", {})
        if not isinstance(file_hashes, Mapping) or len(file_hashes) != 1:
            raise ValueError(
                "parent security_master must contain exactly one file"
            )
        relative, expected_hash = next(iter(file_hashes.items()))
        source = (parent_root / str(relative)).resolve()
        try:
            source.relative_to(parent_root.resolve())
        except ValueError as exc:
            raise ValueError("parent snapshot contains an unsafe file path") from exc
        if not source.is_file() or sha256_file(source) != expected_hash:
            raise ValueError("parent security_master file hash mismatch")
        rows = read_parquet_rows(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{os.getpid()}.tmp"
        )
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
        session.complete_domain(
            "security_master",
            files=(destination,),
            row_count=len(rows),
            quality_flags=(
                "security_master:reused_parent:information:"
                f"{self.parent_security_master_snapshot}",
            ),
            details={
                "parent_snapshot_id": self.parent_security_master_snapshot,
                "parent_content_hash": meta.get("content_hash"),
            },
        )
        return rows

    def _run_calendar(
        self, session: SnapshotSession
    ) -> list[dict[str, object]]:
        if "calendar" not in self.config.steps:
            return []
        path = session.staging_path / "calendar" / "trade_dates.parquet"
        if session.is_domain_complete("calendar"):
            return read_parquet_rows(path)
        if self.config.start_date is None or self.config.end_date is None:
            raise ValueError("start_date and end_date are required")
        try:
            rows = self.baostock.fetch_calendar(
                self.config.start_date,
                self.config.end_date + timedelta(days=10),
            )
            if not rows:
                raise ValueError("calendar returned no rows")
            dates = [str(row.get("date")) for row in rows]
            if len(set(dates)) != len(dates):
                raise ValueError("calendar contains duplicate dates")
            write_parquet_rows(path, rows, sort_keys=("date",))
            session.complete_domain(
                "calendar", files=(path,), row_count=len(rows)
            )
            return rows
        except Exception as exc:
            session.fail_domain("calendar", str(exc))
            raise

    def _select_market_securities(
        self, master_rows: Sequence[Mapping[str, object]]
    ) -> list[dict[str, object]]:
        end_date = self.config.end_date or self.config.ingest_calendar_date
        start_date = self.config.start_date or end_date
        selected_by_id: dict[str, dict[str, object]] = {}
        for source in master_rows:
            if source.get("board") != "main_board":
                continue
            listing = date.fromisoformat(str(source["listing_date"]))
            raw_delisting = source.get("delisting_date")
            delisting = (
                date.fromisoformat(str(raw_delisting))
                if raw_delisting
                else None
            )
            effective_from = date.fromisoformat(
                str(source["board_effective_from"])
            )
            raw_effective_to = source.get("board_effective_to")
            effective_to = (
                date.fromisoformat(str(raw_effective_to))
                if raw_effective_to
                else None
            )
            if listing > end_date:
                continue
            if delisting is not None and delisting < start_date:
                continue
            if effective_from > end_date:
                continue
            if effective_to is not None and effective_to < start_date:
                continue
            row = dict(source)
            row["symbol"] = row["security_id"]
            selected_by_id[str(row["security_id"])] = row
        selected = [
            selected_by_id[key] for key in sorted(selected_by_id)
        ]
        if self.config.max_symbols is not None:
            selected = selected[: self.config.max_symbols]
        return selected

    def _run_market_daily(
        self,
        session: SnapshotSession,
        selected: Sequence[Mapping[str, object]],
    ) -> None:
        if "market_daily" not in self.config.steps:
            return
        if session.is_domain_complete("market_daily"):
            return
        if not selected:
            raise ValueError("market_daily has no selected securities")
        if self.config.start_date is None or self.config.end_date is None:
            raise ValueError("start_date and end_date are required")
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in selected:
            security_id = str(row["security_id"])
            # Five digits keeps a full-history shard small enough to avoid
            # holding hundreds of thousands of Python dictionaries at once.
            prefix = security_id.split(".", 1)[1][:5]
            grouped[prefix].append(security_id)
        files: list[Path] = []
        total_rows = 0
        quality_flags: list[str] = []
        observed_securities: set[str] = set()
        checkpoint_paths: list[Path] = []
        try:
            for prefix in sorted(grouped):
                self._progress(
                    f"market_daily shard {prefix}: "
                    f"{len(grouped[prefix])} securities"
                )
                domain_path = session.staging_path / "market" / "raw_daily"
                parquet = domain_path / f"part-{prefix}.parquet"
                checkpoint = domain_path / f"part-{prefix}.checkpoint.json"
                checkpoint_paths.append(checkpoint)
                if should_skip_completed_shard(checkpoint, parquet):
                    existing = read_parquet_rows(parquet)
                    files.append(parquet)
                    total_rows += len(existing)
                    observed_securities.update(
                        str(row["security_id"]) for row in existing
                    )
                    continue
                write_checkpoint(
                    checkpoint,
                    checkpoint_payload(
                        domain="market_daily",
                        batch_id=session.batch_id,
                        prefix=prefix,
                        status="in_progress",
                        parquet_sha256=None,
                    ),
                )
                rows: list[dict[str, object]] = []
                for security_id in sorted(grouped[prefix]):
                    rows.extend(
                        self.stockdb.fetch_raw_daily(
                            security_id,
                            start_date=self.config.start_date,
                            end_date=self.config.end_date,
                        )
                    )
                quality = validate_raw_daily_rows(rows)
                quality_flags.extend(quality.warning_issues)
                observed_securities.update(
                    str(row["security_id"]) for row in rows
                )
                write_parquet_rows(
                    parquet,
                    rows,
                    sort_keys=("security_id", "trade_date"),
                )
                write_checkpoint(
                    checkpoint,
                    checkpoint_payload(
                        domain="market_daily",
                        batch_id=session.batch_id,
                        prefix=prefix,
                        status="complete",
                        parquet_sha256=sha256_file(parquet),
                        completed_symbols=tuple(sorted(grouped[prefix])),
                    ),
                )
                files.append(parquet)
                total_rows += len(rows)
                del rows
                del quality
                gc.collect()
            coverage = (
                Decimal(len(observed_securities)) / Decimal(len(selected))
                if selected
                else Decimal("0")
            )
            if coverage < self.config.minimum_market_coverage:
                raise ValueError(
                    "market_daily security coverage "
                    f"{coverage:.4f} is below configured threshold "
                    f"{self.config.minimum_market_coverage}"
                )
            if coverage < Decimal("1"):
                quality_flags.append(
                    "market_daily:security_coverage:warning:"
                    f"{len(observed_securities)}/{len(selected)}"
                )
            missing_security_ids = sorted(
                {
                    str(row["security_id"]) for row in selected
                }.difference(observed_securities)
            )
            session.complete_domain(
                "market_daily",
                files=tuple(files),
                row_count=total_rows,
                quality_flags=tuple(quality_flags),
                details={
                    "security_coverage": str(coverage),
                    "missing_security_ids": missing_security_ids,
                },
            )
            self._progress(
                f"market_daily: {total_rows} rows, coverage={coverage}"
            )
            for checkpoint in checkpoint_paths:
                checkpoint.unlink(missing_ok=True)
        except Exception as exc:
            session.fail_domain("market_daily", str(exc))
            raise

    def _run_adjustment_factors(
        self,
        session: SnapshotSession,
        selected: Sequence[Mapping[str, object]],
    ) -> None:
        if "adjustment_factors" not in self.config.steps:
            return
        if session.is_domain_complete("adjustment_factors"):
            return
        path = (
            session.staging_path
            / "corporate_actions"
            / "adjustment_factors"
            / "part.parquet"
        )
        try:
            security_ids = {
                str(row["security_id"]) for row in selected
            }
            rows = self.stockdb.fetch_adjustment_factors(security_ids)
            for row in rows:
                factor = row.get("factor")
                if factor is None or factor <= 0:
                    raise ValueError("adjustment factor must be positive")
            write_parquet_rows(
                path,
                rows,
                sort_keys=("security_id", "ex_date"),
            )
            session.complete_domain(
                "adjustment_factors",
                files=(path,),
                row_count=len(rows),
            )
            self._progress(f"adjustment_factors: {len(rows)} rows")
        except Exception as exc:
            session.fail_domain("adjustment_factors", str(exc))
            raise

    def _run_chinabond(
        self,
        session: SnapshotSession,
        calendar_rows: Sequence[Mapping[str, object]],
    ) -> None:
        if "chinabond_10y" not in self.config.steps:
            return
        if session.is_domain_complete("chinabond_10y"):
            return
        if self.config.start_date is None or self.config.end_date is None:
            raise ValueError("start_date and end_date are required")
        trading_dates = sorted(
            date.fromisoformat(str(row["date"]))
            for row in calendar_rows
            if row.get("is_trading_day") is True
        )

        def next_trading_day(obs_date: date) -> date:
            for trading_date in trading_dates:
                if trading_date > obs_date:
                    return trading_date
            raise ValueError(
                f"calendar cannot resolve conservative availability after {obs_date}"
            )

        path = (
            session.staging_path
            / "macro"
            / "cn_yield_10y"
            / "daily.parquet"
        )
        try:
            rows = self.chinabond.fetch_10y(
                self.config.start_date,
                self.config.end_date,
                available_at_resolver=next_trading_day,
            )
            if not rows:
                raise ValueError("ChinaBond 10Y returned no rows")
            gaps = tuple(getattr(self.chinabond, "last_gaps", ()))
            quality_flags = tuple(
                f"chinabond_10y:source_gap:warning:{year}"
                for year in gaps
            )
            write_parquet_rows(path, rows, sort_keys=("obs_date",))
            session.complete_domain(
                "chinabond_10y",
                files=(path,),
                row_count=len(rows),
                quality_flags=quality_flags,
                details={"gap_years": list(gaps)},
            )
            self._progress(f"chinabond_10y: {len(rows)} rows")
        except Exception as exc:
            session.fail_domain("chinabond_10y", str(exc))
            raise
