"""Pure aggregation of rule outcomes into a research decision."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable

from turtle_quant.core.result import ResultStatus, RuleKind, RuleResult
from turtle_quant.core.types import to_decimal


class DecisionKind(str, Enum):
    CANDIDATE = "CANDIDATE"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_SUPPORTED = "NOT_SUPPORTED"


@dataclass(frozen=True)
class OpportunityDecision:
    kind: DecisionKind
    reasons: tuple[str, ...] = ()
    reference_score_incomplete: bool = False


def decide(
    rule_results: Iterable[RuleResult],
    *,
    coverage6: Decimal | None,
    gg_pct: Decimal | None,
    required_return_pct: Decimal | None,
    score_coverage: Decimal,
    profile_status: ResultStatus = ResultStatus.PASS,
) -> OpportunityDecision:
    """Aggregate frozen decision priorities without handling portfolios/orders."""
    results = tuple(rule_results)
    score_coverage_decimal = to_decimal(score_coverage)
    if not Decimal("0") <= score_coverage_decimal <= Decimal("1"):
        raise ValueError("score_coverage must be between 0 and 1")

    if profile_status in {
        ResultStatus.NOT_SUPPORTED,
        ResultStatus.NOT_APPLICABLE,
    }:
        return OpportunityDecision(
            kind=DecisionKind.NOT_SUPPORTED,
            reasons=("industry_profile_not_supported",),
        )

    unknown_results = tuple(
        result
        for result in results
        if result.kind is not RuleKind.INFORMATION
        and result.status in {ResultStatus.UNKNOWN, ResultStatus.NEEDS_REVIEW}
    )
    if (
        unknown_results
        or coverage6 is None
        or gg_pct is None
        or required_return_pct is None
        or score_coverage_decimal < Decimal("1")
    ):
        reasons = tuple(result.rule_id for result in unknown_results)
        if score_coverage_decimal < Decimal("1"):
            reasons += ("score_coverage_incomplete",)
        if coverage6 is None:
            reasons += ("coverage6_unknown",)
        if gg_pct is None:
            reasons += ("gg_unknown",)
        if required_return_pct is None:
            reasons += ("required_return_unknown",)
        return OpportunityDecision(
            kind=DecisionKind.NEEDS_REVIEW,
            reasons=reasons,
            reference_score_incomplete=score_coverage_decimal < Decimal("1"),
        )

    hard_gate_failures = tuple(
        result.rule_id
        for result in results
        if result.kind is RuleKind.HARD_GATE
        and result.status is ResultStatus.FAIL
    )
    if hard_gate_failures:
        return OpportunityDecision(
            kind=DecisionKind.REJECTED,
            reasons=hard_gate_failures,
        )

    coverage6_decimal = to_decimal(coverage6)
    gg_decimal = to_decimal(gg_pct)
    required_return_decimal = to_decimal(required_return_pct)
    if coverage6_decimal < Decimal("1"):
        return OpportunityDecision(
            kind=DecisionKind.REJECTED,
            reasons=("coverage6_below_one",),
        )
    if gg_decimal < required_return_decimal:
        return OpportunityDecision(
            kind=DecisionKind.REJECTED,
            reasons=("gg_below_required_return",),
        )
    return OpportunityDecision(kind=DecisionKind.CANDIDATE)
