"""Content-addressed, immutable raw-data snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from types import MappingProxyType
from typing import Any
import unicodedata


SNAPSHOT_SCHEMA_VERSION = 1
_VOLATILE_IDENTITY_KEYS = frozenset(
    {
        "fetch_time_utc",
        "fetched_at",
        "acquired_at",
        "output_path",
        "storage_root",
        "log_level",
    }
)
_BATCH_ID_PATTERN = re.compile(r"^local-\d{8}-[0-9a-f]{16}$")


def _json_default(value: object) -> str:
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"cannot serialize {type(value).__name__} canonically")


def _canonical_json(obj: object) -> str:
    """Serialize one value deterministically for hashes and identities."""
    raw = json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )
    return unicodedata.normalize("NFC", raw)


def _stable_descriptor(value: object) -> object:
    """Remove acquisition-only fields from a nested source descriptor."""
    if isinstance(value, Mapping):
        return {
            unicodedata.normalize("NFC", str(key)): _stable_descriptor(item)
            for key, item in value.items()
            if str(key) not in _VOLATILE_IDENTITY_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_stable_descriptor(item) for item in value]
    return value


def normalize_fetch_time_utc(value: datetime | str) -> str:
    """Return strict UTC ISO-8601 text ending in ``Z``."""
    if isinstance(value, str):
        candidate = value
        if candidate.endswith("Z"):
            parsed = datetime.fromisoformat(candidate[:-1] + "+00:00")
        else:
            parsed = datetime.fromisoformat(candidate)
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("fetch_time_utc must be a datetime or ISO string")
    if parsed.tzinfo is None:
        raise ValueError("fetch_time_utc must include a timezone")
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class IngestConfig:
    """Inputs that define one deterministic ingestion task."""

    ingest_calendar_date: date
    steps: tuple[str, ...]
    start_date: date | None
    end_date: date | None
    max_symbols: int | None
    board_filter_version: str
    source_provenance_template: Mapping[str, object]
    minimum_market_coverage: Decimal = Decimal("0.98")

    def __post_init__(self) -> None:
        if type(self.ingest_calendar_date) is not date:
            raise ValueError("ingest_calendar_date must be a date")
        normalized_steps = tuple(
            unicodedata.normalize("NFC", step.strip()) for step in self.steps
        )
        if not normalized_steps or any(not step for step in normalized_steps):
            raise ValueError("steps must contain non-empty names")
        if len(set(normalized_steps)) != len(normalized_steps):
            raise ValueError("steps must not contain duplicates")
        if self.start_date is not None and type(self.start_date) is not date:
            raise ValueError("start_date must be a date or None")
        if self.end_date is not None and type(self.end_date) is not date:
            raise ValueError("end_date must be a date or None")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date cannot precede start_date")
        if (
            self.max_symbols is not None
            and (
                isinstance(self.max_symbols, bool)
                or not isinstance(self.max_symbols, int)
                or self.max_symbols < 0
            )
        ):
            raise ValueError("max_symbols must be a non-negative integer or None")
        board_version = unicodedata.normalize(
            "NFC", self.board_filter_version.strip()
        )
        if not board_version:
            raise ValueError("board_filter_version must be non-empty")
        if not isinstance(self.source_provenance_template, Mapping):
            raise ValueError("source_provenance_template must be a mapping")
        if (
            not isinstance(self.minimum_market_coverage, Decimal)
            or not self.minimum_market_coverage.is_finite()
            or not Decimal("0") <= self.minimum_market_coverage <= Decimal("1")
        ):
            raise ValueError(
                "minimum_market_coverage must be a finite Decimal in [0, 1]"
            )
        object.__setattr__(self, "steps", normalized_steps)
        object.__setattr__(self, "board_filter_version", board_version)
        object.__setattr__(
            self,
            "source_provenance_template",
            MappingProxyType(dict(self.source_provenance_template)),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "ingest_calendar_date": self.ingest_calendar_date.isoformat(),
            "steps": sorted(self.steps),
            "start_date": (
                self.start_date.isoformat() if self.start_date is not None else None
            ),
            "end_date": (
                self.end_date.isoformat() if self.end_date is not None else None
            ),
            "max_symbols": self.max_symbols,
            "board_filter_version": self.board_filter_version,
            "minimum_market_coverage": str(self.minimum_market_coverage),
            "source_provenance_template": _stable_descriptor(
                self.source_provenance_template
            ),
        }


def compute_config_hash(config: IngestConfig) -> str:
    return hashlib.sha256(
        _canonical_json(config.identity_payload()).encode("utf-8")
    ).hexdigest()


def compute_batch_id(config: IngestConfig) -> str:
    digest = compute_config_hash(config)[:16]
    day = config.ingest_calendar_date.strftime("%Y%m%d")
    return f"local-{day}-{digest}"


def _validated_batch_id(value: str) -> str:
    if not isinstance(value, str) or not _BATCH_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "batch_id must match local-YYYYMMDD-<16 lowercase hex digits>"
        )
    return value


def _normal_date(value: object, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO date or null") from exc
    raise ValueError(f"{field_name} must be an ISO date or null")


def _universe_rows(
    rows_or_parquet: Iterable[Mapping[str, object]] | str | Path,
) -> list[Mapping[str, object]]:
    if isinstance(rows_or_parquet, (str, Path)):
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - optional sync dependency
            raise RuntimeError("pyarrow is required to hash a parquet universe") from exc
        table = pq.read_table(rows_or_parquet)
        return table.to_pylist()
    return list(rows_or_parquet)


def compute_universe_hash(
    rows_or_parquet: Iterable[Mapping[str, object]] | str | Path,
) -> str:
    """Hash the economic identity of one security universe."""
    canonical_rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in _universe_rows(rows_or_parquet):
        raw_symbol = row.get("symbol", row.get("security_id"))
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise ValueError("universe row requires symbol or security_id")
        symbol = unicodedata.normalize("NFC", raw_symbol.strip().lower())
        if symbol in seen:
            raise ValueError(f"duplicate universe symbol: {symbol}")
        seen.add(symbol)
        canonical_rows.append(
            {
                "symbol": symbol,
                "listing_date": _normal_date(
                    row.get("listing_date"), "listing_date"
                ),
                "delisting_date": _normal_date(
                    row.get("delisting_date"), "delisting_date"
                ),
            }
        )
    canonical_rows.sort(key=lambda row: str(row["symbol"]))
    digest = hashlib.sha256(
        _canonical_json({"universe": canonical_rows}).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(_canonical_json(payload), encoding="utf-8")
    os.replace(temporary, path)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class BatchLock:
    """An exclusive process lock for one batch ID."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    def _reclaim_if_stale(self) -> None:
        try:
            owner = int(self.path.read_text("ascii").strip())
        except (OSError, ValueError):
            return
        if not _pid_is_running(owner):
            self.path.unlink(missing_ok=True)

    def __enter__(self) -> "BatchLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                self._fd = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                break
            except FileExistsError:
                self._reclaim_if_stale()
                if self.path.exists():
                    raise
        else:
            raise FileExistsError(self.path)
        os.write(self._fd, f"{os.getpid()}\n".encode("ascii"))
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.path.unlink(missing_ok=True)


class SnapshotSession:
    """Mutable staging session which can publish one immutable snapshot."""

    def __init__(
        self,
        root: Path,
        config: IngestConfig,
        batch_id: str,
        meta: dict[str, Any],
    ) -> None:
        self.root = root
        self.config = config
        self.batch_id = batch_id
        self.staging_path = root / ".staging" / batch_id
        self.partial_meta_path = self.staging_path / "meta.partial.json"
        self._meta = meta

    @classmethod
    def start(
        cls,
        root: str | Path,
        config: IngestConfig,
        *,
        batch_id: str | None = None,
    ) -> "SnapshotSession":
        root_path = Path(root)
        resolved_batch = _validated_batch_id(
            batch_id or compute_batch_id(config)
        )
        staging = root_path / ".staging" / resolved_batch
        if staging.exists():
            raise FileExistsError(f"batch staging already exists: {resolved_batch}")
        for meta_path in (root_path / "snapshots").glob("*/meta.json"):
            try:
                published = json.loads(meta_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if published.get("batch_id") == resolved_batch:
                raise FileExistsError(
                    f"batch was already published: {resolved_batch}"
                )
        staging.mkdir(parents=True)
        meta: dict[str, Any] = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "status": "in_progress",
            "batch_id": resolved_batch,
            "config_hash": compute_config_hash(config),
            "config": config.identity_payload(),
            "required_domains": sorted(config.steps),
            "domains": {},
            "source_descriptors": _stable_descriptor(
                config.source_provenance_template
            ),
            "acquisition_provenance": {},
            "data_quality_flags": [],
        }
        session = cls(root_path, config, resolved_batch, meta)
        session._write_partial()
        return session

    @classmethod
    def resume(
        cls,
        root: str | Path,
        batch_id: str,
        config: IngestConfig,
    ) -> "SnapshotSession":
        root_path = Path(root)
        batch_id = _validated_batch_id(batch_id)
        staging = root_path / ".staging" / batch_id
        partial = staging / "meta.partial.json"
        if not partial.is_file():
            raise FileNotFoundError(f"partial batch does not exist: {batch_id}")
        meta = json.loads(partial.read_text("utf-8"))
        if meta.get("status") != "in_progress":
            raise ValueError("only an in-progress batch can be resumed")
        if meta.get("config_hash") != compute_config_hash(config):
            raise ValueError("resume config does not match partial batch config")
        if meta.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("resume schema version does not match")
        return cls(root_path, config, batch_id, meta)

    def _write_partial(self) -> None:
        _atomic_write_json(self.partial_meta_path, self._meta)

    def is_domain_complete(self, domain: str) -> bool:
        return (
            self._meta.get("domains", {})
            .get(domain, {})
            .get("status")
            == "complete"
        )

    def domain_record(self, domain: str) -> Mapping[str, object] | None:
        record = self._meta.get("domains", {}).get(domain)
        return MappingProxyType(dict(record)) if record is not None else None

    def set_acquisition_provenance(
        self, source: str, provenance: Mapping[str, object]
    ) -> None:
        acquisition = self._meta.setdefault("acquisition_provenance", {})
        acquisition[source] = dict(provenance)
        self._write_partial()

    def set_source_provenance(
        self, source: str, provenance: Mapping[str, object]
    ) -> None:
        """Store per-snapshot audit facts outside v1 content identity."""
        if not isinstance(source, str) or not source:
            raise ValueError("source provenance key must be non-empty")
        if not isinstance(provenance, Mapping):
            raise ValueError("source provenance must be a mapping")
        values = dict(provenance)
        if "fetch_time_utc" in values:
            values["fetch_time_utc"] = normalize_fetch_time_utc(
                values["fetch_time_utc"]  # type: ignore[arg-type]
            )
        audit = self._meta.setdefault("source_provenance", {})
        audit[source] = values
        self._write_partial()

    def complete_domain(
        self,
        domain: str,
        *,
        files: Sequence[str | Path],
        row_count: int,
        quality_flags: Sequence[str] = (),
        details: Mapping[str, object] | None = None,
    ) -> None:
        if row_count < 0:
            raise ValueError("row_count must be non-negative")
        hashes: dict[str, str] = {}
        for item in files:
            path = Path(item)
            try:
                relative = path.resolve().relative_to(self.staging_path.resolve())
            except ValueError as exc:
                raise ValueError("domain files must be inside staging") from exc
            if not path.is_file():
                raise FileNotFoundError(path)
            hashes[relative.as_posix()] = sha256_file(path)
        if not hashes:
            raise ValueError("a complete domain must contain at least one file")
        domains = self._meta.setdefault("domains", {})
        domain_record: dict[str, object] = {
            "status": "complete",
            "row_count": row_count,
            "file_hashes": dict(sorted(hashes.items())),
            "logical_hash": hashlib.sha256(
                _canonical_json(
                    {"row_count": row_count, "file_hashes": hashes}
                ).encode("utf-8")
            ).hexdigest(),
            "quality_flags": sorted(set(quality_flags)),
        }
        if details:
            domain_record["details"] = dict(details)
        domains[domain] = domain_record
        all_flags = set(self._meta.get("data_quality_flags", []))
        all_flags.update(quality_flags)
        self._meta["data_quality_flags"] = sorted(all_flags)
        self._write_partial()

    def fail_domain(self, domain: str, error: str) -> None:
        domains = self._meta.setdefault("domains", {})
        domains[domain] = {"status": "failed", "error": str(error)}
        self._write_partial()

    def _verify_files(self) -> None:
        for domain in self._meta.get("domains", {}).values():
            if domain.get("status") != "complete":
                continue
            for relative, expected in domain.get("file_hashes", {}).items():
                path = self.staging_path / relative
                if not path.is_file() or sha256_file(path) != expected:
                    raise ValueError(f"staging file hash mismatch: {relative}")

    def publish(
        self,
        *,
        universe_hash: str,
        source_descriptors: Mapping[str, object],
    ) -> str:
        domains = self._meta.get("domains", {})
        missing = [
            domain
            for domain in self._meta["required_domains"]
            if domains.get(domain, {}).get("status") != "complete"
        ]
        if missing:
            raise ValueError(
                "required domains are not complete: " + ", ".join(missing)
            )
        stable_sources = _stable_descriptor(source_descriptors)
        if _canonical_json(stable_sources) != _canonical_json(
            self._meta["source_descriptors"]
        ):
            raise ValueError("source descriptors do not match batch config")
        self._verify_files()
        content_payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "config_hash": self._meta["config_hash"],
            "domains": domains,
            "source_descriptors": stable_sources,
            "universe_hash": universe_hash,
        }
        full_hash = hashlib.sha256(
            _canonical_json(content_payload).encode("utf-8")
        ).hexdigest()
        snapshot_id = f"snapshot-{full_hash[:16]}"
        destination = self.root / "snapshots" / snapshot_id
        if destination.exists():
            try:
                existing = json.loads(
                    (destination / "meta.json").read_text("utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise FileExistsError(
                    f"snapshot destination exists but is unreadable: {snapshot_id}"
                ) from exc
            if existing.get("content_hash") != full_hash:
                raise ValueError("short snapshot ID collision detected")
            raise FileExistsError(f"snapshot already exists: {snapshot_id}")

        complete = dict(self._meta)
        complete.update(
            {
                "status": "complete",
                "snapshot_id": snapshot_id,
                "content_hash": full_hash,
                "universe_hash": universe_hash,
                "source_descriptors": stable_sources,
            }
        )
        _atomic_write_json(self.staging_path / "meta.json", complete)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.staging_path, destination)
        partial = destination / "meta.partial.json"
        partial.unlink(missing_ok=True)
        return snapshot_id

    @classmethod
    def finish_interrupted_publish(
        cls, root: str | Path, batch_id: str
    ) -> str | None:
        """Move a fully written staging tree after a failed directory rename."""
        root_path = Path(root)
        batch_id = _validated_batch_id(batch_id)
        staging = root_path / ".staging" / batch_id
        meta_path = staging / "meta.json"
        if not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text("utf-8"))
        if meta.get("status") != "complete":
            return None
        snapshot_id = meta.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id.startswith(
            "snapshot-"
        ):
            raise ValueError("interrupted publish meta has no snapshot_id")
        destination = root_path / "snapshots" / snapshot_id
        if destination.exists():
            existing = json.loads((destination / "meta.json").read_text("utf-8"))
            if existing.get("content_hash") != meta.get("content_hash"):
                raise ValueError("interrupted publish conflicts with snapshot")
            shutil.rmtree(staging)
            return snapshot_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
        (destination / "meta.partial.json").unlink(missing_ok=True)
        return snapshot_id

    def abort(self) -> None:
        """Remove an unpublished staging tree explicitly."""
        if self.staging_path.exists():
            shutil.rmtree(self.staging_path)


def provenance_to_manifest_source_versions(
    provenance: Mapping[str, object],
) -> dict[str, str]:
    """Map structured, stable provenance onto RunManifest's string values."""
    return {
        unicodedata.normalize("NFC", str(source)): _canonical_json(
            _stable_descriptor(value)
        )
        for source, value in sorted(provenance.items(), key=lambda item: item[0])
    }
