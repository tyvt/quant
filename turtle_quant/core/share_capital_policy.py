"""Fail-closed, evidence-only interpretation of ambiguous historical shares.

This pure policy gate does not read snapshots or certify PIT source coverage.
Production shares remain unavailable until ParquetSharesReader is independently ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from turtle_quant.core.result import ResultStatus, RuleKind, RuleResult


_SECURITY_ID = re.compile(r"^(sh|sz)\.\d{6}$")


@dataclass(frozen=True)
class ShareCapitalEvidence:
    """An upstream PIT-verified structure claim, not a production share count.

    ``available_on`` is the earliest *verified safe* date for using the claim,
    not an inferred date from a PDF URL or issuer signature. A production
    adapter must also verify precise source availability and revision coverage;
    this class deliberately cannot do that work on its own.
    """

    security_id: str
    as_of: date
    ordinary_share_classes: tuple[str, ...] | None
    treasury_shares: int | None
    available_on: date | None
    evidence_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.security_id, str) or not _SECURITY_ID.fullmatch(self.security_id):
            raise ValueError("security_id must use canonical sh.600000 form")
        if type(self.as_of) is not date:
            raise ValueError("as_of must be a date")
        if self.available_on is not None and type(self.available_on) is not date:
            raise ValueError("available_on must be a date or None")
        if self.ordinary_share_classes is not None:
            if not isinstance(self.ordinary_share_classes, tuple):
                raise ValueError("ordinary_share_classes must be a tuple or None")
            classes = tuple(self.ordinary_share_classes)
            if any(not isinstance(item, str) or not item or item != item.upper() for item in classes):
                raise ValueError("ordinary_share_classes must contain uppercase class names")
            if len(set(classes)) != len(classes):
                raise ValueError("ordinary_share_classes must not contain duplicates")
            object.__setattr__(self, "ordinary_share_classes", classes)
        if self.treasury_shares is not None and (
            type(self.treasury_shares) is not int or self.treasury_shares < 0
        ):
            raise ValueError("treasury_shares must be a non-negative integer or None")
        if self.evidence_ref is not None and (
            not isinstance(self.evidence_ref, str) or not self.evidence_ref
        ):
            raise ValueError("evidence_ref must be non-empty or None")


def assess_share_capital_policy(
    evidence: ShareCapitalEvidence | None,
    *,
    security_id: str,
    as_of: date,
) -> RuleResult:
    """Mark ambiguous S/MV UNKNOWN; PASS only means no *additional* policy block.

    This does not make shares known or license a real market value calculation.
    Missing/late evidence is UNKNOWN, never a zero treasury balance. The upstream
    Reader remains responsible for exact available_at and full event coverage.
    """

    if not isinstance(security_id, str) or not _SECURITY_ID.fullmatch(security_id):
        raise ValueError("security_id must use canonical sh.600000 form")
    if type(as_of) is not date:
        raise ValueError("as_of must be a date")
    if evidence is not None and not isinstance(evidence, ShareCapitalEvidence):
        raise ValueError("evidence must be ShareCapitalEvidence or None")
    if evidence is not None and evidence.security_id != security_id:
        raise ValueError("share-capital evidence security_id mismatch")

    reasons: list[str] = []
    refs: tuple[str, ...] = ()
    if evidence is None:
        reasons.append("share_capital_evidence_missing")
    else:
        if evidence.as_of != as_of:
            reasons.append("share_structure_as_of_mismatch")
        if evidence.available_on is None:
            reasons.append("share_structure_availability_unknown")
        elif evidence.available_on > as_of:
            reasons.append("share_structure_future_available")
        if evidence.evidence_ref is None:
            reasons.append("share_structure_evidence_missing")
        else:
            refs = (evidence.evidence_ref,)
        classes = evidence.ordinary_share_classes
        if not classes:
            reasons.append("ordinary_share_classes_unknown")
        elif "A" not in classes:
            reasons.append("a_share_class_missing")
        elif len(classes) > 1:
            reasons.append("multiple_ordinary_share_classes")
        if evidence.treasury_shares is None:
            reasons.append("treasury_shares_unknown")
        elif evidence.treasury_shares > 0:
            reasons.append("treasury_shares_nonzero")

    return RuleResult(
        rule_id="shares.capital_structure_policy",
        kind=RuleKind.EVIDENCE,
        status=ResultStatus.UNKNOWN if reasons else ResultStatus.PASS,
        notes=tuple(reasons),
        missing_fields=("S", "MV") if reasons else (),
        evidence_refs=refs,
    )


__all__ = ["ShareCapitalEvidence", "assess_share_capital_policy"]
