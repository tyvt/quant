"""Fail-closed verification for immutable, published snapshot domains."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType

from .snapshot import SNAPSHOT_SCHEMA_VERSION, _canonical_json, sha256_file


_SNAPSHOT_ID_PATTERN = re.compile(r"^snapshot-[0-9a-f]{16}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REVOCATION_SCHEMA_VERSION = 1


class SnapshotVerificationError(ValueError):
    """Raised when a published snapshot cannot be trusted for reading."""


class DomainRevokedError(SnapshotVerificationError):
    """Raised when the catalog explicitly revokes one snapshot domain."""


@dataclass(frozen=True)
class VerifiedSnapshotDomain:
    """A verified whitelist of immutable files for one snapshot domain."""

    snapshot_id: str
    domain: str
    snapshot_path: Path
    file_paths: tuple[Path, ...]
    row_count: int
    logical_hash: str
    content_hash: str
    universe_hash: str
    quality_flags: tuple[str, ...]
    snapshot_quality_flags: tuple[str, ...]
    config: Mapping[str, object]
    source_descriptors: Mapping[str, object]
    domain_details: Mapping[str, object]
    source_provenance: Mapping[str, object]


def _json_mapping(path: Path, label: str) -> Mapping[str, object]:
    if not path.is_file():
        raise SnapshotVerificationError(f"{label} is missing: {path}")
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotVerificationError(f"{label} is unreadable: {path}") from exc
    if not isinstance(payload, Mapping):
        raise SnapshotVerificationError(f"{label} must be a JSON object")
    return payload


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise SnapshotVerificationError(f"{field} must be an object with string keys")
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SnapshotVerificationError(f"{field} must be a non-empty string")
    return value


def _sha256(value: object, field: str) -> str:
    text = _nonempty_string(value, field)
    if not _SHA256_PATTERN.fullmatch(text):
        raise SnapshotVerificationError(f"{field} must be a lowercase SHA-256")
    return text


def _frozen_json(value: object, field: str) -> object:
    """Return a recursively immutable copy of JSON-compatible metadata."""
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise SnapshotVerificationError(f"{field} contains a non-string key")
        return MappingProxyType(
            {
                key: _frozen_json(item, f"{field}.{key}")
                for key, item in value.items()
            }
        )
    if isinstance(value, list):
        return tuple(
            _frozen_json(item, f"{field}[{index}]")
            for index, item in enumerate(value)
        )
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise SnapshotVerificationError(
        f"{field} contains unsupported metadata type {type(value).__name__}"
    )


def _verify_content_identity(
    meta: Mapping[str, object], snapshot_id: str
) -> tuple[
    str,
    str,
    Mapping[str, object],
    Mapping[str, object],
]:
    config_hash = _sha256(meta.get("config_hash"), "meta.config_hash")
    config = _mapping(meta.get("config"), "meta.config")
    actual_config_hash = hashlib.sha256(
        _canonical_json(config).encode("utf-8")
    ).hexdigest()
    if actual_config_hash != config_hash:
        raise SnapshotVerificationError("snapshot config hash mismatch")
    domains = _mapping(meta.get("domains"), "meta.domains")
    source_descriptors = _mapping(
        meta.get("source_descriptors"), "meta.source_descriptors"
    )
    configured_sources = _mapping(
        config.get("source_provenance_template"),
        "meta.config.source_provenance_template",
    )
    if _canonical_json(configured_sources) != _canonical_json(source_descriptors):
        raise SnapshotVerificationError(
            "snapshot source descriptors do not match config"
        )
    universe_hash = _nonempty_string(
        meta.get("universe_hash"), "meta.universe_hash"
    )
    expected_content_hash = _sha256(
        meta.get("content_hash"), "meta.content_hash"
    )
    content_payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "config_hash": config_hash,
        "domains": domains,
        "source_descriptors": source_descriptors,
        "universe_hash": universe_hash,
    }
    actual_content_hash = hashlib.sha256(
        _canonical_json(content_payload).encode("utf-8")
    ).hexdigest()
    if actual_content_hash != expected_content_hash:
        raise SnapshotVerificationError("snapshot content hash mismatch")
    if snapshot_id != f"snapshot-{actual_content_hash[:16]}":
        raise SnapshotVerificationError("snapshot ID does not match content hash")
    frozen_config = _frozen_json(config, "meta.config")
    frozen_sources = _frozen_json(
        source_descriptors, "meta.source_descriptors"
    )
    assert isinstance(frozen_config, Mapping)
    assert isinstance(frozen_sources, Mapping)
    return (
        actual_content_hash,
        universe_hash,
        frozen_config,
        frozen_sources,
    )


def _verify_required_domains(meta: Mapping[str, object]) -> None:
    required = meta.get("required_domains")
    if not isinstance(required, list) or not all(
        isinstance(item, str) and item for item in required
    ):
        raise SnapshotVerificationError(
            "meta.required_domains must be a list of non-empty strings"
        )
    domains = _mapping(meta.get("domains"), "meta.domains")
    incomplete = [
        item
        for item in required
        if not isinstance(domains.get(item), Mapping)
        or domains[item].get("status") != "complete"  # type: ignore[union-attr]
    ]
    if incomplete:
        raise SnapshotVerificationError(
            "required domains are not complete: " + ", ".join(sorted(incomplete))
        )
    config = _mapping(meta.get("config"), "meta.config")
    steps = config.get("steps")
    if not isinstance(steps, list) or not all(
        isinstance(item, str) and item for item in steps
    ):
        raise SnapshotVerificationError(
            "meta.config.steps must be a list of non-empty strings"
        )
    if sorted(set(steps)) != sorted(set(required)):
        raise SnapshotVerificationError(
            "meta.required_domains do not match config steps"
        )


def _verify_not_revoked(root: Path, snapshot_id: str, domain: str) -> None:
    catalog = _json_mapping(
        root / "catalog" / "domain-revocations.json",
        "domain revocation catalog",
    )
    if catalog.get("schema_version") != _REVOCATION_SCHEMA_VERSION:
        raise SnapshotVerificationError("unsupported domain revocation schema")
    revocations = _mapping(catalog.get("revocations"), "catalog.revocations")
    snapshot_revocations = revocations.get(snapshot_id, {})
    snapshot_map = _mapping(
        snapshot_revocations,
        f"catalog.revocations.{snapshot_id}",
    )
    record = snapshot_map.get(domain)
    if record is None:
        return
    revoked = _mapping(
        record,
        f"catalog.revocations.{snapshot_id}.{domain}",
    )
    reason = _nonempty_string(revoked.get("reason"), "revocation.reason")
    replacement = revoked.get("replacement_snapshot_id")
    replacement_note = ""
    if replacement is not None:
        if not isinstance(replacement, str) or not _SNAPSHOT_ID_PATTERN.fullmatch(
            replacement
        ):
            raise SnapshotVerificationError(
                "revocation replacement_snapshot_id is invalid"
            )
        replacement_note = f"; replacement={replacement}"
    raise DomainRevokedError(
        f"snapshot domain is revoked: {snapshot_id}/{domain}: "
        f"{reason}{replacement_note}"
    )


def _verified_file_path(snapshot_path: Path, relative: str) -> Path:
    if not relative or "\\" in relative:
        raise SnapshotVerificationError("snapshot file path must use non-empty POSIX form")
    portable = PurePosixPath(relative)
    if portable.is_absolute() or ".." in portable.parts:
        raise SnapshotVerificationError(f"snapshot file path escapes root: {relative}")
    candidate = snapshot_path.joinpath(*portable.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SnapshotVerificationError(
            f"snapshot file is missing or unreadable: {relative}"
        ) from exc
    try:
        resolved.relative_to(snapshot_path)
    except ValueError as exc:
        raise SnapshotVerificationError(
            f"snapshot file resolves outside snapshot root: {relative}"
        ) from exc
    if not resolved.is_file():
        raise SnapshotVerificationError(f"snapshot whitelist entry is not a file: {relative}")
    return resolved


def _verify_benchmark_exclusion_metadata(
    details: Mapping[str, object],
    domain_flags: list[str],
    snapshot_flags: list[str],
    source_provenance: Mapping[str, object],
) -> None:
    """Keep the v1 string marker and benchmark evidence in strict agreement."""

    marker = "benchmark_excluded_dates"
    dates = details.get(marker, [])
    evidence = details.get("exclusion_evidence", [])
    if not isinstance(dates, list) or not isinstance(evidence, list):
        raise SnapshotVerificationError("benchmark exclusion details must be lists")
    has_dates = bool(dates)
    if (marker in domain_flags) != has_dates or (marker in snapshot_flags) != has_dates:
        raise SnapshotVerificationError("benchmark exclusion marker and dates disagree")
    if not has_dates:
        if evidence:
            raise SnapshotVerificationError("benchmark exclusion evidence has no dates")
        return
    if len(evidence) != len(dates):
        raise SnapshotVerificationError("benchmark exclusion evidence count differs from dates")
    if not all(isinstance(item, str) for item in dates):
        raise SnapshotVerificationError("benchmark exclusion date must be ISO text")
    if len(set(dates)) != len(dates):
        raise SnapshotVerificationError("benchmark exclusion dates are duplicated")
    for index, (raw_day, raw_evidence) in enumerate(zip(dates, evidence)):
        if not isinstance(raw_day, str):
            raise SnapshotVerificationError("benchmark exclusion date must be ISO text")
        try:
            parsed_day = date.fromisoformat(raw_day)
        except ValueError as exc:
            raise SnapshotVerificationError("benchmark exclusion date is invalid") from exc
        if parsed_day.isoformat() != raw_day:
            raise SnapshotVerificationError("benchmark exclusion date is not canonical")
        item = _mapping(raw_evidence, f"benchmark.exclusion_evidence[{index}]")
        for field in (
            "excluded_date", "official_close", "calendar_verdict",
            "exclusion_reason", "evidence_ref", "rule_version",
        ):
            _nonempty_string(item.get(field), f"benchmark.exclusion_evidence[{index}].{field}")
        if item["excluded_date"] != raw_day:
            raise SnapshotVerificationError("benchmark exclusion evidence date differs")
    csindex = _mapping(source_provenance.get("csindex"), "meta.source_provenance.csindex")
    if csindex.get("exclusion_policy") != "explicit_whitelist_v1":
        raise SnapshotVerificationError("benchmark exclusion policy is invalid")


def verify_published_domain(
    storage_root: str | Path,
    snapshot_id: str,
    domain: str,
) -> VerifiedSnapshotDomain:
    """Verify one explicit snapshot/domain and return only its whitelisted files.

    The function deliberately does not discover a "latest" snapshot and does
    not follow revocation replacements.  Callers must record their explicit
    snapshot choices in a run manifest.
    """
    if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID_PATTERN.fullmatch(
        snapshot_id
    ):
        raise SnapshotVerificationError("snapshot_id has an invalid format")
    if not isinstance(domain, str) or not domain:
        raise SnapshotVerificationError("domain must be a non-empty string")

    root = Path(storage_root).resolve()
    snapshot_path = (root / "snapshots" / snapshot_id).resolve()
    expected_parent = (root / "snapshots").resolve()
    if snapshot_path.parent != expected_parent or not snapshot_path.is_dir():
        raise SnapshotVerificationError(
            f"published snapshot is missing: {snapshot_id}"
        )

    meta = _json_mapping(snapshot_path / "meta.json", "snapshot meta")
    if meta.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotVerificationError("unsupported snapshot schema version")
    if meta.get("status") != "complete":
        raise SnapshotVerificationError("snapshot meta is not complete")
    if meta.get("snapshot_id") != snapshot_id:
        raise SnapshotVerificationError("snapshot meta ID does not match directory")
    (
        content_hash,
        universe_hash,
        frozen_config,
        frozen_sources,
    ) = _verify_content_identity(meta, snapshot_id)
    _verify_required_domains(meta)
    _verify_not_revoked(root, snapshot_id, domain)

    domains = _mapping(meta.get("domains"), "meta.domains")
    record = domains.get(domain)
    if not isinstance(record, Mapping) or record.get("status") != "complete":
        raise SnapshotVerificationError(
            f"snapshot domain is missing or incomplete: {domain}"
        )
    row_count = record.get("row_count")
    if type(row_count) is not int or row_count < 0:
        raise SnapshotVerificationError("domain row_count must be a non-negative integer")
    file_hashes = _mapping(record.get("file_hashes"), "domain.file_hashes")
    if not file_hashes:
        raise SnapshotVerificationError("complete domain has no whitelisted files")
    normalized_hashes: dict[str, str] = {}
    verified_files: list[Path] = []
    for relative, raw_expected in sorted(file_hashes.items()):
        expected = _sha256(raw_expected, f"domain.file_hashes.{relative}")
        path = _verified_file_path(snapshot_path, relative)
        if sha256_file(path) != expected:
            raise SnapshotVerificationError(
                f"snapshot file hash mismatch: {relative}"
            )
        normalized_hashes[relative] = expected
        verified_files.append(path)

    logical_hash = _sha256(record.get("logical_hash"), "domain.logical_hash")
    actual_logical_hash = hashlib.sha256(
        _canonical_json(
            {"row_count": row_count, "file_hashes": normalized_hashes}
        ).encode("utf-8")
    ).hexdigest()
    if actual_logical_hash != logical_hash:
        raise SnapshotVerificationError("domain logical hash mismatch")
    raw_flags = record.get("quality_flags", [])
    if not isinstance(raw_flags, list) or not all(
        isinstance(item, str) for item in raw_flags
    ):
        raise SnapshotVerificationError("domain quality_flags must be a string list")
    raw_snapshot_flags = meta.get("data_quality_flags", [])
    if not isinstance(raw_snapshot_flags, list) or not all(
        isinstance(item, str) for item in raw_snapshot_flags
    ):
        raise SnapshotVerificationError(
            "snapshot data_quality_flags must be a string list"
        )
    raw_details = record.get("details", {})
    details = _mapping(raw_details, "domain.details")
    frozen_details = _frozen_json(details, "domain.details")
    assert isinstance(frozen_details, Mapping)
    raw_provenance = _mapping(
        meta.get("source_provenance", {}), "meta.source_provenance"
    )
    benchmark_record = domains.get("benchmark")
    if isinstance(benchmark_record, Mapping) and benchmark_record.get("status") == "complete":
        if domain == "benchmark":
            benchmark_details = details
            benchmark_flags = raw_flags
        else:
            benchmark_details = _mapping(
                benchmark_record.get("details", {}), "benchmark.details"
            )
            benchmark_flags = benchmark_record.get("quality_flags", [])
            if not isinstance(benchmark_flags, list) or not all(
                isinstance(item, str) for item in benchmark_flags
            ):
                raise SnapshotVerificationError("benchmark quality_flags must be a string list")
        _verify_benchmark_exclusion_metadata(
            benchmark_details, benchmark_flags, raw_snapshot_flags, raw_provenance
        )
    elif "benchmark_excluded_dates" in raw_snapshot_flags:
        raise SnapshotVerificationError(
            "benchmark exclusion marker has no complete benchmark domain"
        )
    frozen_provenance = _frozen_json(raw_provenance, "meta.source_provenance")
    assert isinstance(frozen_provenance, Mapping)

    return VerifiedSnapshotDomain(
        snapshot_id=snapshot_id,
        domain=domain,
        snapshot_path=snapshot_path,
        file_paths=tuple(verified_files),
        row_count=row_count,
        logical_hash=logical_hash,
        content_hash=content_hash,
        universe_hash=universe_hash,
        quality_flags=tuple(sorted(set(raw_flags))),
        snapshot_quality_flags=tuple(sorted(set(raw_snapshot_flags))),
        config=frozen_config,
        source_descriptors=frozen_sources,
        domain_details=frozen_details,
        source_provenance=frozen_provenance,
    )
