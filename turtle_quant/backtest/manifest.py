"""Canonical strategy-run manifest without changing the legacy RunManifest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from types import MappingProxyType
import unicodedata

from turtle_quant.core.types import to_decimal


_HASH = re.compile(r"^[0-9a-f]{64}$")
_STRATEGY_ID = "GENERAL_FCF_MONTHLY_TOP20_V1"
_EXECUTION_ID = "CN_A_OPEN_STRICT_V1"


@dataclass(frozen=True)
class StrategyRunManifest:
    manifest_version: str
    run_id: str
    base_run_manifest_hash: str
    strategy_id: str
    execution_policy_id: str
    initial_capital: Decimal
    signal_start: date
    signal_end: date
    snapshot_ids: tuple[str, ...]
    benchmark_id: str
    benchmark_snapshot_id: str
    fee_schedule_id: str
    config_hash: str
    code_version: str
    rules_version: str
    completeness_summary: Mapping[str, object]
    order_content_hash: str
    holding_content_hash: str
    nav_content_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "manifest_version",
            "run_id",
            "benchmark_snapshot_id",
            "fee_schedule_id",
            "code_version",
            "rules_version",
        ):
            object.__setattr__(
                self, field_name, _nonempty(getattr(self, field_name), field_name)
            )
        if self.strategy_id != _STRATEGY_ID:
            raise ValueError(f"strategy_id must be {_STRATEGY_ID}")
        if self.execution_policy_id != _EXECUTION_ID:
            raise ValueError(f"execution_policy_id must be {_EXECUTION_ID}")
        if self.benchmark_id != "H00985":
            raise ValueError("benchmark_id must be H00985")
        if self.rules_version != "v1.3.0":
            raise ValueError("rules_version must be v1.3.0")
        capital = to_decimal(self.initial_capital)
        if capital <= 0:
            raise ValueError("initial_capital must be positive")
        object.__setattr__(self, "initial_capital", capital)
        if type(self.signal_start) is not date or type(self.signal_end) is not date:
            raise ValueError("signal dates must be dates")
        if self.signal_end < self.signal_start:
            raise ValueError("signal_end cannot precede signal_start")
        snapshots = tuple(_nonempty(item, "snapshot_id") for item in self.snapshot_ids)
        normalized_snapshots = tuple(sorted(set(snapshots)))
        if len(normalized_snapshots) != len(snapshots):
            raise ValueError("snapshot_ids must not contain duplicates")
        object.__setattr__(self, "snapshot_ids", normalized_snapshots)
        for field_name in (
            "base_run_manifest_hash",
            "config_hash",
            "order_content_hash",
            "holding_content_hash",
            "nav_content_hash",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _HASH.fullmatch(value):
                raise ValueError(f"{field_name} must be a lowercase SHA-256")
        summary = _normalize_summary(self.completeness_summary)
        object.__setattr__(self, "completeness_summary", MappingProxyType(summary))

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_version": self.manifest_version,
            "run_id": self.run_id,
            "base_run_manifest_hash": self.base_run_manifest_hash,
            "strategy_id": self.strategy_id,
            "execution_policy_id": self.execution_policy_id,
            "initial_capital": _decimal_text(self.initial_capital),
            "signal_start": self.signal_start.isoformat(),
            "signal_end": self.signal_end.isoformat(),
            "snapshot_ids": list(self.snapshot_ids),
            "benchmark_id": self.benchmark_id,
            "benchmark_snapshot_id": self.benchmark_snapshot_id,
            "fee_schedule_id": self.fee_schedule_id,
            "config_hash": self.config_hash,
            "code_version": self.code_version,
            "rules_version": self.rules_version,
            "completeness_summary": dict(self.completeness_summary),
            "order_content_hash": self.order_content_hash,
            "holding_content_hash": self.holding_content_hash,
            "nav_content_hash": self.nav_content_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "StrategyRunManifest":
        required = {
            "manifest_version",
            "run_id",
            "base_run_manifest_hash",
            "strategy_id",
            "execution_policy_id",
            "initial_capital",
            "signal_start",
            "signal_end",
            "snapshot_ids",
            "benchmark_id",
            "benchmark_snapshot_id",
            "fee_schedule_id",
            "config_hash",
            "code_version",
            "rules_version",
            "completeness_summary",
            "order_content_hash",
            "holding_content_hash",
            "nav_content_hash",
        }
        if set(payload) != required:
            raise ValueError("strategy manifest payload does not match its schema")
        snapshots = payload["snapshot_ids"]
        summary = payload["completeness_summary"]
        if not isinstance(snapshots, (list, tuple)) or not all(
            isinstance(item, str) for item in snapshots
        ):
            raise ValueError("snapshot_ids must be a string list")
        if not isinstance(summary, Mapping):
            raise ValueError("completeness_summary must be a mapping")
        return cls(
            manifest_version=str(payload["manifest_version"]),
            run_id=str(payload["run_id"]),
            base_run_manifest_hash=str(payload["base_run_manifest_hash"]),
            strategy_id=str(payload["strategy_id"]),
            execution_policy_id=str(payload["execution_policy_id"]),
            initial_capital=to_decimal(payload["initial_capital"]),  # type: ignore[arg-type]
            signal_start=date.fromisoformat(str(payload["signal_start"])),
            signal_end=date.fromisoformat(str(payload["signal_end"])),
            snapshot_ids=tuple(snapshots),
            benchmark_id=str(payload["benchmark_id"]),
            benchmark_snapshot_id=str(payload["benchmark_snapshot_id"]),
            fee_schedule_id=str(payload["fee_schedule_id"]),
            config_hash=str(payload["config_hash"]),
            code_version=str(payload["code_version"]),
            rules_version=str(payload["rules_version"]),
            completeness_summary=summary,
            order_content_hash=str(payload["order_content_hash"]),
            holding_content_hash=str(payload["holding_content_hash"]),
            nav_content_hash=str(payload["nav_content_hash"]),
        )

    def canonical_json(self) -> str:
        return unicodedata.normalize(
            "NFC",
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _nonempty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be non-empty")
    return unicodedata.normalize("NFC", value)


def _decimal_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _normalize_summary(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("completeness_summary must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        normalized_key = _nonempty(key, "completeness_summary key")
        if item is None or type(item) in (bool, int):
            normalized[normalized_key] = item
        elif isinstance(item, str):
            normalized[normalized_key] = unicodedata.normalize("NFC", item)
        elif isinstance(item, Decimal):
            normalized[normalized_key] = _decimal_text(item)
        else:
            raise ValueError("completeness_summary values must be JSON scalars")
    return dict(sorted(normalized.items()))


__all__ = ["StrategyRunManifest"]
