from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from turtle_quant.pit.parquet_buybacks import ParquetBuybackReader
from turtle_quant.pit.parquet_dividends import ParquetDividendReader
from turtle_quant.pit.parquet_finance import ParquetFinanceReader
from turtle_quant.pit.parquet_financial_statements import (
    ParquetFinancialStatementsReader,
)


class ParquetFinanceGateTests(unittest.TestCase):
    def test_dedicated_readers_are_lexical_and_fail_with_domain_gate(self) -> None:
        day = date(2025, 1, 2)
        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            financials = ParquetFinancialStatementsReader(missing)
            dividends = ParquetDividendReader(missing)
            buybacks = ParquetBuybackReader(missing)
            self.assertFalse(missing.exists())

            reads = (
                (
                    lambda: financials.get_financial_record(
                        "sh.600000", day, as_of=day
                    ),
                    "financial statements",
                ),
                (
                    lambda: dividends.dividend_events(
                        "sh.600000", day, day, as_of=day
                    ),
                    "dividends",
                ),
                (
                    lambda: buybacks.buyback_events(
                        "sh.600000", day, day, as_of=day
                    ),
                    "buybacks",
                ),
            )
            for read, domain in reads:
                with self.subTest(domain=domain), self.assertRaisesRegex(
                    NotImplementedError, domain
                ):
                    read()

    def test_aggregate_facade_never_partially_opens(self) -> None:
        day = date(2025, 1, 2)
        reader = ParquetFinanceReader("missing")
        reads = (
            lambda: reader.get_financial_record("sh.600000", day, as_of=day),
            lambda: reader.dividend_events("sh.600000", day, day, as_of=day),
            lambda: reader.buyback_events("sh.600000", day, day, as_of=day),
        )
        for read in reads:
            with self.subTest(read=read), self.assertRaisesRegex(
                NotImplementedError,
                "all three dedicated finance readers",
            ):
                read()


if __name__ == "__main__":
    unittest.main()
