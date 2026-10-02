"""Explicit gate for the not-ready financial-statement Parquet reader."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import NoReturn

from turtle_quant.core.pit import FinancialRecord


_NOT_READY = (
    "financial statements Parquet reader is not ready under RULE_SPEC v1.2.0: "
    "complete legal-report and correction revision coverage is required"
)


class ParquetFinancialStatementsReader:
    def __init__(self, snapshot_root: str | Path) -> None:
        self.snapshot_root = Path(snapshot_root)

    @staticmethod
    def _not_ready() -> NoReturn:
        raise NotImplementedError(_NOT_READY)

    def get_financial_record(
        self, security_id: str, period_end: date, *, as_of: date
    ) -> FinancialRecord | None:
        self._not_ready()


__all__ = ["ParquetFinancialStatementsReader"]
