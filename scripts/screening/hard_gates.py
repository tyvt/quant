"""One call to the existing six-gate engine; presentation order is not short-circuiting."""

from turtle_quant.core.result import ResultStatus, RuleKind, RuleResult
from turtle_quant.premise.general_fcf import GeneralFCFInputs, evaluate_general_fcf
from scripts.screening.contracts import plain


GATE_ORDER = (
    "premise.profile_supported", "premise.positive_equity",
    "premise.statement_integrity", "premise.roe_5y",
    "premise.fcf_consistency", "premise.leverage",
)


def hard_gates(inputs: GeneralFCFInputs | None) -> list[dict]:
    if inputs is None:
        results = tuple(RuleResult(rule_id, RuleKind.HARD_GATE, ResultStatus.UNKNOWN,
                                   notes=("financial_inputs_missing",),
                                   missing_fields=("financial_inputs",))
                        for rule_id in GATE_ORDER)
    else:
        results = evaluate_general_fcf(inputs).hard_gates
    by_id = {item.rule_id: item for item in results}
    if len(results) != len(GATE_ORDER) or set(by_id) != set(GATE_ORDER):
        raise ValueError("six-gate contract drift")
    # Do not expose the engine's quality scores, valuation or five-year FCF arrays.
    return [plain(by_id[rule_id]) for rule_id in GATE_ORDER]
