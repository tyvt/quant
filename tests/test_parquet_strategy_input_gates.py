from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from turtle_quant.pit.parquet_strategy_inputs import (
    ParquetBenchmarkReader,
    ParquetCorporateActionsReader,
    ParquetCostScheduleReader,
    ParquetIndustryReader,
    ParquetSecurityStatusReader,
    ParquetSharesReader,
    ParquetTradeabilityReader,
)


class StrategyInputGateTests(unittest.TestCase):
    def test_each_production_domain_fails_independently_without_io(self) -> None:
        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            day = date(2025, 1, 2)
            reads = (
                (lambda: ParquetIndustryReader(missing).industry_on("sh.600001", as_of=day), "industry"),
                (lambda: ParquetSharesReader(missing).shares_on("sh.600001", as_of=day), "historical shares"),
                (lambda: ParquetSecurityStatusReader(missing).status_on("sh.600001", as_of=day), "security status"),
                (lambda: ParquetTradeabilityReader(missing).tradeability_on("sh.600001", day, as_of=day), "tradeability"),
                (lambda: ParquetCorporateActionsReader(missing).events("sh.600001", day, day, as_of=day), "corporate actions"),
                (lambda: ParquetCostScheduleReader(missing).rate_on(day), "historical cost"),
            )
            for read, label in reads:
                with self.subTest(domain=label), self.assertRaisesRegex(NotImplementedError, label):
                    read()
            self.assertFalse(missing.exists())

    def test_benchmark_requires_an_explicit_verified_snapshot(self) -> None:
        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            with self.assertRaisesRegex(ValueError, "published snapshot is missing"):
                ParquetBenchmarkReader(missing, "snapshot-" + "0" * 16)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
