from __future__ import annotations

from decimal import Decimal
import unittest

from turtle_quant.adapters.security import (
    is_main_board_security,
    normalize_security_id,
)
from turtle_quant.storage.quality import (
    QualityGateError,
    validate_raw_daily_rows,
)


class SecurityNormalizationTests(unittest.TestCase):
    def test_normalizes_each_vendor_without_guessing(self) -> None:
        stockdb = normalize_security_id("600000", source="stockdb")
        baostock = normalize_security_id("sh.600000", source="baostock")
        akshare = normalize_security_id("000001", source="akshare")

        self.assertEqual(stockdb.security_id, "sh.600000")
        self.assertEqual(baostock.security_id, "sh.600000")
        self.assertEqual(akshare.security_id, "sz.000001")
        self.assertEqual(stockdb.exchange, "sh")
        self.assertEqual(akshare.exchange, "sz")
        self.assertEqual(stockdb.normalization_version, "cn_equity_v1")

    def test_rejects_ambiguous_or_non_equity_code(self) -> None:
        with self.assertRaises(ValueError):
            normalize_security_id("123456", source="akshare")
        with self.assertRaises(ValueError):
            normalize_security_id("", source="stockdb")

    def test_main_board_filter_excludes_b_share_and_growth_boards(self) -> None:
        self.assertTrue(is_main_board_security("sh.600000"))
        self.assertTrue(is_main_board_security("sz.000001"))
        self.assertTrue(is_main_board_security("sz.002001"))
        self.assertFalse(is_main_board_security("sh.688001"))
        self.assertFalse(is_main_board_security("sz.300001"))
        self.assertFalse(is_main_board_security("sh.900901"))
        self.assertFalse(is_main_board_security("sz.200001"))


class RawDailyQualityTests(unittest.TestCase):
    def _row(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "security_id": "sh.600000",
            "trade_date": "2026-09-23",
            "open": Decimal("10"),
            "high": Decimal("11"),
            "low": Decimal("9"),
            "close": Decimal("10.5"),
            "volume": Decimal("1000"),
            "amount": Decimal("10500"),
            "paused": False,
            "adjust_type": "RAW",
            "schema_version": 1,
            "normalization_version": "market_raw_v1",
            "source_name": "fixture",
            "source_row_hash": "a" * 64,
            "evidence_ref": "fixture:bar:1",
        }
        row.update(overrides)
        return row

    def test_accepts_raw_finite_unique_rows(self) -> None:
        result = validate_raw_daily_rows([self._row()])
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.blocking_issues, ())

    def test_rejects_adjusted_prices(self) -> None:
        with self.assertRaisesRegex(QualityGateError, "RAW"):
            validate_raw_daily_rows([self._row(adjust_type="QFQ")])

    def test_rejects_duplicate_primary_key(self) -> None:
        row = self._row()
        with self.assertRaisesRegex(QualityGateError, "duplicate"):
            validate_raw_daily_rows([row, dict(row)])

    def test_rejects_non_finite_decimal(self) -> None:
        with self.assertRaisesRegex(QualityGateError, "finite"):
            validate_raw_daily_rows([self._row(close=Decimal("NaN"))])

    def test_flags_inconsistent_ohlc_without_silently_fixing_it(self) -> None:
        result = validate_raw_daily_rows(
            [self._row(high=Decimal("10"), close=Decimal("10.5"))]
        )
        self.assertEqual(len(result.warning_issues), 1)
        self.assertIn("ohlc", result.warning_issues[0])

    def test_accepts_explicit_zero_ohlc_nontrading_placeholder(self) -> None:
        result = validate_raw_daily_rows(
            [
                self._row(
                    open=Decimal("0"),
                    high=Decimal("0"),
                    low=Decimal("0"),
                    close=Decimal("69.78"),
                    volume=Decimal("0"),
                    amount=Decimal("0"),
                    paused=True,
                )
            ]
        )
        self.assertIn("zero_ohlc_placeholder", result.warning_issues[0])

    def test_rejects_zero_price_when_not_a_nontrading_placeholder(self) -> None:
        with self.assertRaisesRegex(QualityGateError, "positive"):
            validate_raw_daily_rows(
                [
                    self._row(
                        open=Decimal("0"),
                        volume=Decimal("100"),
                        paused=False,
                    )
                ]
            )


if __name__ == "__main__":
    unittest.main()
