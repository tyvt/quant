from decimal import Decimal
import unittest

from turtle_quant.core.result import ResultStatus
from turtle_quant.evidence.validate import derive_unrestricted_cash


D = Decimal


class UnrestrictedCashEvidenceTests(unittest.TestCase):
    def test_explicit_zero_is_not_missing(self) -> None:
        explicit_zero = derive_unrestricted_cash(
            cash_and_equivalents=D("100"),
            restricted_cash=D("0"),
            cash_evidence_ref="balance-sheet:cash",
            restricted_cash_evidence_ref="note:restricted-cash-zero",
        )
        missing = derive_unrestricted_cash(
            cash_and_equivalents=D("100"),
            restricted_cash=None,
            cash_evidence_ref="balance-sheet:cash",
        )

        self.assertEqual(explicit_zero.status, ResultStatus.PASS)
        self.assertEqual(explicit_zero.value, D("100"))
        self.assertEqual(missing.status, ResultStatus.UNKNOWN)
        self.assertIsNone(missing.value)
        self.assertEqual(missing.missing_fields, ("restricted_cash",))

    def test_positive_restriction_is_subtracted(self) -> None:
        result = derive_unrestricted_cash(
            cash_and_equivalents=D("100"),
            restricted_cash=D("25"),
        )
        self.assertEqual(result.value, D("75"))

    def test_unknown_cash_remains_unknown(self) -> None:
        result = derive_unrestricted_cash(
            cash_and_equivalents=None,
            restricted_cash=D("0"),
        )
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.missing_fields, ("cash_and_equivalents",))

    def test_illegal_restricted_cash_is_a_hard_input_error(self) -> None:
        with self.assertRaises(ValueError):
            derive_unrestricted_cash(D("100"), D("-1"))
        with self.assertRaises(ValueError):
            derive_unrestricted_cash(D("100"), D("101"))


if __name__ == "__main__":
    unittest.main()
