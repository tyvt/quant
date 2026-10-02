from datetime import date
from decimal import Decimal
import unittest

from turtle_quant.backtest.hashing import canonical_row_stream, logical_content_hash
from turtle_quant.backtest.manifest import StrategyRunManifest


D = Decimal
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


class LogicalContentHashTests(unittest.TestCase):
    def test_row_order_and_decimal_exponent_do_not_change_logical_hash(self) -> None:
        rows_a = (
            {"id": "b", "day": date(2025, 1, 2), "value": D("1.00")},
            {"id": "a", "day": date(2025, 1, 1), "value": D("2.0")},
        )
        rows_b = (
            {"id": "a", "day": date(2025, 1, 1), "value": D("2.00")},
            {"id": "b", "day": date(2025, 1, 2), "value": D("1.0")},
        )
        kwargs = {
            "schema_version": "orders-v1",
            "columns": ("id", "day", "value"),
            "primary_key": ("id",),
        }
        self.assertEqual(
            logical_content_hash(rows_a, **kwargs),
            logical_content_hash(rows_b, **kwargs),
        )
        self.assertEqual(
            canonical_row_stream(rows_a, **kwargs),
            canonical_row_stream(rows_b, **kwargs),
        )

    def test_logical_value_change_changes_hash_and_schema_is_strict(self) -> None:
        rows = ({"id": "a", "value": D("1")},)
        changed = ({"id": "a", "value": D("2")},)
        kwargs = {
            "schema_version": "nav-v1",
            "columns": ("id", "value"),
            "primary_key": ("id",),
        }
        self.assertNotEqual(
            logical_content_hash(rows, **kwargs),
            logical_content_hash(changed, **kwargs),
        )
        with self.assertRaises(ValueError):
            logical_content_hash(
                ({"id": "a"},),
                schema_version="nav-v1",
                columns=("id", "value"),
                primary_key=("id",),
            )


class StrategyManifestTests(unittest.TestCase):
    def _manifest(self, snapshots: tuple[str, ...], summary: dict[str, object]) -> StrategyRunManifest:
        return StrategyRunManifest(
            manifest_version="strategy-v1",
            run_id="synthetic-run",
            base_run_manifest_hash=HASH_A,
            strategy_id="GENERAL_FCF_MONTHLY_TOP20_V1",
            execution_policy_id="CN_A_OPEN_STRICT_V1",
            initial_capital=D("10000000.00"),
            signal_start=date(2025, 1, 31),
            signal_end=date(2025, 12, 31),
            snapshot_ids=snapshots,
            benchmark_id="H00985",
            benchmark_snapshot_id="benchmark:fixture",
            fee_schedule_id="fees:fixture",
            config_hash=HASH_B,
            code_version="test",
            rules_version="v1.3.0",
            completeness_summary=summary,
            order_content_hash=HASH_B,
            holding_content_hash=HASH_C,
            nav_content_hash=HASH_D,
        )

    def test_manifest_is_canonical_across_mapping_and_snapshot_order(self) -> None:
        first = self._manifest(("snap:b", "snap:a"), {"complete": True, "issues": 0})
        second = self._manifest(("snap:a", "snap:b"), {"issues": 0, "complete": True})
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(first.content_hash(), second.content_hash())
        self.assertEqual(
            StrategyRunManifest.from_dict(first.to_dict()).canonical_json(),
            first.canonical_json(),
        )

    def test_manifest_rejects_wrong_frozen_strategy_identity(self) -> None:
        with self.assertRaises(ValueError):
            StrategyRunManifest(
                manifest_version="strategy-v1",
                run_id="bad",
                base_run_manifest_hash=HASH_A,
                strategy_id="OTHER",
                execution_policy_id="CN_A_OPEN_STRICT_V1",
                initial_capital=D("1"),
                signal_start=date(2025, 1, 1),
                signal_end=date(2025, 1, 2),
                snapshot_ids=("snap:a",),
                benchmark_id="H00985",
                benchmark_snapshot_id="benchmark:fixture",
                fee_schedule_id="fees:fixture",
                config_hash=HASH_B,
                code_version="test",
                rules_version="v1.3.0",
                completeness_summary={"complete": True},
                order_content_hash=HASH_B,
                holding_content_hash=HASH_C,
                nav_content_hash=HASH_D,
            )


if __name__ == "__main__":
    unittest.main()
