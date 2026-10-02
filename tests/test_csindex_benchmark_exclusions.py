from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import unittest

from turtle_quant.adapters.csindex_benchmark import (
    EXCLUSION_POLICY,
    parse_official_response,
)
from turtle_quant.storage.snapshot import _canonical_json


FETCHED = datetime(2026, 9, 30, tzinfo=timezone.utc)


def row(day: str, close: float) -> dict[str, object]:
    return {
        "tradeDate": day,
        "indexCode": "H00985",
        "indexNameCnAll": "中证全指全收益指数",
        "indexNameEnAll": "CSI All Share Total Return Index",
        "close": close,
    }


def raw(rows: list[dict[str, object]]) -> bytes:
    return json.dumps({"code": "200", "data": rows}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


class ExplicitBenchmarkExclusionTests(unittest.TestCase):
    def test_both_approved_rows_have_recomputable_row_evidence(self) -> None:
        rows = [
            row("20180618", 5161.74),
            row("20050101", 984.4),
            row("20050104", 980.0),
            row("20180619", 4903.61),
        ]
        body = raw(rows)
        result = parse_official_response(
            body,
            start=date(2005, 1, 1), end=date(2018, 6, 19),
            expected_trading_dates=(date(2005, 1, 4), date(2018, 6, 19)),
            fetched_at_utc=FETCHED,
        )
        self.assertEqual(tuple(item.excluded_date for item in result.exclusions),
                         (date(2005, 1, 1), date(2018, 6, 18)))
        self.assertEqual(result.observations[0].excluded_dates,
                         (date(2005, 1, 1), date(2018, 6, 18)))
        parsed_rows = json.loads(body.decode("utf-8"), parse_float=Decimal)["data"]
        for excluded in result.exclusions:
            offset = next(index for index, source_row in enumerate(parsed_rows)
                          if source_row["tradeDate"] == excluded.excluded_date.strftime("%Y%m%d"))
            row_hash = hashlib.sha256(
                _canonical_json(parsed_rows[offset]).encode("utf-8")
            ).hexdigest()
            self.assertEqual(
                excluded.evidence_ref,
                f"csindex_official_index_perf_v1:{hashlib.sha256(body).hexdigest()}:"
                f"data[{offset}]:{row_hash}",
            )

    def test_approved_2018_row_is_isolated_with_structured_evidence(self) -> None:
        body = raw([
            row("20180615", 5161.13),
            row("20180618", 5161.74),
            row("20180619", 4903.61),
        ])
        result = parse_official_response(
            body,
            start=date(2018, 6, 15), end=date(2018, 6, 19),
            expected_trading_dates=(date(2018, 6, 15), date(2018, 6, 19)),
            fetched_at_utc=FETCHED,
        )
        self.assertEqual(len(result.observations), 2)
        self.assertEqual(len(result.exclusions), 1)
        excluded = result.exclusions[0]
        self.assertEqual(excluded.excluded_date, date(2018, 6, 18))
        self.assertEqual(excluded.official_close, Decimal("5161.74"))
        self.assertEqual(excluded.calendar_verdict, "NON_TRADING_DAY")
        self.assertEqual(excluded.exclusion_reason, "官方接口返回非交易日行，日历与交易所公告一致")
        self.assertEqual(excluded.rule_version, "v1.3.1")
        self.assertIn(hashlib.sha256(body).hexdigest(), excluded.evidence_ref)
        self.assertIn("data[1]", excluded.evidence_ref)
        self.assertEqual(result.observations[0].quality_flags, ("benchmark_excluded_dates",))
        self.assertEqual(result.observations[0].excluded_dates, (date(2018, 6, 18),))
        self.assertEqual(result.observations[0].exclusion_evidence, result.exclusions)
        self.assertEqual(EXCLUSION_POLICY, "explicit_whitelist_v1")

    def test_approved_2005_row_is_isolated(self) -> None:
        result = parse_official_response(
            raw([row("20050101", 984.4), row("20050104", 980.0)]),
            start=date(2005, 1, 1), end=date(2005, 1, 4),
            expected_trading_dates=(date(2005, 1, 4),),
            fetched_at_utc=FETCHED,
        )
        self.assertEqual(tuple(item.excluded_date for item in result.exclusions),
                         (date(2005, 1, 1),))
        self.assertEqual(result.observations[0].trade_date, date(2005, 1, 4))

    def test_approved_exclusion_rows_reject_identity_drift(self) -> None:
        cases = (
            ("20050101", 984.4, date(2005, 1, 1), date(2005, 1, 4)),
            ("20180618", 5161.74, date(2018, 6, 18), date(2018, 6, 19)),
        )
        for day, close, start, trading_day in cases:
            for field_name, bad_value in (
                ("indexCode", "000985"),
                ("indexNameCnAll", "中证全指价格指数"),
                ("indexNameEnAll", "Other Index"),
                ("indexNameEnAll", "CSI All Share Total Return Index "),
            ):
                excluded_row = row(day, close)
                excluded_row[field_name] = bad_value
                with self.subTest(day=day, field=field_name, value=bad_value):
                    with self.assertRaisesRegex(ValueError, "identity drift"):
                        parse_official_response(
                            raw([excluded_row, row(trading_day.strftime("%Y%m%d"), 980.0)]),
                            start=start, end=trading_day,
                            expected_trading_dates=(trading_day,),
                            fetched_at_utc=FETCHED,
                        )

    def test_approved_exclusion_rows_require_all_identity_fields(self) -> None:
        cases = (
            ("20050101", 984.4, date(2005, 1, 1), date(2005, 1, 4)),
            ("20180618", 5161.74, date(2018, 6, 18), date(2018, 6, 19)),
        )
        for day, close, start, trading_day in cases:
            for field_name in ("indexCode", "indexNameCnAll", "indexNameEnAll"):
                excluded_row = row(day, close)
                del excluded_row[field_name]
                with self.subTest(day=day, missing_field=field_name):
                    with self.assertRaisesRegex(ValueError, "identity drift"):
                        parse_official_response(
                            raw([excluded_row, row(trading_day.strftime("%Y%m%d"), 980.0)]),
                            start=start, end=trading_day,
                            expected_trading_dates=(trading_day,),
                            fetched_at_utc=FETCHED,
                        )

    def test_other_nontrading_dates_and_close_drift_still_hard_fail(self) -> None:
        base = [row("20180615", 5161.13), row("20180619", 4903.61)]
        for anomaly in (
            row("20180616", 5161.13),  # weekend pattern is not a rule
            row("20180617", 5161.13),
            row("20180618", 5161.75),  # approved source value changed
        ):
            with self.subTest(anomaly=anomaly), self.assertRaises(ValueError):
                parse_official_response(
                    raw(base + [anomaly]),
                    start=date(2018, 6, 15), end=date(2018, 6, 19),
                    expected_trading_dates=(date(2018, 6, 15), date(2018, 6, 19)),
                    fetched_at_utc=FETCHED,
                )

    def test_whitelisted_date_cannot_be_excluded_if_calendar_says_trading(self) -> None:
        with self.assertRaisesRegex(ValueError, "marked trading"):
            parse_official_response(
                raw([row("20180618", 5161.74)]),
                start=date(2018, 6, 18), end=date(2018, 6, 18),
                expected_trading_dates=(date(2018, 6, 18),),
                fetched_at_utc=FETCHED,
            )

    def test_duplicate_whitelisted_row_still_hard_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate date"):
            parse_official_response(
                raw([row("20180615", 5161.13), row("20180618", 5161.74),
                     row("20180618", 5161.74), row("20180619", 4903.61)]),
                start=date(2018, 6, 15), end=date(2018, 6, 19),
                expected_trading_dates=(date(2018, 6, 15), date(2018, 6, 19)),
                fetched_at_utc=FETCHED,
            )

    def test_historical_evidence_version_is_explicit_and_unknown_versions_fail(self) -> None:
        body = raw([row("20180615", 5161.13), row("20180618", 5161.74),
                    row("20180619", 4903.61)])
        kwargs = {
            "start": date(2018, 6, 15),
            "end": date(2018, 6, 19),
            "expected_trading_dates": (date(2018, 6, 15), date(2018, 6, 19)),
            "fetched_at_utc": FETCHED,
        }
        historical = parse_official_response(
            body, exclusion_rule_version="v1.3.0", **kwargs
        )
        self.assertEqual(historical.exclusions[0].rule_version, "v1.3.0")
        with self.assertRaisesRegex(ValueError, "not approved"):
            parse_official_response(body, exclusion_rule_version="v1.4.0", **kwargs)

    def test_whitelisted_date_outside_requested_range_still_hard_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds requested range"):
            parse_official_response(
                raw([row("20050101", 984.4), row("20050104", 980.0)]),
                start=date(2005, 1, 2), end=date(2005, 1, 4),
                expected_trading_dates=(date(2005, 1, 4),),
                fetched_at_utc=FETCHED,
            )


if __name__ == "__main__":
    unittest.main()
