"""Approved interim interpretation; not a production shares-data readiness test."""

from datetime import date
from unittest import TestCase

from turtle_quant.core.result import ResultStatus, RuleKind
from turtle_quant.core.share_capital_policy import (
    ShareCapitalEvidence,
    assess_share_capital_policy,
)
from turtle_quant.pit.parquet_strategy_inputs import ParquetSharesReader


AS_OF = date(2026, 9, 30)


def evidence(
    classes: tuple[str, ...] | None,
    treasury_shares: int | None,
    *,
    available_on: date | None = AS_OF,
    as_of: date = AS_OF,
    evidence_ref: str | None = "synthetic:share-structure",
) -> ShareCapitalEvidence:
    return ShareCapitalEvidence(
        security_id="sh.600001",
        as_of=as_of,
        ordinary_share_classes=classes,
        treasury_shares=treasury_shares,
        available_on=available_on,
        evidence_ref=evidence_ref,
    )


class ShareCapitalPolicyTests(TestCase):
    def test_multiclass_is_unknown_even_if_treasury_is_zero(self) -> None:
        for classes in (("A", "B"), ("A", "D", "H")):
            with self.subTest(classes=classes):
                result = assess_share_capital_policy(
                    evidence(classes, 0), security_id="sh.600001", as_of=AS_OF
                )
                self.assertEqual(result.kind, RuleKind.EVIDENCE)
                self.assertEqual(result.status, ResultStatus.UNKNOWN)
                self.assertEqual(result.missing_fields, ("S", "MV"))
                self.assertIn("multiple_ordinary_share_classes", result.notes)

    def test_single_class_nonzero_treasury_is_unknown(self) -> None:
        result = ParquetSharesReader.assess_structure(
            evidence(("A",), 1), security_id="sh.600001", as_of=AS_OF
        )
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertIn("treasury_shares_nonzero", result.notes)
        with self.assertRaisesRegex(NotImplementedError, "not ready"):
            ParquetSharesReader("storage/snapshots").shares_on("sh.600001", as_of=AS_OF)

    def test_clean_single_class_only_clears_policy_not_production_reader(self) -> None:
        result = assess_share_capital_policy(
            evidence(("A",), 0), security_id="sh.600001", as_of=AS_OF
        )
        self.assertEqual(result.status, ResultStatus.PASS)
        self.assertEqual(result.missing_fields, ())
        with self.assertRaisesRegex(NotImplementedError, "not ready"):
            ParquetSharesReader("storage/snapshots").shares_on("sh.600001", as_of=AS_OF)

    def test_unknown_or_late_evidence_never_means_zero_treasury(self) -> None:
        cases = (
            (evidence(("A",), None), "treasury_shares_unknown"),
            (evidence(("A",), 0, evidence_ref=None), "share_structure_evidence_missing"),
            (evidence(("A",), 0, available_on=None), "share_structure_availability_unknown"),
            (evidence(("A",), 0, available_on=date(2026, 10, 1)), "share_structure_future_available"),
            (evidence(("A",), 0, as_of=date(2026, 9, 29)), "share_structure_as_of_mismatch"),
        )
        for item, reason in cases:
            with self.subTest(reason=reason):
                result = assess_share_capital_policy(item, security_id="sh.600001", as_of=AS_OF)
                self.assertEqual(result.status, ResultStatus.UNKNOWN)
                self.assertIn(reason, result.notes)

    def test_missing_evidence_and_identity_mismatch(self) -> None:
        self.assertEqual(
            assess_share_capital_policy(None, security_id="sh.600001", as_of=AS_OF).status,
            ResultStatus.UNKNOWN,
        )
        with self.assertRaisesRegex(ValueError, "security_id mismatch"):
            assess_share_capital_policy(evidence(("A",), 0), security_id="sh.600002", as_of=AS_OF)

    def test_invalid_claim_shape_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "tuple"):
            ShareCapitalEvidence(
                "sh.600001", AS_OF, "AB", 0, AS_OF, "synthetic"
            )
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            ShareCapitalEvidence(
                "sh.600001", AS_OF, ("A",), True, AS_OF, "synthetic"
            )
