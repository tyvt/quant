"""Technical-only integration: synthetic strategy inputs and published H00985."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from turtle_quant.backtest.engine import ExecutionMarket, ExecutionSession, run_order_book
from turtle_quant.backtest.execution import (
    FeeRate,
    FeeSchedule,
    ParticipationDay,
    Tradeability,
    calculate_participation_limit,
)
from turtle_quant.backtest.manifest import StrategyRunManifest
from turtle_quant.backtest.metrics import (
    BenchmarkPoint,
    NavPoint,
    TradeNotional,
    calculate_performance,
)
from turtle_quant.backtest.portfolio import PortfolioState
from turtle_quant.core.manifest import RunManifest
from turtle_quant.core.types import UnitRatio
from turtle_quant.pipeline.decision import DecisionKind, decide
from turtle_quant.pit.parquet_benchmark import ParquetBenchmarkReader
from turtle_quant.premise.general_fcf import (
    AnnualFinancialObservation,
    GeneralFCFInputs,
    evaluate_general_fcf,
)
from turtle_quant.storage.benchmark import expected_benchmark_dates
from turtle_quant.storage.verification import verify_published_domain
from turtle_quant.strategy.config import GeneralFCFStrategyConfig
from turtle_quant.strategy.orders import plan_rebalance
from turtle_quant.strategy.selection import (
    CandidateMetrics,
    LiquidityDay,
    SecurityAssessment,
    UniverseInput,
    UniverseStatus,
    build_monthly_selection,
    evaluate_universe_security,
)
from turtle_quant.valuation.absolute import AbsoluteValuationInputs, calculate_absolute_valuation
from turtle_quant.valuation.lookthrough import LookthroughInputs, calculate_lookthrough


D = Decimal
ROOT = Path(__file__).resolve().parents[1] / "storage"
SNAPSHOT_ID = "snapshot-9b72a2666190542a"
CLEAN_SNAPSHOT_ID = "snapshot-d9fa4c6d8933fe39"
SIGNAL = date(2025, 1, 27)
END = date(2025, 3, 31)
MARKET_VALUE = D("6000000000")


def _annual(year: int) -> AnnualFinancialObservation:
    return AnnualFinancialObservation(
        fiscal_year=year,
        available_at=date(year + 1, 4, 30),
        attributable_equity_end=D("10000000000"),
        total_equity_end=D("10000000000"),
        minority_interest_end=D("0"),
        parent_net_profit=D("1500000000"),
        operating_cash_flow=D("2000000000"),
        capex=D("500000000"),
        lease_cash_not_already_deducted=D("100000000"),
        currency="CNY",
        statement_scope="CONSOLIDATED",
        traceable=True,
        evidence_refs=(f"synthetic-annual:{year}",),
    )


def _assessment(
    security_id: str,
    *,
    market_value: Decimal = MARKET_VALUE,
    profile: str = "GENERAL_FCF",
    missing_oldest: bool = False,
) -> SecurityAssessment:
    years = range(2019 if missing_oldest else 2018, 2024)
    premise = evaluate_general_fcf(GeneralFCFInputs(
        as_of=SIGNAL,
        industry_profile=profile,
        statements_comparable=True,
        latest_audit_unmodified=True,
        going_concern_uncertainty=False,
        latest_equity=D("10000000000"),
        annual_observations=tuple(_annual(year) for year in years),
        cash=D("3000000000"),
        liquid_assets=D("1000000000"),
        interest_bearing_debt=D("2000000000"),
    ))
    absolute = calculate_absolute_valuation(AbsoluteValuationInputs(
        price=D("10"),
        market_value=market_value,
        net_cash=D("2000000000"),
        annual_fcf_newest_to_oldest=premise.annual_fcf_newest_to_oldest,
        latest_annualized_fcf=premise.f_norm,
        previous_annualized_fcf=premise.f_norm,
    ))
    lookthrough = calculate_lookthrough(LookthroughInputs(
        capacity=premise.f_norm,
        dividends=D("500000000") if premise.f_norm is not None else None,
        qualified_buybacks=D("100000000") if premise.f_norm is not None else None,
        market_value=market_value,
        price=D("10"),
        required_return_pct=D("5"),
        tax_rate=UnitRatio("0.2"),
    ))
    decision = decide(
        premise.hard_gates,
        coverage6=absolute.coverage.get(6),
        gg_pct=lookthrough.gg_pct,
        required_return_pct=D("5"),
        score_coverage=premise.quality.score_coverage,
        profile_status=premise.gate("premise.profile_supported").status,
    )
    metrics = None
    if decision.kind is DecisionKind.CANDIDATE:
        assert premise.quality.quality_score is not None
        assert absolute.coverage.get(6) is not None
        assert lookthrough.gg_pct is not None
        metrics = CandidateMetrics(
            quality_score=premise.quality.quality_score,
            coverage6=absolute.coverage[6],
            gg_margin_pct=lookthrough.gg_pct - D("5"),
            market_position_score=D("70"),  # synthetic market-position fixture
        )
    return SecurityAssessment(
        security_id=security_id,
        decision_kind=decision.kind,
        reasons=decision.reasons,
        missing_fields=tuple(sorted({
            field for gate in premise.hard_gates for field in gate.missing_fields
        } | set(absolute.missing_fields) | set(lookthrough.missing_fields))),
        quality_flags=("SYNTHETIC_FIXTURE_ONLY",),
        hard_gate_statuses=tuple(gate.status.value for gate in premise.hard_gates),
        score_statuses=("COMPLETE" if premise.quality.score_coverage == 1 else "UNKNOWN",),
        evidence_statuses=("SYNTHETIC_ONLY",),
        metrics=metrics,
    )


def _fees() -> FeeSchedule:
    return FeeSchedule(
        "synthetic-fee-schedule",
        (FeeRate(date(2020, 1, 1), D("3"), D("5"), D("0"), D("0"), D("0")),),
    )


class BenchmarkTechnicalIntegrationTests(TestCase):
    """No real securities, financials, orders, yields or publishable performance."""

    def _reader(self, snapshot_id: str = SNAPSHOT_ID) -> ParquetBenchmarkReader:
        if not (ROOT / "snapshots" / snapshot_id / "meta.json").is_file():
            self.skipTest(f"local immutable benchmark snapshot {snapshot_id} is unavailable")
        return ParquetBenchmarkReader(ROOT, snapshot_id)

    def test_synthetic_strategy_real_benchmark_pipeline_is_deterministic(self) -> None:
        reader = self._reader()
        config = GeneralFCFStrategyConfig()
        history = reader.values("H00985", date(2024, 10, 1), END)
        dates = tuple(item.trade_date for item in history)
        period = tuple(item for item in history if SIGNAL <= item.trade_date <= END)
        period_dates = tuple(item.trade_date for item in period)
        self.assertEqual(period_dates, expected_benchmark_dates(
            ROOT, reader.calendar_snapshot_id, SIGNAL, END
        ))
        self.assertGreater(len(period), 3)
        self.assertEqual(period_dates[0], SIGNAL)
        self.assertEqual(period_dates[-1], END)

        liquidity_dates = tuple(day for day in dates if day <= SIGNAL)[-60:]
        self.assertEqual(len(liquidity_dates), 60)
        universe = evaluate_universe_security(UniverseInput(
            security_id="sh.600001",
            as_of=SIGNAL,
            expected_liquidity_dates=liquidity_dates,
            main_board_a_share=True,
            listing_trading_days=600,
            industry_profile="GENERAL_FCF",
            eligible_security_status=True,
            market_value=MARKET_VALUE,
            liquidity_days=tuple(LiquidityDay(
                day, D("30000000"), True, f"synthetic-amount:{day.isoformat()}"
            ) for day in liquidity_dates),
            stage_a_coverage_complete=True,
            shares_known=True,  # synthetic historical-share fixture, not a ready data domain
        ))
        self.assertEqual(universe.status, UniverseStatus.ELIGIBLE)

        candidate = _assessment("sh.600001")
        rejected = _assessment("sh.600002", market_value=D("20000000000"))
        unsupported = _assessment("sh.600003", profile="BANK")
        review = _assessment("sh.600004", missing_oldest=True)
        self.assertEqual(
            tuple(item.decision_kind for item in (candidate, rejected, unsupported, review)),
            (DecisionKind.CANDIDATE, DecisionKind.REJECTED,
             DecisionKind.NOT_SUPPORTED, DecisionKind.NEEDS_REVIEW),
        )
        diagnostic = build_monthly_selection((candidate, rejected, unsupported, review))
        self.assertTrue(diagnostic.diagnostic_only)
        self.assertFalse(diagnostic.official_selection)
        self.assertEqual(diagnostic.ranked_candidates, ())
        self.assertEqual(dict(diagnostic.target_weights), {})
        forbidden = {"rank", "top_n", "target_weight", "order_plan", "nav"}
        self.assertTrue(all(forbidden.isdisjoint(row.to_dict()) for row in diagnostic.diagnostics))
        first_execution_date = period_dates[1]
        with self.assertRaisesRegex(ValueError, "official"):
            plan_rebalance(
                diagnostic, signal_date=SIGNAL,
                first_execution_date=first_execution_date,
                signal_nav=config.initial_capital,
                signal_raw_closes={"sh.600001": D("10")},
                current_quantities={}, market_coverage_end=END,
            )

        # Removing the deliberately incomplete synthetic security exercises the
        # pure order/portfolio path; it does not make the run production-eligible.
        selection = build_monthly_selection((candidate, rejected, unsupported))
        self.assertTrue(selection.official_selection)  # internal synthetic-only API state
        orders = plan_rebalance(
            selection, signal_date=SIGNAL,
            first_execution_date=first_execution_date,
            signal_nav=config.initial_capital,
            signal_raw_closes={"sh.600001": D("10")},
            current_quantities={}, market_coverage_end=END,
        )
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].first_execution_date, first_execution_date)

        tradeability = Tradeability(True, True, False, False, False, "synthetic-tradeability")
        sessions = []
        for index, day in enumerate(period_dates):
            previous = dates[dates.index(day) - 20:dates.index(day)]
            self.assertEqual(len(previous), 20)
            participation = calculate_participation_limit(
                tuple(ParticipationDay(
                    prior, D("30000000"), False,
                    f"synthetic-amount:{prior.isoformat()}"
                ) for prior in previous),
                expected_trading_dates=previous,
            )
            price = D("10") + D(index) * D("0.02")
            sessions.append(ExecutionSession(day, {"sh.600001": ExecutionMarket(
                security_id="sh.600001",
                raw_open=price,
                raw_close=price + (D("0.06") if index % 3 == 0 else D("-0.03")),
                close_evidence_ref=f"synthetic-close:{day.isoformat()}",
                tradeability=tradeability,
                participation=participation,
            )}))

        initial = PortfolioState(config.initial_capital, ())
        first = run_order_book(initial, orders, tuple(sessions),
                               fee_schedule=_fees(), expected_trading_dates=period_dates)
        second = run_order_book(initial, orders, tuple(sessions),
                                fee_schedule=_fees(), expected_trading_dates=period_dates)
        self.assertTrue(first.complete)
        self.assertEqual(first.logical_hashes(), second.logical_hashes())
        self.assertEqual(tuple(item.trade_date for item in first.nav_points), period_dates)
        self.assertEqual(len(first.fills), 1)
        self.assertEqual(first.fills[0].execution_date, first_execution_date)

        benchmark = tuple(BenchmarkPoint(item.trade_date, item.close) for item in period)
        risk_free = {day: D("2") for day in period_dates[1:]}  # synthetic, not a yield Reader
        trades = tuple(TradeNotional(item.execution_date, item.notional) for item in first.fills)
        performance = calculate_performance(
            first.nav_points, benchmark_points=benchmark,
            risk_free_yields_pct=risk_free, trades=trades,
            expected_trading_dates=period_dates, calendar_complete_through=END,
        )
        self.assertTrue(performance.complete)
        for field in ("cagr", "annualized_volatility", "sharpe", "excess_cagr",
                      "tracking_error", "information_ratio"):
            self.assertIsNotNone(getattr(performance, field), field)

        base = RunManifest(
            manifest_version="technical-integration-v1",
            run_id="synthetic-strategy-real-benchmark-technical-only",
            as_of=END,
            code_version="technical-integration-fixture",
            rules_version=config.rules_version,
            config_hash=config.content_hash(),
            universe_hash="synthetic-universe-fixture-v1",
            snapshot_ids=(reader.snapshot_id, reader.calendar_snapshot_id),
            source_versions={"strategy": "synthetic-v1", "benchmark_reader": "v1.3.1"},
            treasury_yield_source_used="synthetic-yield-fixture",
            fallback_policy="none",
            data_quality_flags=("TECHNICAL_INTEGRATION_ONLY",) + reader.quality_flags,
        )

        def make_manifest(result):
            hashes = result.logical_hashes()
            return StrategyRunManifest(
                manifest_version="strategy-v1",
                run_id=base.run_id,
                base_run_manifest_hash=base.content_hash(),
                strategy_id=config.strategy_id,
                execution_policy_id=config.execution_policy_id,
                initial_capital=config.initial_capital,
                signal_start=SIGNAL, signal_end=SIGNAL,
                snapshot_ids=base.snapshot_ids,
                benchmark_id="H00985",
                benchmark_snapshot_id=reader.snapshot_id,
                fee_schedule_id="synthetic-fee-schedule",
                config_hash=config.content_hash(),
                code_version=base.code_version,
                rules_version=config.rules_version,
                completeness_summary={
                    "complete": False,
                    "production_ready": False,
                    "technical_integration_only": True,
                    "synthetic_strategy": True,
                    "benchmark_rows_complete": performance.complete,
                },
                order_content_hash=hashes["orders"],
                holding_content_hash=hashes["holdings"],
                nav_content_hash=hashes["nav"],
            )

        manifest_a = make_manifest(first)
        manifest_b = make_manifest(second)
        self.assertEqual(manifest_a.base_run_manifest_hash, base.content_hash())
        self.assertEqual(manifest_a.benchmark_snapshot_id, SNAPSHOT_ID)
        self.assertEqual(manifest_a.rules_version, "v1.3.0")
        self.assertFalse(manifest_a.completeness_summary["production_ready"])
        self.assertEqual(manifest_a.canonical_json(), manifest_b.canonical_json())
        self.assertEqual(manifest_a.content_hash(), manifest_b.content_hash())
        self.assertEqual(
            StrategyRunManifest.from_dict(manifest_a.to_dict()).canonical_json(),
            manifest_a.canonical_json(),
        )

        # A missing real benchmark date is UNKNOWN, never filled from a prior close.
        missing = tuple(item for item in benchmark if item.trade_date != period_dates[2])
        incomplete = calculate_performance(
            first.nav_points, benchmark_points=missing,
            risk_free_yields_pct=risk_free, trades=trades,
            expected_trading_dates=period_dates, calendar_complete_through=END,
        )
        self.assertFalse(incomplete.complete)
        self.assertIn("BENCHMARK_INCOMPLETE", incomplete.quality_flags)
        self.assertIsNone(incomplete.benchmark_cagr)
        self.assertIsNone(incomplete.excess_cagr)
        self.assertIsNone(incomplete.tracking_error)
        self.assertIsNone(incomplete.information_ratio)
        missing_yield = calculate_performance(
            first.nav_points, benchmark_points=benchmark,
            risk_free_yields_pct={}, trades=trades,
            expected_trading_dates=period_dates, calendar_complete_through=END,
        )
        self.assertFalse(missing_yield.complete)
        self.assertIn("RISK_FREE_INCOMPLETE", missing_yield.quality_flags)
        self.assertIsNone(missing_yield.sharpe)

    def test_reader_snapshot_exclusions_and_calendar_binding(self) -> None:
        reader = self._reader()
        clean = self._reader(CLEAN_SNAPSHOT_ID)
        for item in (reader, clean):
            verified = verify_published_domain(ROOT, item.snapshot_id, "benchmark")
            self.assertEqual(item.calendar_snapshot_id,
                             verified.domain_details["calendar_snapshot_id"])
        self.assertEqual(item.calendar_snapshot_id, "snapshot-2abff764afcbfb52")
        with patch("turtle_quant.pit.parquet_benchmark.expected_benchmark_dates",
                   wraps=expected_benchmark_dates) as calendar_query:
            subrange = reader.values("H00985", date(2020, 1, 1), date(2020, 12, 31))
        calendar_query.assert_called_once_with(
            ROOT, reader.calendar_snapshot_id, date(2020, 1, 1), date(2020, 12, 31)
        )
        self.assertTrue(subrange)
        self.assertEqual(subrange[0].quality_flags, reader.quality_flags)
        self.assertEqual(subrange[0].excluded_dates, reader.excluded_dates)
        self.assertEqual(subrange[0].exclusion_evidence, reader.exclusion_evidence)
        self.assertEqual(reader.values("H00985", date(2020, 1, 5), date(2020, 1, 5)), ())
        self.assertEqual(reader.excluded_dates,
                         (date(2005, 1, 1), date(2018, 6, 18)))
        with self.assertRaisesRegex(ValueError, "exceeds snapshot coverage"):
            reader.values("H00985", date(2004, 12, 31), date(2005, 1, 4))

    def test_reader_rejects_unapproved_exclusion_evidence_version(self) -> None:
        self._reader()  # establish that the unmodified published snapshot is valid
        verified = verify_published_domain(ROOT, SNAPSHOT_ID, "benchmark")
        evidence = tuple(dict(item) for item in verified.domain_details["exclusion_evidence"])
        evidence[0]["rule_version"] = "v1.4.0"
        tampered_details = dict(verified.domain_details)
        tampered_details["exclusion_evidence"] = evidence
        forged = replace(verified, domain_details=tampered_details)
        # Isolate the Reader's approved-version guard without modifying a real snapshot.
        with patch("turtle_quant.pit.parquet_benchmark.verify_published_domain",
                   return_value=forged):
            with self.assertRaisesRegex(ValueError, "unapproved rule version"):
                ParquetBenchmarkReader(ROOT, SNAPSHOT_ID)

    def test_metric_sample_and_zero_denominator_boundaries_remain_unknown(self) -> None:
        days = (date(2025, 2, 5), date(2025, 2, 6), date(2025, 2, 7))
        nav = tuple(NavPoint(day, value, value, 0) for day, value in zip(
            days, (D("100"), D("101"), D("102.01"))
        ))
        benchmark = tuple(BenchmarkPoint(item.trade_date, item.nav) for item in nav)
        one_return = calculate_performance(
            nav[:2], benchmark_points=benchmark[:2],
            risk_free_yields_pct={days[1]: D("0")}, trades=(),
            expected_trading_dates=days[:2], calendar_complete_through=days[1],
        )
        self.assertFalse(one_return.complete)
        self.assertIn("INSUFFICIENT_RETURN_SAMPLE", one_return.quality_flags)
        self.assertIsNone(one_return.annualized_volatility)
        self.assertIsNone(one_return.sharpe)
        self.assertIsNone(one_return.tracking_error)
        self.assertIsNone(one_return.information_ratio)

        zero_denominator = calculate_performance(
            nav, benchmark_points=benchmark,
            risk_free_yields_pct={days[1]: D("0"), days[2]: D("0")},
            trades=(), expected_trading_dates=days,
            calendar_complete_through=days[-1],
        )
        self.assertFalse(zero_denominator.complete)
        self.assertIn("SHARPE_DENOMINATOR_ZERO", zero_denominator.quality_flags)
        self.assertIn("ACTIVE_RETURN_DENOMINATOR_ZERO", zero_denominator.quality_flags)
        self.assertIsNone(zero_denominator.sharpe)
        self.assertIsNone(zero_denominator.information_ratio)
