from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from turtle_quant.adapters.buyback_samples import (
    CumulativeBuybackObservation,
    eventize_cumulative_buyback_observations,
    normalize_buyback_sample,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "buybacks"
    / "moutai-2024-plan-cumulative-observations-v1.json"
)
EXPECTED_FIXTURE_SHA256 = (
    "e406316ffe12dce6d433cfa42448e9db0948026f9c426bcb7c7bde68fe2d1c7f"
)


class BuybackSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_bytes = FIXTURE_PATH.read_bytes()
        cls.fixture = json.loads(cls.fixture_bytes.decode("utf-8"))
        cls.sample = cls.fixture["sample"]
        cls.first_observed_at = datetime.fromisoformat(
            cls.fixture["captured_at_utc"].replace("Z", "+00:00")
        )

    @staticmethod
    def _next_trading_day(announced_on: date) -> date:
        known = {
            date(2025, 4, 8): date(2025, 4, 9),
            date(2025, 5, 8): date(2025, 5, 9),
            date(2025, 5, 17): date(2025, 5, 19),
            date(2025, 6, 5): date(2025, 6, 6),
            date(2025, 7, 3): date(2025, 7, 4),
            date(2025, 8, 5): date(2025, 8, 6),
            date(2025, 8, 30): date(2025, 9, 1),
            date(2026, 4, 17): date(2026, 4, 20),
        }
        return known[announced_on]

    def _normalize(self, sample: dict[str, object] | None = None):
        return normalize_buyback_sample(
            self.sample if sample is None else sample,
            first_observed_at=self.first_observed_at,
            next_trading_day=self._next_trading_day,
        )

    def test_fixture_content_is_pinned_by_sha256(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.fixture_bytes).hexdigest(),
            EXPECTED_FIXTURE_SHA256,
        )

    def test_legacy_last_execution_date_is_only_a_cumulative_cutoff(self) -> None:
        last = self.sample["legal_cumulative_observations"][-1]
        self.assertEqual(self.sample["last_execution_date"], last["cumulative_through"])
        self.assertEqual(last["kind"], "FINAL")
        rows = self._normalize()
        self.assertEqual(rows[-1]["execution_window_end"], last["cumulative_through"])
        self.assertTrue(all(row["exact_execution_date"] is None for row in rows))
        self.assertTrue(all(row["research_eligible"] is False for row in rows))

    def test_eventizes_cumulative_amounts_into_interval_deltas(self) -> None:
        rows = self._normalize()

        self.assertEqual(len(rows), 7)
        self.assertEqual(
            [row["delta_shares"] for row in rows],
            [1315901, 701582, 624646, 667956, 72000, 69600, 475900],
        )
        self.assertEqual(
            [row["delta_amount"] for row in rows],
            [
                Decimal("1948495151.53"),
                Decimal("1090355610.97"),
                Decimal("1011403920.62"),
                Decimal("1049692608.71"),
                Decimal("101580050.00"),
                Decimal("99931703.40"),
                Decimal("698526921.72"),
            ],
        )
        self.assertEqual(sum(row["delta_shares"] for row in rows), 3927585)
        self.assertEqual(
            sum((row["delta_amount"] for row in rows), Decimal("0")),
            Decimal("5999985966.95"),
        )

    def test_preserves_interval_censoring_instead_of_inventing_trade_dates(self) -> None:
        rows = self._normalize()

        self.assertEqual(rows[0]["execution_window_start"], "2025-01-02")
        self.assertIs(rows[0]["execution_window_start_inclusive"], True)
        self.assertEqual(rows[0]["execution_window_end"], "2025-04-07")
        self.assertEqual(rows[1]["execution_window_start"], "2025-04-07")
        self.assertIs(rows[1]["execution_window_start_inclusive"], False)
        self.assertEqual(rows[-1]["execution_window_end"], "2025-08-29")
        self.assertTrue(all(row["exact_execution_date"] is None for row in rows))
        self.assertTrue(all(row["research_eligible"] is False for row in rows))
        self.assertTrue(
            all(
                row["blocking_reasons"]
                == [
                    "exact_execution_date_unavailable",
                    "calendar_year_coverage_unverified",
                ]
                for row in rows
            )
        )

    def test_reconciles_final_provider_row_and_does_not_use_provider_start_as_trade(self) -> None:
        rows = self._normalize()
        final = rows[-1]

        self.assertEqual(final["cumulative_shares"], 3927585)
        self.assertEqual(final["cumulative_amount"], Decimal("5999985966.95"))
        self.assertEqual(final["provider_buyback_start_date"], "2024-09-20")
        self.assertNotEqual(
            final["provider_buyback_start_date"],
            rows[0]["execution_window_start"],
        )
        self.assertEqual(final["provider_latest_announcement_date"], "2025-08-30")

    def test_tracks_event_and_later_cancellation_availability_separately(self) -> None:
        rows = self._normalize()

        self.assertEqual(rows[0]["event_available_at"], "2025-04-09T00:00:00Z")
        self.assertEqual(rows[-1]["event_available_at"], "2025-09-01T00:00:00Z")
        self.assertTrue(
            all(
                row["cancellation_status"] == "VERIFIED_TRUE"
                and row["cancellation_verified_at"]
                == "2026-04-20T00:00:00Z"
                and row["fully_qualified_available_at"]
                == "2026-04-20T00:00:00Z"
                for row in rows
            )
        )
        self.assertTrue(all(row["cancellation_date"] is None for row in rows))

    def test_reconciles_cancelled_shares_with_share_count_bridge(self) -> None:
        rows = self._normalize()

        self.assertTrue(
            all(row["cancelled_shares"] == 3927585 for row in rows)
        )
        self.assertEqual(rows[-1]["pre_cancellation_shares"], 1256197800)
        self.assertEqual(rows[-1]["post_cancellation_shares"], 1252270215)
        self.assertEqual(
            rows[-1]["pre_cancellation_shares"]
            - rows[-1]["post_cancellation_shares"],
            rows[-1]["cancelled_shares"],
        )

    def test_generic_eventization_is_deterministic_and_collapses_duplicates(self) -> None:
        first = CumulativeBuybackObservation(
            security_id="sh.600519",
            plan_id="plan-a",
            cumulative_through=date(2025, 1, 31),
            available_at=datetime(2025, 2, 3, tzinfo=timezone.utc),
            cumulative_shares=10,
            cumulative_amount=Decimal("100"),
            evidence_ref="evidence-a",
        )
        duplicate = CumulativeBuybackObservation(
            security_id="sh.600519",
            plan_id="plan-a",
            cumulative_through=date(2025, 1, 31),
            available_at=datetime(2025, 2, 4, tzinfo=timezone.utc),
            cumulative_shares=10,
            cumulative_amount=Decimal("100"),
            evidence_ref="evidence-b",
        )
        second = CumulativeBuybackObservation(
            security_id="sh.600519",
            plan_id="plan-a",
            cumulative_through=date(2025, 2, 28),
            available_at=datetime(2025, 3, 3, tzinfo=timezone.utc),
            cumulative_shares=15,
            cumulative_amount=Decimal("160"),
            evidence_ref="evidence-c",
        )

        forward = eventize_cumulative_buyback_observations(
            (first, duplicate, second),
            first_execution_date=date(2025, 1, 2),
        )
        reverse = eventize_cumulative_buyback_observations(
            (second, duplicate, first),
            first_execution_date=date(2025, 1, 2),
        )

        self.assertEqual(forward, reverse)
        self.assertEqual(len(forward), 2)
        self.assertEqual(forward[0].evidence_refs, ("evidence-a", "evidence-b"))
        self.assertEqual(forward[1].delta_amount, Decimal("60"))

    def test_rejects_conflicts_regressions_and_cross_source_mismatch(self) -> None:
        base = CumulativeBuybackObservation(
            security_id="sh.600519",
            plan_id="plan-a",
            cumulative_through=date(2025, 1, 31),
            available_at=datetime(2025, 2, 3, tzinfo=timezone.utc),
            cumulative_shares=10,
            cumulative_amount=Decimal("100"),
            evidence_ref="evidence-a",
        )
        conflict = CumulativeBuybackObservation(
            security_id="sh.600519",
            plan_id="plan-a",
            cumulative_through=date(2025, 1, 31),
            available_at=datetime(2025, 2, 4, tzinfo=timezone.utc),
            cumulative_shares=11,
            cumulative_amount=Decimal("101"),
            evidence_ref="evidence-b",
        )
        regression = CumulativeBuybackObservation(
            security_id="sh.600519",
            plan_id="plan-a",
            cumulative_through=date(2025, 2, 28),
            available_at=datetime(2025, 3, 3, tzinfo=timezone.utc),
            cumulative_shares=9,
            cumulative_amount=Decimal("99"),
            evidence_ref="evidence-c",
        )
        with self.assertRaisesRegex(ValueError, "conflicting cumulative"):
            eventize_cumulative_buyback_observations(
                (base, conflict),
                first_execution_date=date(2025, 1, 2),
            )
        with self.assertRaisesRegex(ValueError, "regress"):
            eventize_cumulative_buyback_observations(
                (base, regression),
                first_execution_date=date(2025, 1, 2),
            )

        mismatch = json.loads(json.dumps(self.sample, ensure_ascii=False))
        mismatch["akshare_final_row"]["raw_row"]["已回购金额"] = "1"
        with self.assertRaisesRegex(ValueError, "final.*disagree"):
            self._normalize(mismatch)

        broken_bridge = json.loads(json.dumps(self.sample, ensure_ascii=False))
        broken_bridge["cancellation_confirmation"]["post_cancellation_shares"] = (
            "1252270214"
        )
        with self.assertRaisesRegex(ValueError, "cancellation.*bridge"):
            self._normalize(broken_bridge)


if __name__ == "__main__":
    unittest.main()
