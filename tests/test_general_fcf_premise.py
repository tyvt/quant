from datetime import date
from decimal import Decimal
import unittest

from turtle_quant.core.result import ResultStatus
from turtle_quant.premise.general_fcf import (
    AnnualFinancialObservation,
    GeneralFCFInputs,
    QualityComponents,
    QualityWeights,
    combine_quality_scores,
    derive_ttm,
    evaluate_general_fcf,
)


D = Decimal


def annual(
    year: int,
    *,
    available_at: date | None = None,
    equity: str = "100",
    profit: str = "15",
    ocf: str = "20",
    capex: str = "5",
    lease: str = "1",
    traceable: bool = True,
) -> AnnualFinancialObservation:
    return AnnualFinancialObservation(
        fiscal_year=year,
        available_at=available_at or date(year + 1, 4, 30),
        attributable_equity_end=D(equity),
        total_equity_end=D(equity),
        minority_interest_end=None,
        parent_net_profit=D(profit),
        operating_cash_flow=D(ocf),
        capex=D(capex),
        lease_cash_not_already_deducted=D(lease),
        currency="CNY",
        statement_scope="CONSOLIDATED",
        traceable=traceable,
        evidence_refs=(f"annual:{year}",),
    )


class GeneralFCFPremiseTests(unittest.TestCase):
    def _inputs(self, observations: tuple[AnnualFinancialObservation, ...]) -> GeneralFCFInputs:
        return GeneralFCFInputs(
            as_of=date(2026, 5, 1),
            industry_profile="GENERAL_FCF",
            statements_comparable=True,
            latest_audit_unmodified=True,
            going_concern_uncertainty=False,
            latest_equity=D("100"),
            annual_observations=observations,
            cash=D("30"),
            liquid_assets=D("10"),
            interest_bearing_debt=D("20"),
        )

    def test_six_consecutive_year_ends_are_required(self) -> None:
        observations = tuple(annual(year) for year in range(2020, 2026))
        result = evaluate_general_fcf(self._inputs(observations))

        self.assertEqual(result.y0, 2025)
        self.assertEqual(result.gate("premise.roe_5y").status, ResultStatus.PASS)
        self.assertEqual(len(result.annual_roe_pct), 5)

    def test_missing_oldest_equity_cannot_be_replaced_by_an_older_year(self) -> None:
        observations = tuple(
            annual(year) for year in (2019, 2020, 2022, 2023, 2024, 2025)
        )
        result = evaluate_general_fcf(self._inputs(observations))

        self.assertEqual(result.y0, 2025)
        self.assertEqual(
            result.gate("premise.roe_5y").status,
            ResultStatus.UNKNOWN,
        )
        self.assertEqual(result.annual_roe_pct, ())

    def test_future_annual_report_is_not_visible(self) -> None:
        observations = tuple(annual(year) for year in range(2020, 2025)) + (
            annual(2025, available_at=date(2026, 5, 2)),
        )
        result = evaluate_general_fcf(self._inputs(observations))

        self.assertEqual(result.y0, 2024)
        self.assertEqual(
            result.gate("premise.roe_5y").status,
            ResultStatus.UNKNOWN,
        )

    def test_complete_fixture_passes_gates_and_scores(self) -> None:
        result = evaluate_general_fcf(
            self._inputs(tuple(annual(year) for year in range(2020, 2026)))
        )

        self.assertTrue(all(gate.status is ResultStatus.PASS for gate in result.hard_gates))
        self.assertEqual(result.annual_fcf_newest_to_oldest, (D("14"),) * 5)
        self.assertEqual(result.f_norm, D("14"))
        self.assertIsNotNone(result.quality.quality_score)
        self.assertEqual(result.quality.score_coverage, D("1.00"))

    def test_fcf_does_not_skip_a_negative_year(self) -> None:
        observations = tuple(
            annual(year, ocf="0" if year == 2023 else "20")
            for year in range(2020, 2026)
        )
        result = evaluate_general_fcf(self._inputs(observations))

        self.assertIn(D("-6"), result.annual_fcf_newest_to_oldest)
        self.assertEqual(len(result.annual_fcf_newest_to_oldest), 5)

    def test_quality_component_unknown_is_not_renormalized(self) -> None:
        result = combine_quality_scores(
            QualityComponents(
                roe_score=D("80"),
                fcf_stability_score=D("100"),
                cash_conversion_score=None,
                balance_score=D("100"),
            )
        )

        self.assertIsNone(result.quality_score)
        self.assertEqual(result.score_coverage, D("0.75"))
        self.assertEqual(result.reference_raw_score, D("68.00"))

    def test_quality_weights_require_exact_keys_and_exact_one(self) -> None:
        with self.assertRaises(ValueError):
            QualityWeights.from_mapping(
                {
                    "roe_score": D("0.35"),
                    "fcf_stability_score": D("0.25"),
                    "cash_conversion_score": D("0.25"),
                    "balance_score": D("0.14"),
                }
            )
        with self.assertRaises(ValueError):
            QualityWeights.from_mapping(
                {
                    "roe_score": D("0.35"),
                    "fcf_stability_score": D("0.25"),
                    "cash_conversion_score": D("0.25"),
                    "balance_score": D("0.15"),
                    "extra": D("0"),
                }
            )

    def test_ttm_requires_matching_scope_currency_and_period(self) -> None:
        self.assertEqual(
            derive_ttm(
                fy_previous=D("100"),
                ytd_current=D("40"),
                ytd_previous_comparable=D("30"),
                fy_scope="CONSOLIDATED",
                current_scope="CONSOLIDATED",
                previous_scope="CONSOLIDATED",
                fy_currency="CNY",
                current_currency="CNY",
                previous_currency="CNY",
                current_months=6,
                previous_months=6,
            ),
            D("110"),
        )
        self.assertIsNone(
            derive_ttm(
                fy_previous=D("100"),
                ytd_current=D("40"),
                ytd_previous_comparable=D("30"),
                fy_scope="CONSOLIDATED",
                current_scope="PARENT",
                previous_scope="CONSOLIDATED",
                fy_currency="CNY",
                current_currency="CNY",
                previous_currency="CNY",
                current_months=6,
                previous_months=6,
            )
        )

    def test_annual_scope_or_currency_mismatch_fails_statement_integrity(self) -> None:
        observations = list(annual(year) for year in range(2020, 2026))
        mismatched = observations[2]
        observations[2] = AnnualFinancialObservation(
            fiscal_year=mismatched.fiscal_year,
            available_at=mismatched.available_at,
            attributable_equity_end=mismatched.attributable_equity_end,
            total_equity_end=mismatched.total_equity_end,
            minority_interest_end=mismatched.minority_interest_end,
            parent_net_profit=mismatched.parent_net_profit,
            operating_cash_flow=mismatched.operating_cash_flow,
            capex=mismatched.capex,
            lease_cash_not_already_deducted=mismatched.lease_cash_not_already_deducted,
            currency="USD",
            statement_scope=mismatched.statement_scope,
            traceable=True,
            evidence_refs=mismatched.evidence_refs,
        )
        result = evaluate_general_fcf(self._inputs(tuple(observations)))
        self.assertEqual(
            result.gate("premise.statement_integrity").status,
            ResultStatus.FAIL,
        )


if __name__ == "__main__":
    unittest.main()
