"""Compatibility-only placeholder for the old aggregate Parquet PIT reader.

``RULE_SPEC v1.2.0`` keeps this ambiguous aggregate interface ``not_ready``.
Stage-A callers must choose :mod:`parquet_foundation`; finance callers must use
the dedicated domain modules once their independent gates become ready.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import NoReturn, Sequence

from turtle_quant.core.pit import FinancialRecord


_NOT_READY_MESSAGE = (
    "pit.parquet is not ready under RULE_SPEC.md and remains a compatibility "
    "stub: use pit.parquet_foundation for stage-A data; financial statements, "
    "dividends, buybacks, and the aggregate finance facade remain separately "
    "gated"
)


class ParquetPITReader:
    """Declare the production PIT boundary without implementing data access."""

    def __init__(self, snapshot_root: str | Path) -> None:
        # Path construction is lexical only: no existence check or snapshot I/O.
        self.snapshot_root = Path(snapshot_root)

    @staticmethod
    def _not_ready() -> NoReturn:
        raise NotImplementedError(_NOT_READY_MESSAGE)

    def get_financial_record(
        self, security_id: str, period_end: date, *, as_of: date
    ) -> FinancialRecord | None:
        """Refuse financial reads until their PIT revision contract is ready."""
        self._not_ready()

    def security_ids_as_of(self, as_of: date) -> tuple[str, ...]:
        """Refuse security-universe reads through the unpublished reader."""
        self._not_ready()

    def adjustment_factor_series(
        self, security_id: str, start: date, end: date, *, as_of: date
    ) -> Sequence[object]:
        """Refuse adjustment-factor reads through the unpublished reader."""
        self._not_ready()

    def price_bars(
        self, security_id: str, start: date, end: date, *, as_of: date
    ) -> Sequence[object]:
        """Refuse market-data reads through the unpublished reader."""
        self._not_ready()

    def value_on(self, series: str, *, as_of: date) -> object | None:
        """Refuse rate-curve reads through the unpublished reader."""
        self._not_ready()
