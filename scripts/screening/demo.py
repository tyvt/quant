"""Artificial issuers, financials, evidence and calendar: never actual company data."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from turtle_quant.core.share_capital_policy import ShareCapitalEvidence
from turtle_quant.premise.general_fcf import AnnualFinancialObservation, GeneralFCFInputs
from turtle_quant.strategy.selection import LiquidityDay, UniverseInput
from scripts.screening.contracts import BatchRequest, DATA_KIND, SCHEMA, SecurityFixture


def fixture(security_id: str, as_of: date = date(2026, 5, 1)) -> SecurityFixture:
    # 60 consecutive artificial dates, explicitly NOT an exchange trading calendar.
    dates = tuple(as_of - timedelta(days=59 - index) for index in range(60))
    basic = UniverseInput(
        security_id=security_id, as_of=as_of, expected_liquidity_dates=dates,
        main_board_a_share=True, listing_trading_days=600,
        industry_profile="GENERAL_FCF", eligible_security_status=True,
        market_value=Decimal("6000000000"),
        liquidity_days=tuple(LiquidityDay(day, Decimal("30000000"), True,
                                         f"synthetic:{security_id}:amount:{day}") for day in dates),
        stage_a_coverage_complete=True, shares_known=True,
        share_capital_evidence=ShareCapitalEvidence(
            security_id, as_of, ("A",), 0, as_of, f"synthetic:{security_id}:shares"),
    )
    annuals = tuple(AnnualFinancialObservation(
        fiscal_year=year, available_at=date(year + 1, 4, 30),
        attributable_equity_end=Decimal("100"), total_equity_end=Decimal("100"),
        minority_interest_end=Decimal("0"), parent_net_profit=Decimal("15"),
        operating_cash_flow=Decimal("20"), capex=Decimal("5"),
        lease_cash_not_already_deducted=Decimal("1"), currency="CNY",
        statement_scope="CONSOLIDATED", traceable=True,
        evidence_refs=(f"synthetic:{security_id}:annual:{year}",),
    ) for year in range(2020, 2026))
    financial = GeneralFCFInputs(
        as_of=as_of, industry_profile="GENERAL_FCF", statements_comparable=True,
        latest_audit_unmodified=True, going_concern_uncertainty=False,
        latest_equity=Decimal("100"), annual_observations=annuals,
        cash=Decimal("30"), liquid_assets=Decimal("10"), interest_bearing_debt=Decimal("20"),
    )
    return SecurityFixture(security_id, basic, financial)


def demo_request() -> BatchRequest:
    passed = fixture("sh.600001")
    failed = fixture("sh.600002")
    failed = replace(failed, financial=replace(failed.financial, latest_audit_unmodified=False))
    unknown = fixture("sh.600003")
    annuals = tuple(replace(item, lease_cash_not_already_deducted=None)
                    for item in unknown.financial.annual_observations)
    unknown = replace(unknown, financial=replace(unknown.financial, annual_observations=annuals))
    unsupported = fixture("sh.600004")
    unsupported = replace(unsupported, basic=replace(unsupported.basic, industry_profile="BANK"),
                          financial=None)
    ids = tuple(item.security_id for item in (passed, failed, unknown, unsupported)) + ("sh.600005",)
    return BatchRequest(SCHEMA, DATA_KIND, passed.basic.as_of, ids,
                        (passed, failed, unknown, unsupported))
