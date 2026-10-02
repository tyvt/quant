"""Immutable metadata required to reproduce a calculation run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from types import MappingProxyType
import unicodedata


@dataclass(frozen=True)
class RunManifest:
    manifest_version: str
    run_id: str
    as_of: date
    code_version: str
    rules_version: str
    config_hash: str
    universe_hash: str
    snapshot_ids: tuple[str, ...]
    source_versions: Mapping[str, str]
    treasury_yield_source_used: str
    fallback_policy: str
    data_quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        string_fields = (
            "manifest_version",
            "run_id",
            "code_version",
            "rules_version",
            "config_hash",
            "universe_hash",
            "treasury_yield_source_used",
            "fallback_policy",
        )
        for field_name in string_fields:
            object.__setattr__(
                self,
                field_name,
                _normalized_nonempty_string(
                    getattr(self, field_name), field_name
                ),
            )
        if type(self.as_of) is not date:
            raise ValueError("as_of must be a date without a time component")

        object.__setattr__(
            self,
            "snapshot_ids",
            _normalized_string_set(
                self.snapshot_ids,
                "snapshot_ids",
                reject_duplicates=True,
            ),
        )
        object.__setattr__(
            self,
            "data_quality_flags",
            _normalized_string_set(
                self.data_quality_flags,
                "data_quality_flags",
                reject_duplicates=False,
            ),
        )
        object.__setattr__(
            self,
            "source_versions",
            MappingProxyType(_normalized_source_versions(self.source_versions)),
        )

    # Required because source_versions is stored as an unhashable
    # MappingProxyType; do not remove this override from the frozen dataclass.
    def __hash__(self) -> int:
        """Keep Python equality/hash aligned with canonical manifest identity."""
        return hash(self.canonical_json())

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_version": self.manifest_version,
            "run_id": self.run_id,
            "as_of": self.as_of.isoformat(),
            "code_version": self.code_version,
            "rules_version": self.rules_version,
            "config_hash": self.config_hash,
            "universe_hash": self.universe_hash,
            "snapshot_ids": sorted(self.snapshot_ids),
            "source_versions": dict(self.source_versions),
            "treasury_yield_source_used": self.treasury_yield_source_used,
            "fallback_policy": self.fallback_policy,
            "data_quality_flags": sorted(self.data_quality_flags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RunManifest":
        """Restore a manifest while validating its serialized shape."""
        required = {
            "manifest_version",
            "run_id",
            "as_of",
            "code_version",
            "rules_version",
            "config_hash",
            "universe_hash",
            "snapshot_ids",
            "source_versions",
            "treasury_yield_source_used",
            "fallback_policy",
            "data_quality_flags",
        }
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"manifest payload missing fields: {sorted(missing)}")

        snapshot_ids = _string_tuple(payload["snapshot_ids"], "snapshot_ids")
        data_quality_flags = _string_tuple(
            payload["data_quality_flags"], "data_quality_flags"
        )
        source_versions_raw = payload["source_versions"]
        if not isinstance(source_versions_raw, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in source_versions_raw.items()
        ):
            raise ValueError("source_versions must map strings to strings")

        as_of_raw = payload["as_of"]
        if not isinstance(as_of_raw, str):
            raise ValueError("as_of must be an ISO date string")
        string_fields = (
            "manifest_version",
            "run_id",
            "code_version",
            "rules_version",
            "config_hash",
            "universe_hash",
            "treasury_yield_source_used",
            "fallback_policy",
        )
        if any(not isinstance(payload[field], str) for field in string_fields):
            raise ValueError("manifest identity fields must be strings")

        return cls(
            manifest_version=payload["manifest_version"],
            run_id=payload["run_id"],
            as_of=date.fromisoformat(as_of_raw),
            code_version=payload["code_version"],
            rules_version=payload["rules_version"],
            config_hash=payload["config_hash"],
            universe_hash=payload["universe_hash"],
            snapshot_ids=snapshot_ids,
            source_versions=source_versions_raw,
            treasury_yield_source_used=payload["treasury_yield_source_used"],
            fallback_policy=payload["fallback_policy"],
            data_quality_flags=data_quality_flags,
        )

    def canonical_json(self) -> str:
        """Return deterministic JSON suitable for a content address."""
        raw_json = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return unicodedata.normalize("NFC", raw_json)

    def content_hash(self) -> str:
        """Return the SHA-256 hash of the canonical manifest representation."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError(f"{field_name} must be a list or tuple of strings")
    return tuple(value)


def _normalized_nonempty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _normalized_string_set(
    value: object,
    field_name: str,
    *,
    reject_duplicates: bool,
) -> tuple[str, ...]:
    """Normalize an unordered string-set field into a sorted tuple."""
    raw_values = _string_tuple(value, field_name)
    normalized_values = tuple(
        _normalized_nonempty_string(item, field_name) for item in raw_values
    )
    normalized_set = set(normalized_values)
    if reject_duplicates and len(normalized_set) != len(normalized_values):
        raise ValueError(f"{field_name} must not contain duplicate identifiers")
    return tuple(sorted(normalized_set))


def _normalized_source_versions(
    value: Mapping[str, str],
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("source_versions must map strings to strings")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized_key = _normalized_nonempty_string(key, "source_versions key")
        normalized_value = _normalized_nonempty_string(
            item, "source_versions value"
        )
        existing = normalized.get(normalized_key)
        if existing is not None and existing != normalized_value:
            raise ValueError(
                "source_versions contains conflicting normalized keys"
            )
        normalized[normalized_key] = normalized_value
    return normalized
