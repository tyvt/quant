from datetime import date
from decimal import Decimal
import unittest

from turtle_quant.core.pit import (
    InMemoryAttributeReader,
    PointInTimeAttribute,
)
from turtle_quant.strategy.config import GeneralFCFStrategyConfig


D = Decimal


class StrategyPointInTimeTests(unittest.TestCase):
    def test_future_effective_or_future_available_attributes_are_invisible(self) -> None:
        reader = InMemoryAttributeReader(
            (
                PointInTimeAttribute(
                    "sh.600001", "industry", date(2025, 1, 1), date(2025, 1, 2), 0, "GENERAL_FCF", "industry:old"
                ),
                PointInTimeAttribute(
                    "sh.600001", "industry", date(2025, 3, 1), date(2025, 2, 1), 0, "BANK", "industry:future-effective"
                ),
                PointInTimeAttribute(
                    "sh.600001", "shares", date(2025, 1, 1), date(2025, 1, 2), 0, D("1000"), "shares:old"
                ),
                PointInTimeAttribute(
                    "sh.600001", "shares", date(2025, 1, 1), date(2025, 2, 20), 1, D("2000"), "shares:future-revision"
                ),
                PointInTimeAttribute(
                    "sh.600001", "risk_status", date(2025, 3, 1), date(2025, 2, 1), 0, "ST", "status:future"
                ),
            )
        )
        as_of = date(2025, 2, 15)
        self.assertEqual(reader.value_on("sh.600001", "industry", as_of=as_of).value, "GENERAL_FCF")
        self.assertEqual(reader.value_on("sh.600001", "shares", as_of=as_of).value, D("1000"))
        self.assertIsNone(reader.value_on("sh.600001", "risk_status", as_of=as_of))

    def test_post_as_of_records_cannot_change_prior_selection(self) -> None:
        old = PointInTimeAttribute(
            "sh.600001", "shares", date(2025, 1, 1), date(2025, 1, 2), 0, D("1000"), "shares:old"
        )
        future = PointInTimeAttribute(
            "sh.600001", "shares", date(2025, 1, 1), date(2025, 3, 1), 1, D("2000"), "shares:new"
        )
        before = InMemoryAttributeReader((old,)).value_on(
            "sh.600001", "shares", as_of=date(2025, 2, 1)
        )
        after_dataset_growth = InMemoryAttributeReader((old, future)).value_on(
            "sh.600001", "shares", as_of=date(2025, 2, 1)
        )
        self.assertEqual(before, after_dataset_growth)


class StrategyConfigTests(unittest.TestCase):
    def test_frozen_defaults_and_hash_are_deterministic(self) -> None:
        first = GeneralFCFStrategyConfig()
        second = GeneralFCFStrategyConfig(initial_capital=D("10000000.0"))
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(first.content_hash(), second.content_hash())
        self.assertEqual(first.market_cap_min, D("5000000000"))
        self.assertEqual(first.participation_rate, D("0.05"))

    def test_rule_parameter_change_requires_a_new_rules_version(self) -> None:
        with self.assertRaises(ValueError):
            GeneralFCFStrategyConfig(market_cap_min=D("4000000000"))
        with self.assertRaises(ValueError):
            GeneralFCFStrategyConfig(rules_version="v1.3.1")

    def test_alternate_initial_capital_is_allowed_but_changes_config_hash(self) -> None:
        standard = GeneralFCFStrategyConfig()
        alternate = GeneralFCFStrategyConfig(initial_capital=D("20000000"))
        self.assertNotEqual(standard.content_hash(), alternate.content_hash())


if __name__ == "__main__":
    unittest.main()
