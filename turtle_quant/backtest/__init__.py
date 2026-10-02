"""Deterministic synthetic backtest primitives authorized by v1.3.0."""

from .execution import (
    ExecutionAttempt,
    FeeBreakdown,
    FeeRate,
    FeeSchedule,
    Fill,
    ParticipationDay,
    ParticipationResult,
    Tradeability,
    attempt_order,
    calculate_participation_limit,
    create_fill,
)
from .hashing import canonical_row_stream, logical_content_hash
from .manifest import StrategyRunManifest
from .metrics import (
    BenchmarkPoint,
    NavPoint,
    PerformanceResult,
    TradeNotional,
    calculate_performance,
)
from .engine import (
    BacktestEngineResult,
    ExecutionMarket,
    ExecutionSession,
    HoldingSnapshot,
    OrderOutcome,
    run_order_book,
)

__all__ = [
    "ExecutionAttempt",
    "FeeBreakdown",
    "FeeRate",
    "FeeSchedule",
    "Fill",
    "ParticipationDay",
    "ParticipationResult",
    "Tradeability",
    "attempt_order",
    "calculate_participation_limit",
    "create_fill",
    "canonical_row_stream",
    "logical_content_hash",
    "StrategyRunManifest",
    "BenchmarkPoint",
    "NavPoint",
    "PerformanceResult",
    "TradeNotional",
    "calculate_performance",
    "BacktestEngineResult",
    "ExecutionMarket",
    "ExecutionSession",
    "HoldingSnapshot",
    "OrderOutcome",
    "run_order_book",
]
