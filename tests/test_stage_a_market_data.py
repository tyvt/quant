from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
import unittest

from turtle_quant.core.market_data import (
    AdjustmentFactorObservation,
    CoverageIssue,
    CoverageIssueType,
    PriceBarSeries,
    RateObservation,
    RawPriceBar,
    cumulative_factor_on,
)
from turtle_quant.core.types import NonNegativePct


D = Decimal


def _bar(**overrides: object) -> RawPriceBar:
    values: dict[str, object] = {
        "security_id": "sh.600000",
        "trade_date": date(2024, 1, 2),
        "open": D("10"),
        "high": D("11"),
        "low": D("9"),
        "close": D("10.5"),
        "volume": D("100"),
        "amount": D("1050"),
        "paused": False,
        "evidence_ref": "fixture:bar:2024-01-02",
        "source_row_hash": "a" * 64,
    }
    values.update(overrides)
    return RawPriceBar(**values)  # type: ignore[arg-type]


class StageAMarketDataTypeTests(unittest.TestCase):
    def test_raw_bar_is_immutable_decimal_and_preserves_unknown_fields(self) -> None:
        bar = _bar(paused=None, evidence_ref=None, source_row_hash=None)

        self.assertIsNone(bar.paused)
        self.assertIsNone(bar.evidence_ref)
        self.assertEqual(bar.adjust_type, "RAW")
        with self.assertRaises(FrozenInstanceError):
            bar.close = D("99")  # type: ignore[misc]

    def test_raw_bar_rejects_noncanonical_or_invalid_values(self) -> None:
        cases = (
            ({"security_id": "600000.SH"}, "canonical"),
            ({"trade_date": "2024-01-02"}, "trade_date"),
            ({"close": D("NaN")}, "finite"),
            ({"open": D("-1")}, "non-negative"),
            ({"volume": D("-1")}, "non-negative"),
            ({"paused": 0}, "paused"),
            ({"evidence_ref": ""}, "evidence_ref"),
            ({"source_row_hash": "bad"}, "SHA-256"),
            ({"adjust_type": "QFQ"}, "RAW"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(
                ValueError, message
            ):
                _bar(**overrides)

    def test_price_series_derives_coverage_and_normalizes_immutable_inputs(self) -> None:
        issue = CoverageIssue(
            issue_type=CoverageIssueType.PAUSE_STATUS_UNKNOWN,
            security_id="sh.600000",
            date_range=(date(2024, 1, 2), date(2024, 1, 2)),
            evidence_ref="fixture:bar:2024-01-02",
        )
        series = PriceBarSeries(
            bars=[_bar(paused=None)],  # type: ignore[arg-type]
            coverage_issues=[issue],  # type: ignore[arg-type]
            quality_flags=["z", "a", "z"],  # type: ignore[arg-type]
        )

        self.assertEqual(series.bars, (_bar(paused=None),))
        self.assertEqual(series.coverage_issues, (issue,))
        self.assertEqual(series.quality_flags, ("a", "z"))
        self.assertFalse(series.coverage_complete)
        self.assertTrue(PriceBarSeries((), (), ()).coverage_complete)
        with self.assertRaises(FrozenInstanceError):
            series.bars = ()  # type: ignore[misc]

    def test_issue_and_series_reject_ambiguous_ranges_or_ordering(self) -> None:
        with self.assertRaisesRegex(ValueError, "date_range"):
            CoverageIssue(
                CoverageIssueType.MISSING_BAR,
                "sh.600000",
                (date(2024, 1, 3), date(2024, 1, 2)),
                None,
            )
        with self.assertRaisesRegex(ValueError, "sorted"):
            PriceBarSeries(
                (_bar(trade_date=date(2024, 1, 3)), _bar()),
                (),
                (),
            )

    def test_cumulative_factor_uses_one_as_of_visible_set_and_latest_revision(self) -> None:
        observations = (
            AdjustmentFactorObservation(
                "sh.600000",
                date(2024, 1, 3),
                date(2024, 1, 3),
                D("2"),
                "stockdb_cum",
                "fixture:factor:v1",
                "1" * 64,
            ),
            AdjustmentFactorObservation(
                "sh.600000",
                date(2024, 1, 3),
                date(2024, 1, 5),
                D("2.1"),
                "stockdb_cum",
                "fixture:factor:v2",
                "2" * 64,
            ),
        )

        self.assertEqual(
            cumulative_factor_on(
                observations,
                security_id="sh.600000",
                day=date(2024, 1, 2),
                as_of=date(2024, 1, 5),
            ),
            D("1"),
        )
        self.assertEqual(
            cumulative_factor_on(
                observations,
                security_id="sh.600000",
                day=date(2024, 1, 3),
                as_of=date(2024, 1, 4),
            ),
            D("2"),
        )
        self.assertEqual(
            cumulative_factor_on(
                observations,
                security_id="sh.600000",
                day=date(2024, 1, 3),
                as_of=date(2024, 1, 5),
            ),
            D("2.1"),
        )

    def test_cumulative_factor_rejects_conflicting_ordering_key(self) -> None:
        common = {
            "security_id": "sh.600000",
            "ex_date": date(2024, 1, 3),
            "available_at": date(2024, 1, 4),
            "factor_source": "stockdb_cum",
            "evidence_ref": "fixture:factor",
        }
        observations = (
            AdjustmentFactorObservation(
                cumulative_factor=D("2"), source_row_hash="1" * 64, **common
            ),
            AdjustmentFactorObservation(
                cumulative_factor=D("3"), source_row_hash="2" * 64, **common
            ),
        )
        with self.assertRaisesRegex(ValueError, "conflicting"):
            cumulative_factor_on(
                observations,
                security_id="sh.600000",
                day=date(2024, 1, 3),
                as_of=date(2024, 1, 4),
            )

    def test_rate_observation_keeps_percentage_units_and_traceability(self) -> None:
        observation = RateObservation(
            series="CN_GOVT_10Y_YIELD_PCT",
            obs_date=date(2024, 1, 5),
            available_at=date(2024, 1, 8),
            value=NonNegativePct("2.5"),
            curve_id="ycqx",
            curve_name="中债国债收益率曲线",
            tenor="10Y",
            evidence_ref="fixture:rate",
            source_row_hash="f" * 64,
        )

        self.assertEqual(observation.value.value, D("2.5"))
        with self.assertRaisesRegex(ValueError, "available_at"):
            RateObservation(
                series="CN_GOVT_10Y_YIELD_PCT",
                obs_date=date(2024, 1, 8),
                available_at=date(2024, 1, 5),
                value=NonNegativePct("2.5"),
                curve_id="ycqx",
                curve_name="中债国债收益率曲线",
                tenor="10Y",
                evidence_ref="fixture:rate",
                source_row_hash="f" * 64,
            )


if __name__ == "__main__":
    unittest.main()
