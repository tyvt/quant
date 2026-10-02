from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from turtle_quant.pit import ParquetPITReader


class UnreadyParquetPITReaderTests(unittest.TestCase):
    def test_construction_is_lexical_and_does_not_require_a_snapshot(self) -> None:
        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "snapshot-does-not-exist"
            reader = ParquetPITReader(missing)

            self.assertEqual(reader.snapshot_root, missing)
            self.assertFalse(missing.exists())

    def test_every_declared_read_fails_explicitly(self) -> None:
        reader = ParquetPITReader("unused-snapshot-root")
        day = date(2025, 1, 2)
        reads = (
            lambda: reader.get_financial_record("600000.SH", day, as_of=day),
            lambda: reader.security_ids_as_of(day),
            lambda: reader.adjustment_factor_series(
                "600000.SH", day, day, as_of=day
            ),
            lambda: reader.price_bars("600000.SH", day, day, as_of=day),
            lambda: reader.value_on("CGB10Y", as_of=day),
        )

        for read in reads:
            with self.subTest(read=read), self.assertRaisesRegex(
                NotImplementedError,
                r"pit\.parquet is not ready under RULE_SPEC\.md",
            ):
                read()
