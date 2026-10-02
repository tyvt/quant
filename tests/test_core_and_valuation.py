from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, getcontext
import unittest

from turtle_quant.core.manifest import RunManifest
from turtle_quant.core.pit import (
    FinancialRecord,
    InMemoryPITReader,
    InMemorySecurityMasterReader,
    SecurityRecord,
)
from turtle_quant.core.result import ResultStatus, RuleKind, RuleResult
from turtle_quant.core.types import Money, NonNegativePct, SignedRatio, UnitRatio
from turtle_quant.pipeline.decision import DecisionKind, decide
from turtle_quant.valuation.absolute import (
    AbsoluteValuationInputs,
    AttributionInputs,
    calculate_absolute_valuation,
    derive_attribution,
)
from turtle_quant.valuation.lookthrough import (
    BuybackEvent,
    BuybackQualification,
    DividendEvent,
    LookthroughInputs,
    aggregate_buybacks_365d,
    aggregate_dividends,
    calculate_lookthrough,
    qualify_buybacks,
)


D = Decimal


class UnitTypeTests(unittest.TestCase):
    def test_unit_types_reject_invalid_values(self) -> None:
        percentage = NonNegativePct(D("8"))
        self.assertEqual(percentage.value, D("8"))
        self.assertIsInstance(percentage.value, Decimal)
        self.assertEqual(SignedRatio(D("-0.2")).value, D("-0.2"))
        self.assertEqual(UnitRatio(D("0.2")).value, D("0.2"))
        self.assertEqual(Money(D("-5"), "CNY").amount, D("-5"))

        with self.assertRaises(ValueError):
            NonNegativePct(D("-1"))
        with self.assertRaises(ValueError):
            UnitRatio(D("1.01"))


class PITTests(unittest.TestCase):
    def test_reader_hides_future_data_and_selects_latest_visible_revision(self) -> None:
        period_end = date(2024, 12, 31)
        reader = InMemoryPITReader(
            [
                FinancialRecord(
                    security_id="000001.SZ",
                    period_end=period_end,
                    available_at=date(2025, 3, 20),
                    provider_revision_sequence=1,
                    values={"revenue_cny": D("100")},
                    evidence_ref="fixture:v1",
                ),
                FinancialRecord(
                    security_id="000001.SZ",
                    period_end=period_end,
                    available_at=date(2025, 4, 1),
                    provider_revision_sequence=2,
                    values={"revenue_cny": D("110")},
                    evidence_ref="fixture:v2",
                ),
                FinancialRecord(
                    security_id="000001.SZ",
                    period_end=period_end,
                    available_at=date(2025, 5, 1),
                    provider_revision_sequence=3,
                    values={"revenue_cny": D("120")},
                    evidence_ref="fixture:v3",
                ),
            ]
        )

        selected = reader.get_financial_record(
            "000001.SZ", period_end, as_of=date(2025, 4, 15)
        )
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.values["revenue_cny"], D("110"))
        self.assertEqual(selected.evidence_ref, "fixture:v2")

    def test_reader_rejects_ambiguous_visible_revision_order(self) -> None:
        record = FinancialRecord(
            security_id="000001.SZ",
            period_end=date(2024, 12, 31),
            available_at=date(2025, 3, 20),
            provider_revision_sequence=1,
            values={"revenue_cny": D("100")},
            evidence_ref="fixture:v1",
        )

        with self.assertRaises(ValueError):
            InMemoryPITReader((record, record))

    def test_financial_values_are_decimal_and_immutable(self) -> None:
        record = FinancialRecord(
            security_id="000001.SZ",
            period_end=date(2024, 12, 31),
            available_at=date(2025, 3, 20),
            provider_revision_sequence=1,
            values={"revenue_cny": D("100")},
            evidence_ref="fixture:v1",
        )

        with self.assertRaises(TypeError):
            record.values["revenue_cny"] = D("999")  # type: ignore[index]
        with self.assertRaises(ValueError):
            FinancialRecord(
                security_id="000001.SZ",
                period_end=date(2024, 12, 31),
                available_at=date(2025, 3, 20),
                provider_revision_sequence=1,
                values={"revenue_cny": 100},  # type: ignore[dict-item]
                evidence_ref="fixture:bad-value",
            )

    def test_security_master_keeps_historically_listed_delisted_security(self) -> None:
        reader = InMemorySecurityMasterReader(
            [
                SecurityRecord(
                    security_id="000001.SZ",
                    listed_at=date(2010, 1, 1),
                    delisted_at=date(2024, 12, 31),
                ),
                SecurityRecord(
                    security_id="000002.SZ",
                    listed_at=date(2020, 1, 1),
                    delisted_at=None,
                ),
            ]
        )

        self.assertEqual(
            reader.security_ids_as_of(date(2024, 6, 1)),
            ("000001.SZ", "000002.SZ"),
        )
        self.assertEqual(
            reader.security_ids_as_of(date(2025, 1, 1)),
            ("000002.SZ",),
        )
        self.assertEqual(
            reader.security_ids_as_of(date(2024, 12, 31)),
            ("000001.SZ", "000002.SZ"),
        )
        with self.assertRaises(ValueError):
            SecurityRecord(
                security_id="bad",
                listed_at=date(2025, 1, 2),
                delisted_at=date(2025, 1, 1),
            )


class AbsoluteValuationTests(unittest.TestCase):
    def test_attribution_uses_parent_equity_proxy_without_double_counting(self) -> None:
        result = derive_attribution(
            AttributionInputs(
                operating_cash_flow=D("100"),
                capex=D("20"),
                lease_cash_not_already_deducted=D("5"),
                cash=D("300"),
                liquid_assets=D("20"),
                interest_bearing_debt=D("100"),
                attributable_equity=D("80"),
                minority_interest=D("20"),
            )
        )

        self.assertEqual(result.alpha, D("0.8"))
        self.assertEqual(result.fcf_ordinary, D("64"))
        self.assertEqual(result.fcf_conservative, D("60"))
        self.assertEqual(result.net_cash, D("176"))

    def test_calculates_reference_coverage_and_payback(self) -> None:
        result = calculate_absolute_valuation(
            AbsoluteValuationInputs(
                price=D("10"),
                market_value=D("800"),
                net_cash=D("176"),
                annual_fcf_newest_to_oldest=(
                    D("100"),
                    D("90"),
                    D("80"),
                    D("70"),
                    D("60"),
                ),
                latest_annualized_fcf=D("90"),
                previous_annualized_fcf=D("70"),
            )
        )

        self.assertEqual(result.status, ResultStatus.PASS)
        self.assertEqual(result.f_norm, D("80"))
        self.assertEqual(result.f0, D("80"))
        self.assertEqual(result.delta_used, D("8"))
        self.assertEqual(
            result.f_path,
            (D("88"), D("96"), D("104"), D("112"), D("120"), D("128")),
        )
        self.assertEqual(result.coverage[6], D("1.03"))
        self.assertEqual(result.flat_coverage[6], D("0.82"))
        self.assertEqual(result.support_price[6], D("10.30"))
        self.assertEqual(result.payback, D("5.8125"))
        with self.assertRaises(TypeError):
            result.coverage[99] = D("999")  # type: ignore[index]

    def test_normalization_uses_a3_when_median_is_zero(self) -> None:
        result = calculate_absolute_valuation(
            AbsoluteValuationInputs(
                price=D("10"),
                market_value=D("800"),
                net_cash=D("0"),
                annual_fcf_newest_to_oldest=(
                    D("100"),
                    D("100"),
                    D("0"),
                    D("0"),
                    D("0"),
                ),
                latest_annualized_fcf=D("100"),
                previous_annualized_fcf=D("100"),
            )
        )

        self.assertEqual(result.f_norm, D("66.66666666666666666666666667"))

    def test_normalization_uses_median_when_a3_is_zero(self) -> None:
        result = calculate_absolute_valuation(
            AbsoluteValuationInputs(
                price=D("10"),
                market_value=D("800"),
                net_cash=D("0"),
                annual_fcf_newest_to_oldest=(
                    D("-10"),
                    D("10"),
                    D("0"),
                    D("20"),
                    D("30"),
                ),
                latest_annualized_fcf=D("10"),
                previous_annualized_fcf=D("10"),
            )
        )

        self.assertEqual(result.f_norm, D("10"))

    def test_valuation_result_defensively_freezes_f_path(self) -> None:
        from turtle_quant.valuation.absolute import AbsoluteValuationResult

        result = AbsoluteValuationResult(
            status=ResultStatus.PASS,
            f_path=[D("1")],  # type: ignore[arg-type]
        )

        self.assertIsInstance(result.f_path, tuple)

    def test_missing_latest_fcf_returns_unknown_instead_of_zero_fallback(self) -> None:
        result = calculate_absolute_valuation(
            AbsoluteValuationInputs(
                price=D("10"),
                market_value=D("800"),
                net_cash=D("176"),
                annual_fcf_newest_to_oldest=(
                    D("100"),
                    D("90"),
                    D("80"),
                    D("70"),
                    D("60"),
                ),
                latest_annualized_fcf=None,
                previous_annualized_fcf=D("70"),
            )
        )

        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertIn("latest_annualized_fcf", result.missing_fields)
        self.assertIsNone(result.f0)

    def test_missing_previous_fcf_records_delta_reason(self) -> None:
        result = calculate_absolute_valuation(
            AbsoluteValuationInputs(
                price=D("10"),
                market_value=D("800"),
                net_cash=D("176"),
                annual_fcf_newest_to_oldest=(
                    D("100"),
                    D("90"),
                    D("80"),
                    D("70"),
                    D("60"),
                ),
                latest_annualized_fcf=D("90"),
                previous_annualized_fcf=None,
            )
        )

        self.assertEqual(result.delta_base, D("0"))
        self.assertEqual(result.delta_base_reason, "previous_fcf_missing_or_non_positive")

    def test_material_decline_without_supported_magnitude_uses_explicit_zero_growth(self) -> None:
        result = calculate_absolute_valuation(
            AbsoluteValuationInputs(
                price=D("10"),
                market_value=D("800"),
                net_cash=D("176"),
                annual_fcf_newest_to_oldest=(
                    D("100"),
                    D("90"),
                    D("80"),
                    D("70"),
                    D("60"),
                ),
                latest_annualized_fcf=D("90"),
                previous_annualized_fcf=D("70"),
                material_decline=True,
                decline_g=None,
            )
        )

        self.assertEqual(result.delta_used, D("0"))
        self.assertEqual(result.f_path, (D("80"),) * 6)

    def test_calculation_uses_fixed_decimal_context(self) -> None:
        original_precision = getcontext().prec
        getcontext().prec = 6
        try:
            result = calculate_absolute_valuation(
                AbsoluteValuationInputs(
                    price=D("10"),
                    market_value=D("800"),
                    net_cash=D("0"),
                    annual_fcf_newest_to_oldest=(
                        D("91"),
                        D("90"),
                        D("90"),
                        D("100"),
                        D("100"),
                    ),
                    latest_annualized_fcf=D("91"),
                    previous_annualized_fcf=D("90"),
                )
            )
        finally:
            getcontext().prec = original_precision

        self.assertEqual(result.f_norm, D("90.33333333333333333333333333"))


class LookthroughTests(unittest.TestCase):
    def test_calculates_shared_capacity_and_price_ladder(self) -> None:
        result = calculate_lookthrough(
            LookthroughInputs(
                capacity=D("80"),
                dividends=D("60"),
                qualified_buybacks=D("30"),
                market_value=D("800"),
                price=D("10"),
                required_return_pct=D("5"),
                tax_rate=UnitRatio(D("0.2")),
            )
        )

        self.assertEqual(result.status, ResultStatus.PASS)
        self.assertEqual(result.dividend_allocation, D("60"))
        self.assertEqual(result.buyback_allocation, D("20"))
        self.assertEqual(result.shareholder_cash_net, D("68"))
        self.assertEqual(result.gg_pct, D("8.5"))
        self.assertEqual(result.observe_price, D("17"))
        self.assertEqual(result.heavy_price, D("8.5"))
        self.assertEqual(result.standard_price, D("12.75"))

    def test_rolls_dividends_left_open_and_buybacks_closed_at_start_boundary(self) -> None:
        as_of = date(2025, 12, 31)
        dividends = (
            DividendEvent(date(2024, 12, 31), D("10"), is_ordinary=True, is_paid=True),
            DividendEvent(date(2025, 1, 1), D("20"), is_ordinary=True, is_paid=True),
        )
        buybacks = (
            BuybackEvent(date(2024, 12, 31), D("30"), cancellation_verified=True),
            BuybackEvent(date(2025, 1, 1), D("40"), cancellation_verified=True),
        )

        self.assertEqual(aggregate_dividends(dividends, as_of), D("20"))
        self.assertEqual(aggregate_buybacks_365d(buybacks, as_of), D("70"))

    def test_unknown_relevant_dividend_state_propagates_unknown(self) -> None:
        as_of = date(2025, 12, 31)
        cases = (
            DividendEvent(
                date(2025, 7, 1),
                D("20"),
                is_ordinary=None,
                is_paid=True,
            ),
            DividendEvent(
                date(2025, 7, 1),
                D("20"),
                is_ordinary=True,
                is_paid=None,
            ),
            DividendEvent(
                date(2025, 7, 1),
                None,
                is_ordinary=True,
                is_paid=True,
            ),
            DividendEvent(
                None,
                D("20"),
                is_ordinary=True,
                is_paid=True,
            ),
        )

        for event in cases:
            with self.subTest(event=event):
                self.assertIsNone(aggregate_dividends((event,), as_of))

    def test_definitively_excluded_dividend_ignores_other_unknowns(self) -> None:
        events = (
            DividendEvent(
                None,
                None,
                is_ordinary=False,
                is_paid=None,
            ),
            DividendEvent(
                None,
                None,
                is_ordinary=None,
                is_paid=False,
            ),
        )

        self.assertEqual(
            aggregate_dividends(events, date(2025, 12, 31)),
            D("0"),
        )

    def test_unknown_state_outside_dividend_window_is_irrelevant(self) -> None:
        events = (
            DividendEvent(
                date(2024, 12, 31),
                None,
                is_ordinary=None,
                is_paid=None,
            ),
        )

        self.assertEqual(
            aggregate_dividends(events, date(2025, 12, 31)),
            D("0"),
        )

    def test_unknown_relevant_buyback_state_propagates_unknown(self) -> None:
        as_of = date(2025, 12, 31)
        cases = (
            BuybackEvent(
                date(2025, 7, 1),
                D("20"),
                cancellation_verified=None,
            ),
            BuybackEvent(
                date(2025, 7, 1),
                D("20"),
                cancellation_verified=True,
                is_executed=None,
            ),
            BuybackEvent(
                date(2025, 7, 1),
                None,
                cancellation_verified=True,
            ),
            BuybackEvent(
                None,
                D("20"),
                cancellation_verified=True,
            ),
        )

        for event in cases:
            with self.subTest(event=event):
                self.assertIsNone(aggregate_buybacks_365d((event,), as_of))

    def test_definitively_excluded_buyback_ignores_other_unknowns(self) -> None:
        events = (
            BuybackEvent(
                None,
                None,
                cancellation_verified=False,
                is_executed=None,
            ),
            BuybackEvent(
                None,
                None,
                cancellation_verified=None,
                is_executed=False,
            ),
        )

        self.assertEqual(
            aggregate_buybacks_365d(events, date(2025, 12, 31)),
            D("0"),
        )

    def test_buyback_qualification_preserves_unknown_event_state(self) -> None:
        result = qualify_buybacks(
            (
                BuybackEvent(
                    None,
                    D("20"),
                    cancellation_verified=True,
                ),
            ),
            as_of=date(2025, 12, 31),
            latest_complete_calendar_year_amount=D("20"),
            latest_calendar_year_coverage_complete=True,
        )

        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertIsNone(result.qualified_buybacks)
        self.assertIsNone(result.executed_buyback_365d)
        self.assertEqual(result.reasons, ("buyback_event_state_unknown",))

    def test_unknown_qualified_buybacks_remain_unknown(self) -> None:
        result = calculate_lookthrough(
            LookthroughInputs(
                capacity=D("80"),
                dividends=D("60"),
                qualified_buybacks=None,
                market_value=D("800"),
                price=D("10"),
                required_return_pct=D("5"),
                tax_rate=UnitRatio(D("0")),
            )
        )

        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertIn("qualified_buybacks", result.missing_fields)

    def test_zero_capacity_with_complete_events_preserves_zero_gg(self) -> None:
        result = calculate_lookthrough(
            LookthroughInputs(
                capacity=D("0"),
                dividends=D("60"),
                qualified_buybacks=D("30"),
                market_value=D("800"),
                price=D("10"),
                required_return_pct=D("5"),
                tax_rate=UnitRatio(D("0")),
            )
        )

        self.assertEqual(result.status, ResultStatus.FAIL)
        self.assertEqual(result.gg_pct, D("0"))
        self.assertIsNone(result.observe_price)

    def test_qualifies_sustained_buybacks_with_year_coverage_cap(self) -> None:
        result = qualify_buybacks(
            (
                BuybackEvent(date(2023, 12, 30), D("10"), cancellation_verified=True),
                BuybackEvent(date(2024, 7, 1), D("20"), cancellation_verified=True),
                BuybackEvent(date(2025, 12, 1), D("100"), cancellation_verified=True),
            ),
            as_of=date(2025, 12, 31),
            latest_complete_calendar_year_amount=D("80"),
            latest_calendar_year_coverage_complete=True,
        )

        self.assertEqual(result.status, ResultStatus.PASS)
        self.assertEqual(result.executed_buyback_365d, D("100"))
        self.assertEqual(result.qualified_buybacks, D("80"))

    def test_missing_calendar_year_coverage_keeps_buybacks_unknown(self) -> None:
        result = qualify_buybacks(
            (),
            as_of=date(2025, 12, 31),
            latest_complete_calendar_year_amount=None,
            latest_calendar_year_coverage_complete=False,
        )

        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertIsNone(result.qualified_buybacks)

    def test_known_but_nonrecurring_buybacks_are_zero_with_execution_reference(self) -> None:
        result = qualify_buybacks(
            (
                BuybackEvent(date(2025, 12, 1), D("40"), cancellation_verified=True),
            ),
            as_of=date(2025, 12, 31),
            latest_complete_calendar_year_amount=D("40"),
            latest_calendar_year_coverage_complete=True,
        )

        self.assertEqual(result.status, ResultStatus.PASS)
        self.assertEqual(result.qualified_buybacks, D("0"))
        self.assertEqual(result.executed_buyback_365d, D("40"))
        self.assertEqual(result.reasons, ("buyback_continuity_not_met",))

    def test_sustained_buyback_window_is_exactly_three_times_365_days(self) -> None:
        result = qualify_buybacks(
            (
                BuybackEvent(date(2022, 12, 31), D("10"), cancellation_verified=True),
                BuybackEvent(date(2024, 7, 1), D("20"), cancellation_verified=True),
                BuybackEvent(date(2025, 12, 1), D("30"), cancellation_verified=True),
            ),
            as_of=date(2025, 12, 31),
            latest_complete_calendar_year_amount=D("30"),
            latest_calendar_year_coverage_complete=True,
        )

        self.assertEqual(result.qualified_buybacks, D("0"))
        self.assertEqual(result.reasons, ("buyback_continuity_not_met",))


class DecisionTests(unittest.TestCase):
    def test_hard_gate_failure_rejects_before_valuation(self) -> None:
        decision = decide(
            (
                RuleResult(
                    rule_id="quality.roe",
                    kind=RuleKind.HARD_GATE,
                    status=ResultStatus.FAIL,
                ),
            ),
            coverage6=D("2"),
            gg_pct=D("12"),
            required_return_pct=D("5"),
            score_coverage=D("1"),
        )

        self.assertEqual(decision.kind, DecisionKind.REJECTED)

    def test_unknown_result_takes_priority_over_hard_gate_failure(self) -> None:
        decision = decide(
            (
                RuleResult(
                    rule_id="quality.roe",
                    kind=RuleKind.HARD_GATE,
                    status=ResultStatus.FAIL,
                ),
                RuleResult(
                    rule_id="cashflow.missing",
                    kind=RuleKind.EVIDENCE,
                    status=ResultStatus.UNKNOWN,
                ),
            ),
            coverage6=D("2"),
            gg_pct=D("12"),
            required_return_pct=D("5"),
            score_coverage=D("1"),
        )

        self.assertEqual(decision.kind, DecisionKind.NEEDS_REVIEW)

    def test_unknown_score_coverage_is_needs_review_not_tier(self) -> None:
        decision = decide(
            (),
            coverage6=D("1.2"),
            gg_pct=D("6"),
            required_return_pct=D("5"),
            score_coverage=D("0.8"),
        )

        self.assertEqual(decision.kind, DecisionKind.NEEDS_REVIEW)
        self.assertTrue(decision.reference_score_incomplete)

    def test_complete_qualified_result_is_candidate(self) -> None:
        decision = decide(
            (),
            coverage6=D("1"),
            gg_pct=D("5"),
            required_return_pct=D("5"),
            score_coverage=D("1"),
        )

        self.assertEqual(decision.kind, DecisionKind.CANDIDATE)

    def test_complete_but_insufficient_valuation_is_rejected(self) -> None:
        coverage_failure = decide(
            (),
            coverage6=D("0.99"),
            gg_pct=D("6"),
            required_return_pct=D("5"),
            score_coverage=D("1"),
        )
        gg_failure = decide(
            (),
            coverage6=D("1"),
            gg_pct=D("4.99"),
            required_return_pct=D("5"),
            score_coverage=D("1"),
        )
        not_supported = decide(
            (),
            coverage6=D("1"),
            gg_pct=D("5"),
            required_return_pct=D("5"),
            score_coverage=D("1"),
            profile_status=ResultStatus.NOT_SUPPORTED,
        )

        self.assertEqual(coverage_failure.kind, DecisionKind.REJECTED)
        self.assertEqual(gg_failure.kind, DecisionKind.REJECTED)
        self.assertEqual(not_supported.kind, DecisionKind.NOT_SUPPORTED)


class ManifestTests(unittest.TestCase):
    def test_manifest_has_frozen_reproducibility_fields(self) -> None:
        manifest = RunManifest(
            manifest_version="v1",
            run_id="fixture-run",
            as_of=date(2025, 12, 31),
            code_version="test",
            rules_version="v1.0.0",
            config_hash="config-hash",
            universe_hash="universe-hash",
            snapshot_ids=("fixture:a",),
            source_versions={"fixture": "v1"},
            treasury_yield_source_used="fixture",
            fallback_policy="needs_review",
            data_quality_flags=("fixture_only",),
        )

        serialized = manifest.to_dict()
        self.assertEqual(serialized["rules_version"], "v1.0.0")
        self.assertEqual(serialized["as_of"], "2025-12-31")
        self.assertEqual(serialized["snapshot_ids"], ["fixture:a"])
        with self.assertRaises(TypeError):
            manifest.source_versions["fixture"] = "changed"  # type: ignore[index]

    def test_manifest_round_trip_and_hash_are_deterministic(self) -> None:
        manifest = RunManifest(
            manifest_version="v1",
            run_id="fixture-run",
            as_of=date(2025, 12, 31),
            code_version="test",
            rules_version="v1.0.0",
            config_hash="config-hash",
            universe_hash="universe-hash",
            snapshot_ids=("fixture:a", "fixture:b"),
            source_versions={"z_source": "v2", "a_source": "v1"},
            treasury_yield_source_used="fixture",
            fallback_policy="needs_review",
            data_quality_flags=("a_flag", "z_flag"),
        )
        same_content_different_order = RunManifest(
            manifest_version="v1",
            run_id="fixture-run",
            as_of=date(2025, 12, 31),
            code_version="test",
            rules_version="v1.0.0",
            config_hash="config-hash",
            universe_hash="universe-hash",
            snapshot_ids=("fixture:a", "fixture:b"),
            source_versions={"a_source": "v1", "z_source": "v2"},
            treasury_yield_source_used="fixture",
            fallback_policy="needs_review",
            data_quality_flags=("a_flag", "z_flag"),
        )
        same_collections_different_order = RunManifest(
            manifest_version="v1",
            run_id="fixture-run",
            as_of=date(2025, 12, 31),
            code_version="test",
            rules_version="v1.0.0",
            config_hash="config-hash",
            universe_hash="universe-hash",
            snapshot_ids=("fixture:b", "fixture:a"),
            source_versions={"a_source": "v1", "z_source": "v2"},
            treasury_yield_source_used="fixture",
            fallback_policy="needs_review",
            data_quality_flags=("z_flag", "a_flag"),
        )
        unicode_composed = RunManifest(
            manifest_version="v1",
            run_id="café",
            as_of=date(2025, 12, 31),
            code_version="test",
            rules_version="v1.0.0",
            config_hash="config-hash",
            universe_hash="universe-hash",
            snapshot_ids=("fixture:a",),
            source_versions={"fixture": "v1"},
            treasury_yield_source_used="fixture",
            fallback_policy="needs_review",
            data_quality_flags=(),
        )
        unicode_decomposed = RunManifest(
            manifest_version="v1",
            run_id="cafe\u0301",
            as_of=date(2025, 12, 31),
            code_version="test",
            rules_version="v1.0.0",
            config_hash="config-hash",
            universe_hash="universe-hash",
            snapshot_ids=("fixture:a",),
            source_versions={"fixture": "v1"},
            treasury_yield_source_used="fixture",
            fallback_policy="needs_review",
            data_quality_flags=(),
        )

        restored = RunManifest.from_dict(manifest.to_dict())

        self.assertEqual(restored.to_dict(), manifest.to_dict())
        self.assertEqual(manifest.content_hash(), same_content_different_order.content_hash())
        self.assertEqual(manifest.content_hash(), same_collections_different_order.content_hash())
        self.assertEqual(unicode_composed.content_hash(), unicode_decomposed.content_hash())
        self.assertEqual(manifest, same_collections_different_order)
        self.assertEqual(hash(manifest), hash(same_collections_different_order))
        self.assertIsInstance(hash(manifest), int)
        self.assertEqual(unicode_composed, unicode_decomposed)
        self.assertEqual(hash(unicode_composed), hash(unicode_decomposed))
        duplicate_flags = RunManifest(
            manifest_version="v1",
            run_id="duplicate-flags",
            as_of=date(2025, 12, 31),
            code_version="test",
            rules_version="v1.0.0",
            config_hash="config-hash",
            universe_hash="universe-hash",
            snapshot_ids=("fixture:a",),
            source_versions={"fixture": "v1"},
            treasury_yield_source_used="fixture",
            fallback_policy="needs_review",
            data_quality_flags=("missing_field", "missing_field"),
        )
        self.assertEqual(duplicate_flags.data_quality_flags, ("missing_field",))
        with self.assertRaises(ValueError):
            RunManifest(
                manifest_version="v1",
                run_id="duplicate-snapshot",
                as_of=date(2025, 12, 31),
                code_version="test",
                rules_version="v1.0.0",
                config_hash="config-hash",
                universe_hash="universe-hash",
                snapshot_ids=("café-snap", "cafe\u0301-snap"),
                source_versions={"fixture": "v1"},
                treasury_yield_source_used="fixture",
                fallback_policy="needs_review",
                data_quality_flags=(),
            )
        with self.assertRaises(ValueError):
            RunManifest(
                manifest_version="v1",
                run_id="datetime-not-date",
                as_of=datetime(2025, 12, 31, 9, 30),
                code_version="test",
                rules_version="v1.0.0",
                config_hash="config-hash",
                universe_hash="universe-hash",
                snapshot_ids=("fixture:a",),
                source_versions={"fixture": "v1"},
                treasury_yield_source_used="fixture",
                fallback_policy="needs_review",
                data_quality_flags=(),
            )


if __name__ == "__main__":
    unittest.main()
