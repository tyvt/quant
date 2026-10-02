"""Point-in-time universe screening and monthly selection."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import re
from types import MappingProxyType
from typing import Mapping

from turtle_quant.core.result import ResultStatus
from turtle_quant.core.share_capital_policy import (
    ShareCapitalEvidence,
    assess_share_capital_policy,
)
from turtle_quant.core.types import calculation_context, to_decimal
from turtle_quant.pipeline.decision import DecisionKind


_SECURITY_ID = re.compile(r"^(sh|sz)\.\d{6}$")
_MARKET_VALUE_MIN = Decimal("5000000000")
_LIQUIDITY_MEDIAN_MIN = Decimal("20000000")


def _security_id(value: object) -> str:
    if not isinstance(value, str) or not _SECURITY_ID.fullmatch(value):
        raise ValueError("security_id must use canonical sh.600000 form")
    return value


def _tri_state(value: object, field_name: str) -> bool | None:
    if value is None or type(value) is bool:
        return value  # type: ignore[return-value]
    raise ValueError(f"{field_name} must be bool or None")


def _optional_nonnegative(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    converted = to_decimal(value)  # type: ignore[arg-type]
    if converted < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return converted


@dataclass(frozen=True)
class LiquidityDay:
    trade_date: date
    amount: Decimal | None
    tradable: bool | None
    evidence_ref: str | None

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")
        object.__setattr__(self, "amount", _optional_nonnegative(self.amount, "amount"))
        object.__setattr__(self, "tradable", _tri_state(self.tradable, "tradable"))
        if self.evidence_ref is not None and (
            not isinstance(self.evidence_ref, str) or not self.evidence_ref
        ):
            raise ValueError("evidence_ref must be non-empty or None")


@dataclass(frozen=True)
class UniverseInput:
    security_id: str
    as_of: date
    expected_liquidity_dates: tuple[date, ...]
    main_board_a_share: bool | None
    listing_trading_days: int | None
    industry_profile: str | None
    eligible_security_status: bool | None
    market_value: Decimal | None
    liquidity_days: tuple[LiquidityDay, ...]
    stage_a_coverage_complete: bool | None
    shares_known: bool | None
    # Optional only for legacy synthetic fixtures while the production shares
    # reader is not ready. A future production adapter must supply PIT evidence.
    share_capital_evidence: ShareCapitalEvidence | None = None

    def __post_init__(self) -> None:
        _security_id(self.security_id)
        if type(self.as_of) is not date:
            raise ValueError("as_of must be a date")
        expected = tuple(self.expected_liquidity_dates)
        if (
            len(expected) != 60
            or any(type(item) is not date for item in expected)
            or tuple(sorted(expected)) != expected
            or len(set(expected)) != 60
            or expected[-1] != self.as_of
        ):
            raise ValueError("expected_liquidity_dates must be 60 ordered trading dates ending at as_of")
        object.__setattr__(self, "expected_liquidity_dates", expected)
        for field_name in (
            "main_board_a_share",
            "eligible_security_status",
            "stage_a_coverage_complete",
            "shares_known",
        ):
            object.__setattr__(
                self, field_name, _tri_state(getattr(self, field_name), field_name)
            )
        if self.share_capital_evidence is not None and not isinstance(
            self.share_capital_evidence, ShareCapitalEvidence
        ):
            raise ValueError("share_capital_evidence must be ShareCapitalEvidence or None")
        if self.listing_trading_days is not None and (
            isinstance(self.listing_trading_days, bool)
            or not isinstance(self.listing_trading_days, int)
            or self.listing_trading_days < 0
        ):
            raise ValueError("listing_trading_days must be a non-negative integer or None")
        if self.industry_profile is not None:
            if not isinstance(self.industry_profile, str) or not self.industry_profile:
                raise ValueError("industry_profile must be non-empty or None")
            object.__setattr__(self, "industry_profile", self.industry_profile.upper())
        object.__setattr__(
            self, "market_value", _optional_nonnegative(self.market_value, "market_value")
        )
        rows = tuple(self.liquidity_days)
        if any(not isinstance(item, LiquidityDay) for item in rows):
            raise ValueError("liquidity_days must contain LiquidityDay values")
        ordered = tuple(sorted(rows, key=lambda item: item.trade_date))
        if len({item.trade_date for item in ordered}) != len(ordered):
            raise ValueError("liquidity_days must have unique dates")
        object.__setattr__(self, "liquidity_days", ordered)


class UniverseStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_SUPPORTED = "NOT_SUPPORTED"


@dataclass(frozen=True)
class UniverseResult:
    security_id: str
    status: UniverseStatus
    reasons: tuple[str, ...]
    valid_trading_amount_days: int = 0
    median_trading_amount: Decimal | None = None


def evaluate_universe_security(inputs: UniverseInput) -> UniverseResult:
    """Apply the frozen structural-universe screen without hiding unknowns."""

    share_policy = (
        assess_share_capital_policy(
            inputs.share_capital_evidence,
            security_id=inputs.security_id,
            as_of=inputs.as_of,
        )
        if inputs.share_capital_evidence is not None
        else None
    )
    if inputs.industry_profile is not None and inputs.industry_profile != "GENERAL_FCF":
        if share_policy is not None and share_policy.status is ResultStatus.UNKNOWN:
            # The approved interim ruling forbids masking an ambiguous S/MV
            # as NOT_SUPPORTED, even when another profile is unsupported.
            return UniverseResult(
                inputs.security_id,
                UniverseStatus.NEEDS_REVIEW,
                tuple(sorted({
                    "industry_profile_not_supported",
                    "shares_unknown",
                    "market_value_unknown",
                    *share_policy.notes,
                })),
            )
        return UniverseResult(
            inputs.security_id,
            UniverseStatus.NOT_SUPPORTED,
            ("industry_profile_not_supported",),
        )

    unknown_reasons: list[str] = []
    if inputs.main_board_a_share is None:
        unknown_reasons.append("board_unknown")
    if inputs.listing_trading_days is None:
        unknown_reasons.append("listing_history_unknown")
    if inputs.industry_profile is None:
        unknown_reasons.append("industry_profile_unknown")
    if inputs.eligible_security_status is None:
        unknown_reasons.append("security_status_unknown")
    if inputs.market_value is None:
        unknown_reasons.append("market_value_unknown")
    if inputs.stage_a_coverage_complete is not True:
        unknown_reasons.append("stage_a_coverage_incomplete")
    if inputs.shares_known is not True:
        unknown_reasons.append("shares_unknown")
    if share_policy is not None:
        if share_policy.status is ResultStatus.UNKNOWN:
            # A supplied market value cannot override an ambiguous S denominator.
            unknown_reasons.extend(("shares_unknown", "market_value_unknown"))
            unknown_reasons.extend(share_policy.notes)

    by_date = {
        day.trade_date: day
        for day in inputs.liquidity_days if day.trade_date <= inputs.as_of
    }
    window = tuple(by_date.get(day) for day in inputs.expected_liquidity_dates)
    amounts: list[Decimal] = []
    if any(item is None for item in window):
        unknown_reasons.append("liquidity_window_incomplete")
    for observation in window:
        if observation is None:
            continue
        if observation.evidence_ref is None or observation.tradable is None:
            unknown_reasons.append("liquidity_evidence_unknown")
            continue
        if observation.tradable:
            if observation.amount is None:
                unknown_reasons.append("liquidity_evidence_unknown")
            else:
                amounts.append(observation.amount)

    median_amount = _median(tuple(amounts)) if amounts else None
    if unknown_reasons:
        return UniverseResult(
            inputs.security_id,
            UniverseStatus.NEEDS_REVIEW,
            tuple(sorted(set(unknown_reasons))),
            len(amounts),
            median_amount,
        )

    rejection_reasons: list[str] = []
    if inputs.main_board_a_share is not True:
        rejection_reasons.append("not_main_board_a_share")
    assert inputs.listing_trading_days is not None
    if inputs.listing_trading_days < 504:
        rejection_reasons.append("listing_history_below_504")
    if inputs.eligible_security_status is not True:
        rejection_reasons.append("ineligible_security_status")
    assert inputs.market_value is not None
    if inputs.market_value < _MARKET_VALUE_MIN:
        rejection_reasons.append("market_value_below_threshold")
    if len(amounts) < 50:
        rejection_reasons.append("insufficient_tradable_amount_days")
    if median_amount is None or median_amount < _LIQUIDITY_MEDIAN_MIN:
        rejection_reasons.append("median_trading_amount_below_threshold")
    return UniverseResult(
        inputs.security_id,
        UniverseStatus.REJECTED if rejection_reasons else UniverseStatus.ELIGIBLE,
        tuple(rejection_reasons),
        len(amounts),
        median_amount,
    )


@dataclass(frozen=True)
class CandidateMetrics:
    quality_score: Decimal
    coverage6: Decimal
    gg_margin_pct: Decimal
    market_position_score: Decimal

    def __post_init__(self) -> None:
        for field_name in (
            "quality_score",
            "coverage6",
            "gg_margin_pct",
            "market_position_score",
        ):
            object.__setattr__(self, field_name, to_decimal(getattr(self, field_name)))
        if not Decimal("0") <= self.quality_score <= Decimal("100"):
            raise ValueError("quality_score must be between 0 and 100")
        if not Decimal("0") <= self.market_position_score <= Decimal("100"):
            raise ValueError("market_position_score must be between 0 and 100")


@dataclass(frozen=True)
class SecurityAssessment:
    security_id: str
    decision_kind: DecisionKind
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...]
    quality_flags: tuple[str, ...]
    hard_gate_statuses: tuple[str, ...]
    score_statuses: tuple[str, ...]
    evidence_statuses: tuple[str, ...]
    metrics: CandidateMetrics | None

    def __post_init__(self) -> None:
        _security_id(self.security_id)
        if not isinstance(self.decision_kind, DecisionKind):
            raise ValueError("decision_kind must be DecisionKind")
        for field_name in (
            "reasons",
            "missing_fields",
            "quality_flags",
            "hard_gate_statuses",
            "score_statuses",
            "evidence_statuses",
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(item, str) or not item for item in values):
                raise ValueError(f"{field_name} must contain non-empty strings")
            object.__setattr__(self, field_name, values)
        if self.metrics is not None and not isinstance(self.metrics, CandidateMetrics):
            raise ValueError("metrics must be CandidateMetrics or None")
        if self.decision_kind is DecisionKind.CANDIDATE and self.metrics is None:
            raise ValueError("candidate assessment requires complete metrics")


@dataclass(frozen=True)
class DiagnosticRecord:
    security_id: str
    decision_kind: str
    hard_gate_statuses: tuple[str, ...]
    score_statuses: tuple[str, ...]
    evidence_statuses: tuple[str, ...]
    missing_fields: tuple[str, ...]
    reasons: tuple[str, ...]
    quality_flags: tuple[str, ...]
    diagnostic_only: bool = True
    official_selection: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "security_id": self.security_id,
            "decision_kind": self.decision_kind,
            "hard_gate_statuses": list(self.hard_gate_statuses),
            "score_statuses": list(self.score_statuses),
            "evidence_statuses": list(self.evidence_statuses),
            "missing_fields": list(self.missing_fields),
            "reasons": list(self.reasons),
            "quality_flags": list(self.quality_flags),
            "diagnostic_only": self.diagnostic_only,
            "official_selection": self.official_selection,
        }


@dataclass(frozen=True)
class RankedCandidate:
    security_id: str
    rank: int
    quality_score: Decimal
    coverage_rank: Decimal
    gg_margin_rank: Decimal
    market_position_score: Decimal
    composite_score: Decimal


@dataclass(frozen=True)
class MonthlySelection:
    diagnostic_only: bool
    official_selection: bool
    diagnostics: tuple[DiagnosticRecord, ...]
    ranked_candidates: tuple[RankedCandidate, ...]
    target_weights: Mapping[str, Decimal]
    cash_weight: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "ranked_candidates", tuple(self.ranked_candidates))
        object.__setattr__(
            self,
            "target_weights",
            MappingProxyType(dict(self.target_weights)),
        )


def build_monthly_selection(
    assessments: tuple[SecurityAssessment, ...],
) -> MonthlySelection:
    """Create either diagnostics or an official deterministic Top-20."""

    values = tuple(assessments)
    if any(not isinstance(item, SecurityAssessment) for item in values):
        raise ValueError("assessments must contain SecurityAssessment values")
    ids = tuple(item.security_id for item in values)
    if len(set(ids)) != len(ids):
        raise ValueError("assessments must contain unique security IDs")
    if any(item.decision_kind is DecisionKind.NEEDS_REVIEW for item in values):
        diagnostics = tuple(
            _diagnostic(item) for item in sorted(values, key=lambda item: item.security_id)
        )
        return MonthlySelection(
            diagnostic_only=True,
            official_selection=False,
            diagnostics=diagnostics,
            ranked_candidates=(),
            target_weights={},
            cash_weight=Decimal("1"),
        )

    candidates = tuple(
        item for item in values if item.decision_kind is DecisionKind.CANDIDATE
    )
    ranked = _rank_candidates(candidates)[:20]
    selected_count = len(ranked)
    if selected_count:
        weight = min(Decimal("0.05"), Decimal("1") / Decimal(selected_count))
        weights = {item.security_id: weight for item in ranked}
    else:
        weights = {}
    cash_weight = Decimal("1") - sum(weights.values(), Decimal("0"))
    return MonthlySelection(
        diagnostic_only=False,
        official_selection=True,
        diagnostics=(),
        ranked_candidates=ranked,
        target_weights=weights,
        cash_weight=cash_weight,
    )


def _diagnostic(assessment: SecurityAssessment) -> DiagnosticRecord:
    return DiagnosticRecord(
        security_id=assessment.security_id,
        decision_kind=assessment.decision_kind.value,
        hard_gate_statuses=assessment.hard_gate_statuses,
        score_statuses=assessment.score_statuses,
        evidence_statuses=assessment.evidence_statuses,
        missing_fields=assessment.missing_fields,
        reasons=assessment.reasons,
        quality_flags=assessment.quality_flags,
    )


def _rank_candidates(
    candidates: tuple[SecurityAssessment, ...],
) -> tuple[RankedCandidate, ...]:
    if not candidates:
        return ()
    coverages = tuple(item.metrics.coverage6 for item in candidates if item.metrics)
    margins = tuple(item.metrics.gg_margin_pct for item in candidates if item.metrics)
    interim: list[tuple[str, Decimal, Decimal, Decimal, Decimal]] = []
    with calculation_context():
        for item in candidates:
            assert item.metrics is not None
            coverage_rank = _midrank(item.metrics.coverage6, coverages) * Decimal("100")
            margin_rank = _midrank(item.metrics.gg_margin_pct, margins) * Decimal("100")
            composite = (
                Decimal("0.30") * item.metrics.quality_score
                + Decimal("0.30") * coverage_rank
                + Decimal("0.30") * margin_rank
                + Decimal("0.10") * item.metrics.market_position_score
            )
            interim.append(
                (
                    item.security_id,
                    item.metrics.quality_score,
                    coverage_rank,
                    margin_rank,
                    composite,
                )
            )
    interim.sort(key=lambda item: (-item[4], item[0]))
    by_id = {item.security_id: item for item in candidates}
    return tuple(
        RankedCandidate(
            security_id=security_id,
            rank=index,
            quality_score=quality,
            coverage_rank=coverage_rank,
            gg_margin_rank=margin_rank,
            market_position_score=by_id[security_id].metrics.market_position_score,  # type: ignore[union-attr]
            composite_score=composite,
        )
        for index, (
            security_id,
            quality,
            coverage_rank,
            margin_rank,
            composite,
        ) in enumerate(interim, start=1)
    )


def _midrank(value: Decimal, population: tuple[Decimal, ...]) -> Decimal:
    lower = sum(item < value for item in population)
    equal = sum(item == value for item in population)
    return (
        Decimal(lower) + Decimal("0.5") * Decimal(equal)
    ) / Decimal(len(population))


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    count = len(ordered)
    if not count:
        raise ValueError("median requires values")
    midpoint = count // 2
    if count % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def month_end_signal_dates(
    trading_days: tuple[date, ...], *, calendar_complete_through: date
) -> tuple[date, ...]:
    """Return final trading days only for fully covered natural months."""

    values = tuple(trading_days)
    if type(calendar_complete_through) is not date:
        raise ValueError("calendar_complete_through must be a date")
    if any(type(item) is not date for item in values):
        raise ValueError("trading_days must contain dates")
    if len(set(values)) != len(values):
        raise ValueError("trading_days must be unique")
    if any(day > calendar_complete_through for day in values):
        raise ValueError("trading_days cannot exceed calendar_complete_through")
    month_ends: dict[tuple[int, int], date] = {}
    for day in sorted(values):
        month_ends[(day.year, day.month)] = day
    return tuple(
        month_ends[key]
        for key in sorted(month_ends)
        if date(key[0], key[1], calendar.monthrange(*key)[1]) <= calendar_complete_through
    )


__all__ = [
    "CandidateMetrics",
    "DiagnosticRecord",
    "LiquidityDay",
    "MonthlySelection",
    "RankedCandidate",
    "SecurityAssessment",
    "UniverseInput",
    "UniverseResult",
    "UniverseStatus",
    "build_monthly_selection",
    "evaluate_universe_security",
    "month_end_signal_dates",
]
