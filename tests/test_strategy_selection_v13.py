from datetime import date, timedelta
from decimal import Decimal
import unittest

from turtle_quant.core.share_capital_policy import ShareCapitalEvidence
from turtle_quant.pipeline.decision import DecisionKind
from turtle_quant.strategy.selection import (
    CandidateMetrics,
    DiagnosticRecord,
    LiquidityDay,
    SecurityAssessment,
    UniverseInput,
    UniverseStatus,
    build_monthly_selection,
    evaluate_universe_security,
    month_end_signal_dates,
)


D = Decimal


def liquidity(
    *,
    count: int = 60,
    amount: str = "30000000",
) -> tuple[LiquidityDay, ...]:
    start = date(2025, 1, 1)
    return tuple(
        LiquidityDay(
            trade_date=start + timedelta(days=offset),
            amount=D(amount),
            tradable=True,
            evidence_ref=f"amount:{offset}",
        )
        for offset in range(count)
    )


def universe_input(**overrides: object) -> UniverseInput:
    values: dict[str, object] = {
        "security_id": "sh.600000",
        "as_of": liquidity()[-1].trade_date,
        "expected_liquidity_dates": tuple(day.trade_date for day in liquidity()),
        "main_board_a_share": True,
        "listing_trading_days": 600,
        "industry_profile": "GENERAL_FCF",
        "eligible_security_status": True,
        "market_value": D("6000000000"),
        "liquidity_days": liquidity(),
        "stage_a_coverage_complete": True,
        "shares_known": True,
    }
    values.update(overrides)
    return UniverseInput(**values)  # type: ignore[arg-type]


def capital_evidence(
    classes: tuple[str, ...] | None,
    treasury_shares: int | None,
) -> ShareCapitalEvidence:
    as_of = liquidity()[-1].trade_date
    return ShareCapitalEvidence(
        security_id="sh.600000",
        as_of=as_of,
        ordinary_share_classes=classes,
        treasury_shares=treasury_shares,
        available_on=as_of,
        evidence_ref="synthetic:capital-structure",
    )


def candidate(
    security_id: str,
    *,
    quality: str,
    coverage: str,
    margin: str,
    position: str,
) -> SecurityAssessment:
    return SecurityAssessment(
        security_id=security_id,
        decision_kind=DecisionKind.CANDIDATE,
        reasons=(),
        missing_fields=(),
        quality_flags=(),
        hard_gate_statuses=("PASS",),
        score_statuses=("PASS",),
        evidence_statuses=("PASS",),
        metrics=CandidateMetrics(
            quality_score=D(quality),
            coverage6=D(coverage),
            gg_margin_pct=D(margin),
            market_position_score=D(position),
        ),
    )


class UniverseTests(unittest.TestCase):
    def test_complete_security_is_eligible(self) -> None:
        result = evaluate_universe_security(universe_input())
        self.assertEqual(result.status, UniverseStatus.ELIGIBLE)
        self.assertEqual(result.valid_trading_amount_days, 60)
        self.assertEqual(result.median_trading_amount, D("30000000"))

    def test_60_day_screen_requires_at_least_50_tradable_days(self) -> None:
        rows = list(liquidity())
        for index in range(11):
            rows[index] = LiquidityDay(
                trade_date=rows[index].trade_date,
                amount=D("0"),
                tradable=False,
                evidence_ref=f"suspension:{index}",
            )
        result = evaluate_universe_security(
            universe_input(liquidity_days=tuple(rows))
        )
        self.assertEqual(result.status, UniverseStatus.REJECTED)
        self.assertIn("insufficient_tradable_amount_days", result.reasons)

    def test_missing_bar_evidence_is_needs_review_not_rejection(self) -> None:
        rows = list(liquidity())
        rows[0] = LiquidityDay(
            trade_date=rows[0].trade_date,
            amount=D("30000000"),
            tradable=True,
            evidence_ref=None,
        )
        result = evaluate_universe_security(
            universe_input(liquidity_days=tuple(rows))
        )
        self.assertEqual(result.status, UniverseStatus.NEEDS_REVIEW)
        self.assertIn("liquidity_evidence_unknown", result.reasons)

    def test_omitted_liquidity_day_and_future_rows_cannot_change_signal(self) -> None:
        rows = liquidity()
        baseline = evaluate_universe_security(universe_input())
        future = LiquidityDay(
            rows[-1].trade_date + timedelta(days=1), D("0"), True, "future",
        )
        with_future = evaluate_universe_security(universe_input(liquidity_days=rows + (future,)))
        missing = evaluate_universe_security(
            universe_input(liquidity_days=tuple(day for day in rows if day != rows[10]))
        )
        self.assertEqual(baseline, with_future)
        self.assertEqual(missing.status, UniverseStatus.NEEDS_REVIEW)
        self.assertIn("liquidity_window_incomplete", missing.reasons)

    def test_known_unsupported_profile_is_not_supported(self) -> None:
        result = evaluate_universe_security(
            universe_input(industry_profile="BANK")
        )
        self.assertEqual(result.status, UniverseStatus.NOT_SUPPORTED)

    def test_ambiguous_shares_are_review_even_when_profile_is_unsupported(self) -> None:
        for classes, treasury in ((("A", "B"), 0), (("A",), 1)):
            with self.subTest(classes=classes):
                result = evaluate_universe_security(universe_input(
                    industry_profile="BANK",
                    share_capital_evidence=capital_evidence(classes, treasury),
                ))
                self.assertEqual(result.status, UniverseStatus.NEEDS_REVIEW)
                self.assertIn("industry_profile_not_supported", result.reasons)
                self.assertIn("shares_unknown", result.reasons)
                self.assertIn("market_value_unknown", result.reasons)
        clean = evaluate_universe_security(universe_input(
            industry_profile="BANK",
            share_capital_evidence=capital_evidence(("A",), 0),
        ))
        self.assertEqual(clean.status, UniverseStatus.NOT_SUPPORTED)

    def test_market_value_threshold_is_exact(self) -> None:
        at_threshold = evaluate_universe_security(
            universe_input(market_value=D("5000000000"))
        )
        below = evaluate_universe_security(
            universe_input(market_value=D("4999999999"))
        )
        self.assertEqual(at_threshold.status, UniverseStatus.ELIGIBLE)
        self.assertEqual(below.status, UniverseStatus.REJECTED)

    def test_multiclass_overrides_numeric_market_value_and_known_shares(self) -> None:
        result = evaluate_universe_security(universe_input(
            share_capital_evidence=capital_evidence(("A", "B"), 0),
        ))
        self.assertEqual(result.status, UniverseStatus.NEEDS_REVIEW)
        self.assertIn("multiple_ordinary_share_classes", result.reasons)
        self.assertIn("shares_unknown", result.reasons)
        self.assertIn("market_value_unknown", result.reasons)

    def test_single_class_treasury_is_review_but_zero_is_not(self) -> None:
        with_treasury = evaluate_universe_security(universe_input(
            share_capital_evidence=capital_evidence(("A",), 1),
        ))
        clean = evaluate_universe_security(universe_input(
            share_capital_evidence=capital_evidence(("A",), 0),
        ))
        self.assertEqual(with_treasury.status, UniverseStatus.NEEDS_REVIEW)
        self.assertIn("treasury_shares_nonzero", with_treasury.reasons)
        self.assertEqual(clean.status, UniverseStatus.ELIGIBLE)


class SelectionTests(unittest.TestCase):
    def test_capital_policy_review_blocks_whole_month(self) -> None:
        universe = evaluate_universe_security(universe_input(
            share_capital_evidence=capital_evidence(("A", "D", "H"), 0),
        ))
        self.assertEqual(universe.status, UniverseStatus.NEEDS_REVIEW)
        review = SecurityAssessment(
            security_id=universe.security_id,
            decision_kind=DecisionKind.NEEDS_REVIEW,
            reasons=universe.reasons,
            missing_fields=("S", "MV"),
            quality_flags=("SHARE_CAPITAL_POLICY_UNKNOWN",),
            hard_gate_statuses=("UNKNOWN",),
            score_statuses=(),
            evidence_statuses=("UNKNOWN",),
            metrics=None,
        )
        month = build_monthly_selection((
            candidate("sh.600001", quality="90", coverage="2", margin="8", position="70"),
            review,
        ))
        self.assertTrue(month.diagnostic_only)
        self.assertFalse(month.official_selection)
        self.assertEqual(month.ranked_candidates, ())
        self.assertEqual(dict(month.target_weights), {})
        self.assertIn("multiple_ordinary_share_classes", month.diagnostics[0].reasons)

    def test_midrank_composite_and_stable_security_id_tie_break(self) -> None:
        assessments = (
            candidate("sh.600002", quality="80", coverage="2", margin="8", position="70"),
            candidate("sh.600001", quality="80", coverage="2", margin="8", position="70"),
        )
        result = build_monthly_selection(assessments)

        self.assertTrue(result.official_selection)
        self.assertFalse(result.diagnostic_only)
        self.assertEqual(
            tuple(item.security_id for item in result.ranked_candidates),
            ("sh.600001", "sh.600002"),
        )
        self.assertTrue(
            all(item.composite_score == D("61") for item in result.ranked_candidates)
        )
        self.assertEqual(result.target_weights["sh.600001"], D("0.05"))
        self.assertEqual(result.cash_weight, D("0.90"))

    def test_top_twenty_and_five_percent_cap(self) -> None:
        assessments = tuple(
            candidate(
                f"sh.{600000 + index:06d}",
                quality=str(100 - index),
                coverage=str(100 - index),
                margin=str(100 - index),
                position=str(100 - index),
            )
            for index in range(25)
        )
        result = build_monthly_selection(assessments)
        self.assertEqual(len(result.ranked_candidates), 20)
        self.assertEqual(sum(result.target_weights.values()), D("1.00"))
        self.assertEqual(result.cash_weight, D("0.00"))

    def test_needs_review_month_outputs_diagnostics_only(self) -> None:
        needs_review = SecurityAssessment(
            security_id="sh.600003",
            decision_kind=DecisionKind.NEEDS_REVIEW,
            reasons=("shares_unknown",),
            missing_fields=("shares",),
            quality_flags=("MISSING_SHARES",),
            hard_gate_statuses=("UNKNOWN",),
            score_statuses=(),
            evidence_statuses=("UNKNOWN",),
            metrics=None,
        )
        result = build_monthly_selection(
            (candidate("sh.600001", quality="90", coverage="2", margin="8", position="70"), needs_review)
        )

        self.assertTrue(result.diagnostic_only)
        self.assertFalse(result.official_selection)
        self.assertEqual(result.ranked_candidates, ())
        self.assertEqual(dict(result.target_weights), {})
        self.assertEqual(result.cash_weight, D("1"))
        forbidden = {
            "rank",
            "top_n",
            "composite_score",
            "target_weight",
            "order_plan",
            "position",
            "nav",
        }
        for record in result.diagnostics:
            self.assertIsInstance(record, DiagnosticRecord)
            self.assertTrue(forbidden.isdisjoint(record.to_dict()))
            self.assertTrue(record.to_dict()["diagnostic_only"])
            self.assertFalse(record.to_dict()["official_selection"])

    def test_month_end_signal_dates_take_last_trading_day(self) -> None:
        dates = (
            date(2025, 1, 2),
            date(2025, 1, 31),
            date(2025, 2, 3),
            date(2025, 2, 28),
        )
        self.assertEqual(
            month_end_signal_dates(dates, calendar_complete_through=date(2025, 2, 28)),
            (date(2025, 1, 31), date(2025, 2, 28)),
        )

    def test_partial_calendar_month_does_not_emit_early_signal(self) -> None:
        dates = (date(2025, 1, 31), date(2025, 2, 3))
        self.assertEqual(
            month_end_signal_dates(dates, calendar_complete_through=date(2025, 2, 10)),
            (date(2025, 1, 31),),
        )


if __name__ == "__main__":
    unittest.main()
