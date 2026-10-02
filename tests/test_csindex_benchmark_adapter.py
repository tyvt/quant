from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import unittest

from turtle_quant.adapters.csindex_benchmark import (
    ENDPOINT,
    SOURCE_ID,
    build_request,
    fetch_official_benchmark,
    parse_official_response,
)


START = date(2026, 9, 1)
END = date(2026, 9, 2)
EXPECTED = (START, END)
FETCHED = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def row(day: str, close: object) -> dict[str, object]:
    return {
        "tradeDate": day,
        "indexCode": "H00985",
        "indexNameCnAll": "中证全指全收益指数",
        "indexNameEnAll": "CSI All Share Total Return Index",
        "close": close,
    }


def payload(rows: list[dict[str, object]]) -> bytes:
    return json.dumps({"code": "200", "msg": "Success", "data": rows},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse(raw: bytes):
    return parse_official_response(
        raw,
        start=START,
        end=END,
        expected_trading_dates=EXPECTED,
        fetched_at_utc=FETCHED,
    )


class CSIndexBenchmarkAdapterTests(unittest.TestCase):
    def test_exact_official_request_and_raw_response_identity(self) -> None:
        raw = payload([row("20260902", 7998.36), row("20260901", 8105.12)])
        calls = []

        def transport(url, params):
            calls.append((url, dict(params)))
            return raw

        result = fetch_official_benchmark(
            START, END, expected_trading_dates=EXPECTED,
            transport=transport, fetched_at_utc=FETCHED,
        )
        self.assertEqual(calls, [build_request(START, END)])
        self.assertEqual(calls[0][0], ENDPOINT)
        self.assertEqual(result.raw_response, raw)
        self.assertEqual(result.source_response_hash, hashlib.sha256(raw).hexdigest())
        self.assertEqual(tuple(item.trade_date for item in result.observations), EXPECTED)
        self.assertEqual(result.observations[0].close, Decimal("8105.12"))
        self.assertEqual(result.observations[0].fetched_at_utc, FETCHED)
        self.assertIn(SOURCE_ID, result.observations[0].evidence_ref)

    def test_wrong_code_or_name_is_not_silently_accepted(self) -> None:
        for field_name, bad_value in (("indexCode", "000985"),
                                      ("indexNameCnAll", "中证全指价格指数"),
                                      ("indexNameEnAll", "Other Index")):
            rows = [row("20260901", 8105.12), row("20260902", 7998.36)]
            rows[0][field_name] = bad_value
            with self.subTest(field_name=field_name), self.assertRaisesRegex(ValueError, "identity drift"):
                parse(payload(rows))

    def test_missing_identity_fields_hard_fail(self) -> None:
        for field_name in ("indexCode", "indexNameCnAll", "indexNameEnAll"):
            rows = [row("20260901", 8105.12), row("20260902", 7998.36)]
            del rows[0][field_name]
            with self.subTest(missing_field=field_name):
                with self.assertRaisesRegex(ValueError, "identity drift"):
                    parse(payload(rows))

    def test_missing_or_duplicate_date_hard_fails(self) -> None:
        for rows in (
            [row("20260901", 8105.12)],
            [row("20260901", 8105.12), row("20260901", 8105.12)],
        ):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "expected trading calendar"):
                parse(payload(rows))
        with self.assertRaisesRegex(ValueError, "extra=.*2026, 9, 2"):
            parse_official_response(
                payload([row("20260901", 8105.12), row("20260902", 7998.36)]),
                start=START, end=END, expected_trading_dates=(START,),
                fetched_at_utc=FETCHED,
            )

    def test_missing_zero_negative_nonfinite_or_string_close_fails(self) -> None:
        bad_closes = (None, 0, -1, "8105.12", float("nan"))
        for close in bad_closes:
            rows = [row("20260901", close), row("20260902", 7998.36)]
            with self.subTest(close=close), self.assertRaises(ValueError):
                parse(payload(rows))

    def test_failed_api_and_bad_json_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "not successful"):
            parse(b'{"code":"500","data":[]}')
        with self.assertRaisesRegex(ValueError, "UTF-8 JSON"):
            parse(b"not-json")
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse(b'{"code":"200","code":"500","data":[]}')

    def test_invalid_calendar_and_request_range_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_request(END, START)
        with self.assertRaisesRegex(ValueError, "expected_trading_dates"):
            parse_official_response(
                payload([row("20260901", 1), row("20260902", 2)]),
                start=START, end=END,
                expected_trading_dates=(END, START),
                fetched_at_utc=FETCHED,
            )


if __name__ == "__main__":
    unittest.main()
