"""Validate evidence-sensitive financial values without performing I/O."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from turtle_quant.core.result import ResultStatus
from turtle_quant.core.types import NumericLike, to_decimal


@dataclass(frozen=True)
class EvidenceAmount:
    """A numeric evidence result that keeps UNKNOWN distinct from zero."""

    status: ResultStatus
    value: Decimal | None
    missing_fields: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is ResultStatus.PASS and self.value is None:
            raise ValueError("PASS evidence amount must contain a value")
        if self.status is ResultStatus.UNKNOWN and self.value is not None:
            raise ValueError("UNKNOWN evidence amount cannot contain a value")
        if any(not item for item in self.missing_fields):
            raise ValueError("missing_fields must contain non-empty names")
        if any(not isinstance(item, str) or not item for item in self.evidence_refs):
            raise ValueError("evidence_refs must contain non-empty strings")
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))


def derive_unrestricted_cash(
    cash_and_equivalents: NumericLike | None,
    restricted_cash: NumericLike | None,
    *,
    cash_evidence_ref: str | None = None,
    restricted_cash_evidence_ref: str | None = None,
) -> EvidenceAmount:
    """Apply the v1.3.0 four-state cash/restriction decision table."""

    cash = _optional_nonnegative(cash_and_equivalents, "cash_and_equivalents")
    restricted = _optional_nonnegative(restricted_cash, "restricted_cash")
    refs = _evidence_refs(cash_evidence_ref, restricted_cash_evidence_ref)

    if cash is None:
        return EvidenceAmount(
            status=ResultStatus.UNKNOWN,
            value=None,
            missing_fields=("cash_and_equivalents",),
            evidence_refs=refs,
        )
    if restricted is None:
        return EvidenceAmount(
            status=ResultStatus.UNKNOWN,
            value=None,
            missing_fields=("restricted_cash",),
            evidence_refs=refs,
        )
    if restricted > cash:
        raise ValueError("restricted_cash cannot exceed cash_and_equivalents")
    return EvidenceAmount(
        status=ResultStatus.PASS,
        value=cash - restricted,
        evidence_refs=refs,
    )


def _optional_nonnegative(
    value: NumericLike | None,
    field_name: str,
) -> Decimal | None:
    if value is None:
        return None
    converted = to_decimal(value)
    if converted < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return converted


def _evidence_refs(*values: str | None) -> tuple[str, ...]:
    refs: list[str] = []
    for value in values:
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise ValueError("evidence refs must be non-empty strings")
        refs.append(value)
    return tuple(refs)


__all__ = ["EvidenceAmount", "derive_unrestricted_cash"]
