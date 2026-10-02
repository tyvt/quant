"""Fixture-backed point-in-time readers.

The reader deliberately models visibility separately from fiscal period. A
record is usable only when it was available to an investor on or before the
requested ``as_of`` date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Iterable, Mapping


@dataclass(frozen=True)
class FinancialRecord:
    security_id: str
    period_end: date
    available_at: date
    provider_revision_sequence: int
    values: Mapping[str, Decimal]
    evidence_ref: str
    announcement_time: date | None = None
    revision_id: str | None = None

    def __post_init__(self) -> None:
        if not self.security_id:
            raise ValueError("security_id must be non-empty")
        if self.provider_revision_sequence < 0:
            raise ValueError("provider_revision_sequence must be non-negative")
        if not self.evidence_ref:
            raise ValueError("evidence_ref must be non-empty")
        values = dict(self.values)
        if any(
            not isinstance(value, Decimal) or not value.is_finite()
            for value in values.values()
        ):
            raise ValueError("financial values must be finite Decimal instances")
        object.__setattr__(self, "values", MappingProxyType(values))


class InMemoryPITReader:
    """A deterministic reader for fixture data and PIT boundary tests."""

    def __init__(self, records: Iterable[FinancialRecord]) -> None:
        self._records = tuple(records)
        revision_keys = {
            (
                record.security_id,
                record.period_end,
                record.available_at,
                record.provider_revision_sequence,
            )
            for record in self._records
        }
        if len(revision_keys) != len(self._records):
            raise ValueError(
                "records must have unique PIT revision ordering keys"
            )

    def get_financial_record(
        self, security_id: str, period_end: date, *, as_of: date
    ) -> FinancialRecord | None:
        """Return the newest version available at ``as_of`` for one period."""
        visible = [
            record
            for record in self._records
            if record.security_id == security_id
            and record.period_end == period_end
            and record.available_at <= as_of
        ]
        if not visible:
            return None
        return max(
            visible,
            key=lambda record: (
                record.available_at,
                record.provider_revision_sequence,
            ),
        )


@dataclass(frozen=True)
class SecurityRecord:
    security_id: str
    listed_at: date
    delisted_at: date | None

    def __post_init__(self) -> None:
        if not self.security_id:
            raise ValueError("security_id must be non-empty")
        if self.delisted_at is not None and self.delisted_at < self.listed_at:
            raise ValueError("delisted_at cannot precede listed_at")


class InMemorySecurityMasterReader:
    """Historical security universe reader which preserves delisted securities."""

    def __init__(self, records: Iterable[SecurityRecord]) -> None:
        self._records = tuple(records)

    def security_ids_as_of(self, as_of: date) -> tuple[str, ...]:
        return tuple(
            record.security_id
            for record in self._records
            if record.listed_at <= as_of
            and (record.delisted_at is None or as_of <= record.delisted_at)
        )


@dataclass(frozen=True)
class PointInTimeAttribute:
    """One versioned industry, shares, status, or other scalar attribute."""

    security_id: str
    field_name: str
    effective_on: date
    available_at: date
    provider_revision_sequence: int
    value: Decimal | str | int | bool
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.security_id or not self.field_name:
            raise ValueError("security_id and field_name must be non-empty")
        if type(self.effective_on) is not date or type(self.available_at) is not date:
            raise ValueError("effective_on and available_at must be dates")
        if (
            isinstance(self.provider_revision_sequence, bool)
            or not isinstance(self.provider_revision_sequence, int)
            or self.provider_revision_sequence < 0
        ):
            raise ValueError("provider_revision_sequence must be non-negative")
        if isinstance(self.value, Decimal):
            if not self.value.is_finite():
                raise ValueError("attribute Decimal value must be finite")
        elif type(self.value) not in (str, int, bool):
            raise ValueError("attribute value must be a non-null scalar")
        if isinstance(self.value, str) and not self.value:
            raise ValueError("attribute string value must be non-empty")
        if not self.evidence_ref:
            raise ValueError("evidence_ref must be non-empty")


class InMemoryAttributeReader:
    """Fixture reader that blocks future-effective and future-available values."""

    def __init__(self, observations: Iterable[PointInTimeAttribute]) -> None:
        self._observations = tuple(observations)
        if any(not isinstance(item, PointInTimeAttribute) for item in self._observations):
            raise ValueError("observations must contain PointInTimeAttribute values")
        keys = tuple(
            (
                item.security_id,
                item.field_name,
                item.effective_on,
                item.available_at,
                item.provider_revision_sequence,
            )
            for item in self._observations
        )
        if len(set(keys)) != len(keys):
            raise ValueError("attribute observations must have unique PIT ordering keys")

    def value_on(
        self,
        security_id: str,
        field_name: str,
        *,
        as_of: date,
    ) -> PointInTimeAttribute | None:
        if type(as_of) is not date:
            raise ValueError("as_of must be a date")
        visible = tuple(
            item
            for item in self._observations
            if item.security_id == security_id
            and item.field_name == field_name
            and item.effective_on <= as_of
            and item.available_at <= as_of
        )
        if not visible:
            return None
        return max(
            visible,
            key=lambda item: (
                item.effective_on,
                item.available_at,
                item.provider_revision_sequence,
                item.evidence_ref,
            ),
        )
