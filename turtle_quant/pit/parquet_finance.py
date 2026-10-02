"""All-or-nothing gate for the aggregate finance Parquet facade."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import NoReturn

from turtle_quant.core.pit import FinancialRecord


_NOT_READY = (
    "aggregate finance Parquet facade requires all three dedicated finance "
    "readers to be ready; partial opening is forbidden by RULE_SPEC v1.2.0"
)


class ParquetFinanceReader:
    def __init__(self, snapshot_root: str | Path) -> None:
        self.snapshot_root = Path(snapshot_root)

    @staticmethod
    def _not_ready() -> NoReturn:
        raise NotImplementedError(_NOT_READY)

    def get_financial_record(
        self, security_id: str, period_end: date, *, as_of: date
    ) -> FinancialRecord | None:
        self._not_ready()

    def dividend_events(
        self,
        security_id: str,
        start: date,
        end: date,
        *,
        as_of: date,
    ) -> NoReturn:
        self._not_ready()

    def buyback_events(
        self,
        security_id: str,
        start: date,
        end: date,
        *,
        as_of: date,
    ) -> NoReturn:
        self._not_ready()


__all__ = ["ParquetFinanceReader"]
