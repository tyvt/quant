"""Pure GENERAL_FCF premise and quality scoring for RULE_SPEC v1.3.0."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from turtle_quant.core.result import ResultStatus, RuleKind, RuleResult
from turtle_quant.core.types import calculation_context, to_decimal


_QUALITY_KEYS = (
    "roe_score",
    "fcf_stability_score",
    "cash_conversion_score",
    "balance_score",
)


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return to_decimal(value)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}") from exc


def _optional_nonnegative(value: object, field_name: str) -> Decimal | None:
    converted = _optional_decimal(value, field_name)
    if converted is not None and converted < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return converted


def _tri_state(value: object, field_name: str) -> bool | None:
    if value is None or type(value) is bool:
        return value  # type: ignore[return-value]
    raise ValueError(f"{field_name} must be bool or None")


@dataclass(frozen=True)
class AnnualFinancialObservation:
    fiscal_year: int
    available_at: date
    attributable_equity_end: Decimal | None
    total_equity_end: Decimal | None
    minority_interest_end: Decimal | None
    parent_net_profit: Decimal | None
    operating_cash_flow: Decimal | None
    capex: Decimal | None
    lease_cash_not_already_deducted: Decimal | None
    currency: str
    statement_scope: str
    traceable: bool
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.fiscal_year, bool) or not isinstance(self.fiscal_year, int):
            raise ValueError("fiscal_year must be an integer")
        if self.fiscal_year < 1900:
            raise ValueError("fiscal_year is outside the supported range")
        if type(self.available_at) is not date:
            raise ValueError("available_at must be a date")
        for field_name in (
            "attributable_equity_end",
            "total_equity_end",
            "minority_interest_end",
            "parent_net_profit",
            "operating_cash_flow",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_decimal(getattr(self, field_name), field_name),
            )
        for field_name in ("capex", "lease_cash_not_already_deducted"):
            object.__setattr__(
                self,
                field_name,
                _optional_nonnegative(getattr(self, field_name), field_name),
            )
        for field_name in ("currency", "statement_scope"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value.strip().upper())
        if type(self.traceable) is not bool:
            raise ValueError("traceable must be bool")
        refs = tuple(self.evidence_refs)
        if any(not isinstance(item, str) or not item for item in refs):
            raise ValueError("evidence_refs must contain non-empty strings")
        object.__setattr__(self, "evidence_refs", refs)


@dataclass(frozen=True)
class QualityWeights:
    roe_score: Decimal = Decimal("0.35")
    fcf_stability_score: Decimal = Decimal("0.25")
    cash_conversion_score: Decimal = Decimal("0.25")
    balance_score: Decimal = Decimal("0.15")

    def __post_init__(self) -> None:
        converted: list[Decimal] = []
        for key in _QUALITY_KEYS:
            value = to_decimal(getattr(self, key))
            if value < 0:
                raise ValueError("quality weights must be non-negative")
            object.__setattr__(self, key, value)
            converted.append(value)
        if sum(converted, Decimal("0")) != Decimal("1.00"):
            raise ValueError("quality weights must sum exactly to 1.00")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "QualityWeights":
        if set(values) != set(_QUALITY_KEYS):
            raise ValueError("quality weight keys must exactly match score components")
        return cls(**{key: to_decimal(values[key]) for key in _QUALITY_KEYS})

    def as_mapping(self) -> Mapping[str, Decimal]:
        return MappingProxyType({key: getattr(self, key) for key in _QUALITY_KEYS})


@dataclass(frozen=True)
class QualityComponents:
    roe_score: Decimal | None
    fcf_stability_score: Decimal | None
    cash_conversion_score: Decimal | None
    balance_score: Decimal | None

    def __post_init__(self) -> None:
        for key in _QUALITY_KEYS:
            value = _optional_decimal(getattr(self, key), key)
            if value is not None and not Decimal("0") <= value <= Decimal("100"):
                raise ValueError(f"{key} must be between 0 and 100")
            object.__setattr__(self, key, value)

    def as_mapping(self) -> Mapping[str, Decimal | None]:
        return MappingProxyType({key: getattr(self, key) for key in _QUALITY_KEYS})


@dataclass(frozen=True)
class QualityScoreResult:
    components: QualityComponents
    quality_score: Decimal | None
    score_coverage: Decimal
    reference_raw_score: Decimal


def combine_quality_scores(
    components: QualityComponents,
    weights: QualityWeights | None = None,
) -> QualityScoreResult:
    """Combine scores without renormalizing around UNKNOWN components."""

    weights = weights or QualityWeights()
    with calculation_context():
        raw_score = Decimal("0")
        coverage = Decimal("0")
        missing = False
        for key, weight in weights.as_mapping().items():
            component = components.as_mapping()[key]
            if component is None:
                missing = True
                continue
            coverage += weight
            raw_score += weight * component
        return QualityScoreResult(
            components=components,
            quality_score=None if missing else raw_score,
            score_coverage=coverage,
            reference_raw_score=raw_score,
        )


@dataclass(frozen=True)
class GeneralFCFInputs:
    as_of: date
    industry_profile: str | None
    statements_comparable: bool | None
    latest_audit_unmodified: bool | None
    going_concern_uncertainty: bool | None
    latest_equity: Decimal | None
    annual_observations: tuple[AnnualFinancialObservation, ...]
    cash: Decimal | None
    liquid_assets: Decimal | None
    interest_bearing_debt: Decimal | None
    quality_weights: QualityWeights = field(default_factory=QualityWeights)

    def __post_init__(self) -> None:
        if type(self.as_of) is not date:
            raise ValueError("as_of must be a date")
        if self.industry_profile is not None:
            if not isinstance(self.industry_profile, str) or not self.industry_profile:
                raise ValueError("industry_profile must be non-empty or None")
            object.__setattr__(self, "industry_profile", self.industry_profile.upper())
        for field_name in (
            "statements_comparable",
            "latest_audit_unmodified",
            "going_concern_uncertainty",
        ):
            object.__setattr__(
                self, field_name, _tri_state(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "latest_equity", _optional_decimal(self.latest_equity, "latest_equity")
        )
        for field_name in ("cash", "liquid_assets", "interest_bearing_debt"):
            object.__setattr__(
                self,
                field_name,
                _optional_nonnegative(getattr(self, field_name), field_name),
            )
        observations = tuple(self.annual_observations)
        if any(not isinstance(item, AnnualFinancialObservation) for item in observations):
            raise ValueError("annual_observations contains an invalid value")
        object.__setattr__(self, "annual_observations", observations)
        if not isinstance(self.quality_weights, QualityWeights):
            raise ValueError("quality_weights must be QualityWeights")


@dataclass(frozen=True)
class GeneralFCFEvaluation:
    y0: int | None
    hard_gates: tuple[RuleResult, ...]
    annual_roe_pct: tuple[Decimal, ...]
    median_roe_5y: Decimal | None
    annual_fcf_newest_to_oldest: tuple[Decimal, ...]
    annual_alpha_newest_to_oldest: tuple[Decimal, ...]
    f_norm: Decimal | None
    net_debt: Decimal | None
    quality: QualityScoreResult

    def gate(self, rule_id: str) -> RuleResult:
        for gate in self.hard_gates:
            if gate.rule_id == rule_id:
                return gate
        raise KeyError(rule_id)


def evaluate_general_fcf(inputs: GeneralFCFInputs) -> GeneralFCFEvaluation:
    """Evaluate the frozen six hard gates and quality score."""

    with calculation_context():
        observations = _latest_visible_annuals(inputs)
        y0 = max(observations) if observations else None
        required = _required_annuals(observations, y0)

        profile_gate = _profile_gate(inputs.industry_profile)
        statement_gate = _statement_gate(inputs, required)
        equity_gate = _positive_equity_gate(inputs.latest_equity)
        annual_roe, median_roe, roe_gate = _roe_gate(required)
        annual_fcf, alphas, fcf_gate = _fcf_gate(required)
        f_norm = _normalised_fcf(annual_fcf) if len(annual_fcf) == 5 else None
        net_debt, leverage_gate = _leverage_gate(inputs, f_norm)
        hard_gates = (
            profile_gate,
            statement_gate,
            equity_gate,
            roe_gate,
            fcf_gate,
            leverage_gate,
        )

        if all(gate.status is ResultStatus.PASS for gate in hard_gates):
            components = _quality_components(
                required=required,
                annual_fcf=annual_fcf,
                alphas=alphas,
                median_roe=median_roe,
                net_debt=net_debt,
                f_norm=f_norm,
            )
        else:
            components = QualityComponents(None, None, None, None)
        quality = combine_quality_scores(components, inputs.quality_weights)

        return GeneralFCFEvaluation(
            y0=y0,
            hard_gates=hard_gates,
            annual_roe_pct=annual_roe,
            median_roe_5y=median_roe,
            annual_fcf_newest_to_oldest=annual_fcf,
            annual_alpha_newest_to_oldest=alphas,
            f_norm=f_norm,
            net_debt=net_debt,
            quality=quality,
        )


def _latest_visible_annuals(
    inputs: GeneralFCFInputs,
) -> dict[int, AnnualFinancialObservation]:
    selected: dict[int, AnnualFinancialObservation] = {}
    for observation in inputs.annual_observations:
        if (
            observation.available_at > inputs.as_of
            or not observation.traceable
            or not observation.evidence_refs
        ):
            continue
        current = selected.get(observation.fiscal_year)
        if current is None or observation.available_at > current.available_at:
            selected[observation.fiscal_year] = observation
        elif observation.available_at == current.available_at and observation != current:
            raise ValueError("conflicting annual observations at one PIT ordering key")
    return selected


def _required_annuals(
    observations: Mapping[int, AnnualFinancialObservation],
    y0: int | None,
) -> tuple[AnnualFinancialObservation, ...]:
    if y0 is None:
        return ()
    years = tuple(y0 - offset for offset in range(6))
    if any(year not in observations for year in years):
        return ()
    return tuple(observations[year] for year in years)


def _result(
    rule_id: str,
    status: ResultStatus,
    *,
    value: Decimal | None = None,
    missing_fields: tuple[str, ...] = (),
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        kind=RuleKind.HARD_GATE,
        status=status,
        value=value,
        missing_fields=missing_fields,
    )


def _profile_gate(profile: str | None) -> RuleResult:
    if profile is None:
        return _result(
            "premise.profile_supported",
            ResultStatus.UNKNOWN,
            missing_fields=("industry_profile",),
        )
    if profile == "GENERAL_FCF":
        return _result("premise.profile_supported", ResultStatus.PASS)
    return _result("premise.profile_supported", ResultStatus.NOT_SUPPORTED)


def _statement_gate(
    inputs: GeneralFCFInputs,
    required: tuple[AnnualFinancialObservation, ...],
) -> RuleResult:
    values = (
        inputs.statements_comparable,
        inputs.latest_audit_unmodified,
        inputs.going_concern_uncertainty,
    )
    if any(value is None for value in values):
        return _result(
            "premise.statement_integrity",
            ResultStatus.UNKNOWN,
            missing_fields=tuple(
                name
                for name, value in zip(
                    (
                        "statements_comparable",
                        "latest_audit_unmodified",
                        "going_concern_uncertainty",
                    ),
                    values,
                )
                if value is None
            ),
        )
    passed = (
        inputs.statements_comparable is True
        and inputs.latest_audit_unmodified is True
        and inputs.going_concern_uncertainty is False
    )
    if not passed:
        return _result("premise.statement_integrity", ResultStatus.FAIL)
    if len(required) != 6:
        return _result(
            "premise.statement_integrity",
            ResultStatus.UNKNOWN,
            missing_fields=("six_consecutive_traceable_annual_statements",),
        )
    if (
        len({item.currency for item in required}) != 1
        or len({item.statement_scope for item in required}) != 1
    ):
        return _result("premise.statement_integrity", ResultStatus.FAIL)
    return _result(
        "premise.statement_integrity",
        ResultStatus.PASS,
    )


def _positive_equity_gate(equity: Decimal | None) -> RuleResult:
    if equity is None:
        return _result(
            "premise.positive_equity",
            ResultStatus.UNKNOWN,
            missing_fields=("latest_equity",),
        )
    return _result(
        "premise.positive_equity",
        ResultStatus.PASS if equity > 0 else ResultStatus.FAIL,
        value=equity,
    )


def _roe_gate(
    required: tuple[AnnualFinancialObservation, ...],
) -> tuple[tuple[Decimal, ...], Decimal | None, RuleResult]:
    if len(required) != 6:
        return (), None, _result(
            "premise.roe_5y",
            ResultStatus.UNKNOWN,
            missing_fields=("six_consecutive_year_end_equities",),
        )
    roes: list[Decimal] = []
    for offset in range(5):
        current = required[offset]
        previous = required[offset + 1]
        if (
            current.parent_net_profit is None
            or current.attributable_equity_end is None
            or previous.attributable_equity_end is None
        ):
            return (), None, _result(
                "premise.roe_5y",
                ResultStatus.UNKNOWN,
                missing_fields=("annual_profit_or_equity",),
            )
        average_equity = (
            current.attributable_equity_end + previous.attributable_equity_end
        ) / Decimal("2")
        if average_equity <= 0:
            return (), None, _result(
                "premise.roe_5y",
                ResultStatus.UNKNOWN,
                missing_fields=("positive_average_equity",),
            )
        roes.append(current.parent_net_profit / average_equity * Decimal("100"))
    median_roe = _median(tuple(roes))
    return tuple(roes), median_roe, _result(
        "premise.roe_5y",
        ResultStatus.PASS if median_roe >= Decimal("10") else ResultStatus.FAIL,
        value=median_roe,
    )


def _minority_interest(observation: AnnualFinancialObservation) -> Decimal | None:
    if observation.minority_interest_end is not None:
        return observation.minority_interest_end
    if (
        observation.total_equity_end is not None
        and observation.attributable_equity_end is not None
        and observation.total_equity_end == observation.attributable_equity_end
    ):
        return Decimal("0")
    return None


def _fcf_gate(
    required: tuple[AnnualFinancialObservation, ...],
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...], RuleResult]:
    if len(required) != 6:
        return (), (), _result(
            "premise.fcf_consistency",
            ResultStatus.UNKNOWN,
            missing_fields=("five_consecutive_annual_fcf",),
        )
    values: list[Decimal] = []
    alphas: list[Decimal] = []
    for observation in required[:5]:
        minority = _minority_interest(observation)
        fields = (
            observation.attributable_equity_end,
            minority,
            observation.operating_cash_flow,
            observation.capex,
            observation.lease_cash_not_already_deducted,
        )
        if any(value is None for value in fields):
            return (), (), _result(
                "premise.fcf_consistency",
                ResultStatus.UNKNOWN,
                missing_fields=("annual_fcf_inputs",),
            )
        equity = observation.attributable_equity_end
        assert equity is not None and minority is not None
        if equity <= 0:
            return (), (), _result(
                "premise.fcf_consistency",
                ResultStatus.UNKNOWN,
                missing_fields=("positive_attributable_equity",),
            )
        alpha = equity / (equity + max(minority, Decimal("0")))
        assert observation.operating_cash_flow is not None
        assert observation.capex is not None
        assert observation.lease_cash_not_already_deducted is not None
        values.append(
            (
                observation.operating_cash_flow
                - observation.capex
                - observation.lease_cash_not_already_deducted
            )
            * alpha
        )
        alphas.append(alpha)
    positive_years = sum(value > 0 for value in values)
    return tuple(values), tuple(alphas), _result(
        "premise.fcf_consistency",
        ResultStatus.PASS if positive_years >= 4 else ResultStatus.FAIL,
        value=Decimal(positive_years),
    )


def _normalised_fcf(values: tuple[Decimal, ...]) -> Decimal:
    median = _median(values)
    average_three = sum(values[:3], Decimal("0")) / Decimal("3")
    if median == 0 and average_three != 0:
        return average_three
    if average_three == 0 and median != 0:
        return median
    return min(median, average_three)


def _leverage_gate(
    inputs: GeneralFCFInputs,
    f_norm: Decimal | None,
) -> tuple[Decimal | None, RuleResult]:
    fields = {
        "cash": inputs.cash,
        "liquid_assets": inputs.liquid_assets,
        "interest_bearing_debt": inputs.interest_bearing_debt,
        "f_norm": f_norm,
    }
    missing = tuple(key for key, value in fields.items() if value is None)
    if missing:
        return None, _result(
            "premise.leverage",
            ResultStatus.UNKNOWN,
            missing_fields=missing,
        )
    assert inputs.cash is not None
    assert inputs.liquid_assets is not None
    assert inputs.interest_bearing_debt is not None
    assert f_norm is not None
    net_debt = max(
        Decimal("0"),
        inputs.interest_bearing_debt - inputs.cash - inputs.liquid_assets,
    )
    if f_norm <= 0:
        return net_debt, _result("premise.leverage", ResultStatus.FAIL)
    ratio = net_debt / f_norm
    return net_debt, _result(
        "premise.leverage",
        ResultStatus.PASS if ratio <= Decimal("3") else ResultStatus.FAIL,
        value=ratio,
    )


def _quality_components(
    *,
    required: tuple[AnnualFinancialObservation, ...],
    annual_fcf: tuple[Decimal, ...],
    alphas: tuple[Decimal, ...],
    median_roe: Decimal | None,
    net_debt: Decimal | None,
    f_norm: Decimal | None,
) -> QualityComponents:
    assert median_roe is not None and net_debt is not None and f_norm is not None
    roe_score = _clamp((median_roe - Decimal("10")) / Decimal("10")) * Decimal("100")
    stability = Decimal(sum(value > 0 for value in annual_fcf)) / Decimal("5") * Decimal("100")
    profits = tuple(item.parent_net_profit for item in required[:5])
    ocfs = tuple(item.operating_cash_flow for item in required[:5])
    assert all(value is not None for value in profits)
    assert all(value is not None for value in ocfs)
    profit_sum = sum((value for value in profits if value is not None), Decimal("0"))
    cash_conversion_score: Decimal | None = None
    if profit_sum > 0:
        attributable_ocf = sum(
            (
                value * alpha
                for value, alpha in zip(ocfs, alphas)
                if value is not None
            ),
            Decimal("0"),
        )
        conversion = attributable_ocf / profit_sum
        cash_conversion_score = _clamp(conversion / Decimal("1.2")) * Decimal("100")
    balance_score = (
        Decimal("100")
        if net_debt == 0
        else _clamp(Decimal("1") - net_debt / (Decimal("3") * f_norm))
        * Decimal("100")
    )
    return QualityComponents(
        roe_score=roe_score,
        fcf_stability_score=stability,
        cash_conversion_score=cash_conversion_score,
        balance_score=balance_score,
    )


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    count = len(ordered)
    if not count:
        raise ValueError("median requires at least one value")
    midpoint = count // 2
    if count % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _clamp(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("1"), value))


def derive_ttm(
    *,
    fy_previous: Decimal | None,
    ytd_current: Decimal | None,
    ytd_previous_comparable: Decimal | None,
    fy_scope: str | None,
    current_scope: str | None,
    previous_scope: str | None,
    fy_currency: str | None,
    current_currency: str | None,
    previous_currency: str | None,
    current_months: int | None,
    previous_months: int | None,
) -> Decimal | None:
    """Return a strict comparable TTM value, or UNKNOWN as ``None``."""

    amounts = (fy_previous, ytd_current, ytd_previous_comparable)
    metadata = (
        fy_scope,
        current_scope,
        previous_scope,
        fy_currency,
        current_currency,
        previous_currency,
        current_months,
        previous_months,
    )
    if any(value is None for value in amounts + metadata):
        return None
    scopes = {str(fy_scope).upper(), str(current_scope).upper(), str(previous_scope).upper()}
    currencies = {
        str(fy_currency).upper(),
        str(current_currency).upper(),
        str(previous_currency).upper(),
    }
    if len(scopes) != 1 or len(currencies) != 1:
        return None
    if current_months != previous_months:
        return None
    if (
        isinstance(current_months, bool)
        or not isinstance(current_months, int)
        or not 1 <= current_months <= 12
    ):
        raise ValueError("current_months must be between 1 and 12")
    with calculation_context():
        assert fy_previous is not None
        assert ytd_current is not None
        assert ytd_previous_comparable is not None
        return (
            to_decimal(fy_previous)
            + to_decimal(ytd_current)
            - to_decimal(ytd_previous_comparable)
        )


__all__ = [
    "AnnualFinancialObservation",
    "GeneralFCFEvaluation",
    "GeneralFCFInputs",
    "QualityComponents",
    "QualityScoreResult",
    "QualityWeights",
    "combine_quality_scores",
    "derive_ttm",
    "evaluate_general_fcf",
]
