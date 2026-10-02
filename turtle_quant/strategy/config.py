"""Frozen v1.3.0 strategy configuration and deterministic identity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json

from turtle_quant.core.types import to_decimal


@dataclass(frozen=True)
class GeneralFCFStrategyConfig:
    rules_version: str = "v1.3.0"
    strategy_id: str = "GENERAL_FCF_MONTHLY_TOP20_V1"
    execution_policy_id: str = "CN_A_OPEN_STRICT_V1"
    initial_capital: Decimal = Decimal("10000000")
    market_cap_min: Decimal = Decimal("5000000000")
    liquidity_lookback_days: int = 60
    liquidity_min_complete_days: int = 50
    liquidity_median_min: Decimal = Decimal("20000000")
    market_position_lookback_days: int = 756
    market_position_min_prices: int = 504
    top_n: int = 20
    max_weight: Decimal = Decimal("0.05")
    participation_lookback_days: int = 20
    participation_rate: Decimal = Decimal("0.05")
    max_execution_days: int = 5
    buy_lot_size: int = 100
    slippage_bps: Decimal = Decimal("10")
    default_brokerage_bps: Decimal = Decimal("3")
    default_minimum_commission: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        frozen = {
            "rules_version": "v1.3.0",
            "strategy_id": "GENERAL_FCF_MONTHLY_TOP20_V1",
            "execution_policy_id": "CN_A_OPEN_STRICT_V1",
            "market_cap_min": Decimal("5000000000"),
            "liquidity_lookback_days": 60,
            "liquidity_min_complete_days": 50,
            "liquidity_median_min": Decimal("20000000"),
            "market_position_lookback_days": 756,
            "market_position_min_prices": 504,
            "top_n": 20,
            "max_weight": Decimal("0.05"),
            "participation_lookback_days": 20,
            "participation_rate": Decimal("0.05"),
            "max_execution_days": 5,
            "buy_lot_size": 100,
            "slippage_bps": Decimal("10"),
            "default_brokerage_bps": Decimal("3"),
            "default_minimum_commission": Decimal("5"),
        }
        decimal_fields = {
            "initial_capital",
            "market_cap_min",
            "liquidity_median_min",
            "max_weight",
            "participation_rate",
            "slippage_bps",
            "default_brokerage_bps",
            "default_minimum_commission",
        }
        for field_name in decimal_fields:
            object.__setattr__(self, field_name, to_decimal(getattr(self, field_name)))
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        for field_name, expected in frozen.items():
            if getattr(self, field_name) != expected:
                raise ValueError(
                    f"{field_name} is frozen by RULE_SPEC v1.3.0; use a new rules version"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "rules_version": self.rules_version,
            "strategy_id": self.strategy_id,
            "execution_policy_id": self.execution_policy_id,
            "initial_capital": _decimal_text(self.initial_capital),
            "market_cap_min": _decimal_text(self.market_cap_min),
            "liquidity_lookback_days": self.liquidity_lookback_days,
            "liquidity_min_complete_days": self.liquidity_min_complete_days,
            "liquidity_median_min": _decimal_text(self.liquidity_median_min),
            "market_position_lookback_days": self.market_position_lookback_days,
            "market_position_min_prices": self.market_position_min_prices,
            "top_n": self.top_n,
            "max_weight": _decimal_text(self.max_weight),
            "participation_lookback_days": self.participation_lookback_days,
            "participation_rate": _decimal_text(self.participation_rate),
            "max_execution_days": self.max_execution_days,
            "buy_lot_size": self.buy_lot_size,
            "slippage_bps": _decimal_text(self.slippage_bps),
            "default_brokerage_bps": _decimal_text(self.default_brokerage_bps),
            "default_minimum_commission": _decimal_text(
                self.default_minimum_commission
            ),
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _decimal_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


__all__ = ["GeneralFCFStrategyConfig"]
