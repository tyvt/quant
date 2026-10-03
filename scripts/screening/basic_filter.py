"""Reuse the approved universe screen; never replace missing inputs with defaults."""

from turtle_quant.strategy.selection import UniverseInput, evaluate_universe_security
from turtle_quant.core.types import calculation_context
from scripts.screening.contracts import plain


def basic_filter(inputs: UniverseInput | None) -> dict:
    if inputs is None:
        return {"status": "NEEDS_REVIEW", "reasons": ["basic_inputs_missing"],
                "valid_trading_amount_days": None, "median_trading_amount": None,
                "evidence_refs": []}
    with calculation_context():
        result = plain(evaluate_universe_security(inputs))
    result.pop("security_id")
    refs = {item.evidence_ref for item in inputs.liquidity_days if item.evidence_ref}
    if inputs.share_capital_evidence and inputs.share_capital_evidence.evidence_ref:
        refs.add(inputs.share_capital_evidence.evidence_ref)
    result["evidence_refs"] = sorted(refs)
    return result
