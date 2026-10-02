"""Independent fail-closed gates for v1.3.1 production strategy inputs."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import NoReturn

from turtle_quant.core.result import RuleResult
from turtle_quant.core.share_capital_policy import (
    ShareCapitalEvidence,
    assess_share_capital_policy,
)
from turtle_quant.pit.parquet_benchmark import ParquetBenchmarkReader


class _NotReadyReader:
    domain: str = "strategy input"

    def __init__(self, snapshot_root: str | Path) -> None:
        self.snapshot_root = Path(snapshot_root)

    @classmethod
    def _not_ready(cls) -> NoReturn:
        raise NotImplementedError(
            f"{cls.domain} Parquet reader is not ready under RULE_SPEC v1.3.1: "
            "its independent production coverage and PIT fixture must pass first"
        )


class ParquetIndustryReader(_NotReadyReader):
    domain = "industry"

    def industry_on(self, security_id: str, *, as_of: date) -> NoReturn:
        self._not_ready()


class ParquetSharesReader(_NotReadyReader):
    """No production shares read; the pure ambiguity gate is audit-only.

    Multi-class ordinary shares, nonzero treasury shares (including a
    single-class issuer), missing treasury evidence, and unverified PIT
    availability make S/MV UNKNOWN. ``assess_structure`` classifies explicit
    evidence without I/O; it never makes ``shares_on`` ready or produces S.
    """

    domain = "historical shares"

    @staticmethod
    def assess_structure(
        evidence: ShareCapitalEvidence | None,
        *,
        security_id: str,
        as_of: date,
    ) -> RuleResult:
        return assess_share_capital_policy(evidence, security_id=security_id, as_of=as_of)

    def shares_on(self, security_id: str, *, as_of: date) -> NoReturn:
        self._not_ready()


class ParquetSecurityStatusReader(_NotReadyReader):
    domain = "security status"

    def status_on(self, security_id: str, *, as_of: date) -> NoReturn:
        self._not_ready()


class ParquetTradeabilityReader(_NotReadyReader):
    domain = "tradeability"

    def tradeability_on(
        self, security_id: str, day: date, *, as_of: date
    ) -> NoReturn:
        self._not_ready()


class ParquetCorporateActionsReader(_NotReadyReader):
    domain = "corporate actions"

    def events(
        self,
        security_id: str,
        start: date,
        end: date,
        *,
        as_of: date,
    ) -> NoReturn:
        self._not_ready()


class ParquetCostScheduleReader(_NotReadyReader):
    domain = "historical cost"

    def rate_on(self, day: date) -> NoReturn:
        self._not_ready()


__all__ = [
    "ParquetBenchmarkReader",
    "ParquetCorporateActionsReader",
    "ParquetCostScheduleReader",
    "ParquetIndustryReader",
    "ParquetSecurityStatusReader",
    "ParquetSharesReader",
    "ParquetTradeabilityReader",
]
