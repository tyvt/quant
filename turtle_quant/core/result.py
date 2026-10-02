"""Explicit result states for rules and decision aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class ResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class RuleKind(str, Enum):
    HARD_GATE = "HARD_GATE"
    SCORE = "SCORE"
    EVIDENCE = "EVIDENCE"
    INFORMATION = "INFORMATION"


@dataclass(frozen=True)
class RuleResult:
    """Result of one rule without conflating missing evidence with a zero."""

    rule_id: str
    kind: RuleKind
    status: ResultStatus
    value: Decimal | None = None
    notes: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must be non-empty")
        object.__setattr__(self, "notes", tuple(self.notes))
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
