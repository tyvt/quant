from __future__ import annotations

from datetime import date
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from turtle_quant.storage.cli import (
    build_config_from_namespace,
    build_parser,
    build_source_descriptors,
    main,
)


class SyncCliTests(unittest.TestCase):
    def test_cli_builds_explicit_deterministic_config(self) -> None:
        parser = build_parser()
        namespace = parser.parse_args(
            [
                "--start-date",
                "2024-01-01",
                "--end-date",
                "2024-12-31",
                "--ingest-calendar-date",
                "2026-09-24",
                "--steps",
                "security_master,calendar",
                "--max-symbols",
                "0",
            ]
        )
        config = build_config_from_namespace(
            namespace,
            source_descriptors={"fixture": {"version": "1"}},
            shanghai_today=date(2030, 1, 1),
        )
        self.assertEqual(config.ingest_calendar_date, date(2026, 9, 24))
        self.assertEqual(config.steps, ("security_master", "calendar"))
        self.assertEqual(config.max_symbols, 0)

    def test_cli_fills_ingest_day_only_at_boundary(self) -> None:
        parser = build_parser()
        namespace = parser.parse_args(
            [
                "--start-date",
                "2024-01-01",
                "--end-date",
                "2024-12-31",
                "--steps",
                "security_master,calendar",
            ]
        )
        config = build_config_from_namespace(
            namespace,
            source_descriptors={},
            shanghai_today=date(2026, 9, 24),
        )
        self.assertEqual(config.ingest_calendar_date, date(2026, 9, 24))

    def test_zero_symbol_limit_rejects_per_security_steps(self) -> None:
        parser = build_parser()
        namespace = parser.parse_args(
            [
                "--start-date",
                "2024-01-01",
                "--end-date",
                "2024-12-31",
                "--max-symbols",
                "0",
            ]
        )
        with self.assertRaisesRegex(ValueError, "max-symbols"):
            build_config_from_namespace(
                namespace,
                source_descriptors={},
                shanghai_today=date(2026, 9, 24),
            )

    def test_source_descriptors_pin_code_and_chinabond_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            descriptors = build_source_descriptors(
                pybao_path=Path(temporary),
                steps=("security_master", "chinabond_10y"),
            )
        self.assertRegex(
            str(descriptors["turtle_quant"]["source_tree_sha256"]),
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            descriptors["chinabond"]["tenor"],
            "10Y",
        )

    def test_main_wires_adapters_and_prints_snapshot_id(self) -> None:
        output = StringIO()
        with (
            patch(
                "turtle_quant.storage.cli.StockDBLocalAdapter"
            ) as stockdb_class,
            patch(
                "turtle_quant.storage.cli.BaostockAdapter"
            ) as baostock_class,
            patch(
                "turtle_quant.storage.cli.ChinabondAdapter"
            ) as chinabond_class,
            patch(
                "turtle_quant.storage.cli.FoundationSyncRunner"
            ) as runner_class,
            redirect_stdout(output),
        ):
            baostock_class.return_value.__enter__.return_value = object()
            runner_class.return_value.run.return_value = (
                "snapshot-0123456789abcdef"
            )
            result = main(
                [
                    "--start-date",
                    "2024-01-01",
                    "--end-date",
                    "2024-01-02",
                    "--ingest-calendar-date",
                    "2026-09-24",
                    "--steps",
                    "security_master",
                    "--max-symbols",
                    "0",
                ]
            )
        self.assertEqual(result, 0)
        self.assertIn("snapshot-0123456789abcdef", output.getvalue())
        stockdb_class.assert_called_once()
        chinabond_class.assert_called_once()
        runner_class.return_value.run.assert_called_once_with(
            batch_id=None,
            resume=False,
        )


if __name__ == "__main__":
    unittest.main()
