from datetime import date, datetime, timezone
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from turtle_quant.adapters.csindex_benchmark import parse_official_response
from turtle_quant.pit.parquet_benchmark import ParquetBenchmarkReader
from turtle_quant.storage.benchmark import expected_benchmark_dates, publish_benchmark_snapshot
from turtle_quant.storage.parquet import read_parquet_rows, write_parquet_rows
from turtle_quant.storage.snapshot import IngestConfig, SnapshotSession
from turtle_quant.storage.verification import DomainRevokedError, verify_published_domain


START = date(2026, 9, 1)
END = date(2026, 9, 2)
EXPECTED = (START, END)


def _catalog(root: Path, revocations: dict[str, object] | None = None) -> None:
    path = root / "catalog" / "domain-revocations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "revocations": revocations or {}}), encoding="utf-8")


def _calendar(root: Path) -> str:
    config = IngestConfig(
        ingest_calendar_date=END,
        steps=("calendar",),
        start_date=START,
        end_date=END,
        max_symbols=None,
        board_filter_version="fixture",
        source_provenance_template={"fixture": {"version": "1"}},
    )
    session = SnapshotSession.start(root, config)
    path = session.staging_path / "calendar" / "trade_dates.parquet"
    write_parquet_rows(path, (
        {"exchange": "cn", "date": START.isoformat(), "is_trading_day": True},
        {"exchange": "cn", "date": END.isoformat(), "is_trading_day": True},
    ), sort_keys=("date",))
    session.complete_domain("calendar", files=(path,), row_count=2)
    snapshot_id = session.publish(universe_hash="fixture-calendar", source_descriptors={"fixture": {"version": "1"}})
    _catalog(root)
    return snapshot_id


def _response() -> bytes:
    rows = [
        {"tradeDate": day, "indexCode": "H00985", "indexNameCnAll": "中证全指全收益指数",
         "indexNameEnAll": "CSI All Share Total Return Index", "close": close}
        for day, close in (("20260901", 8105.12), ("20260902", 7998.36))
    ]
    return json.dumps({"code": "200", "msg": "Success", "data": rows},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _publish(root: Path, stamp: datetime) -> tuple[str, str]:
    calendar_id = _calendar(root)
    fetch = parse_official_response(
        _response(), start=START, end=END,
        expected_trading_dates=EXPECTED, fetched_at_utc=stamp,
    )
    benchmark_id = publish_benchmark_snapshot(
        root, fetch, calendar_snapshot_id=calendar_id, start=START, end=END,
    )
    return calendar_id, benchmark_id


class ParquetBenchmarkSnapshotTests(unittest.TestCase):
    def test_excluded_day_is_audited_in_v1_meta_and_reader_results(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            start, end = date(2018, 6, 15), date(2018, 6, 19)
            config = IngestConfig(
                ingest_calendar_date=end,
                steps=("calendar",),
                start_date=start,
                end_date=end,
                max_symbols=None,
                board_filter_version="fixture",
                source_provenance_template={"fixture": {"version": "exclusion"}},
            )
            session = SnapshotSession.start(root, config)
            path = session.staging_path / "calendar" / "trade_dates.parquet"
            dates = tuple(date(2018, 6, day) for day in range(15, 20))
            write_parquet_rows(path, tuple(
                {"exchange": "cn", "date": day.isoformat(),
                 "is_trading_day": day in (start, end)}
                for day in dates
            ), sort_keys=("date",))
            session.complete_domain("calendar", files=(path,), row_count=5)
            calendar_id = session.publish(
                universe_hash="fixture-calendar",
                source_descriptors={"fixture": {"version": "exclusion"}},
            )
            _catalog(root)
            rows = [
                {"tradeDate": day, "indexCode": "H00985",
                 "indexNameCnAll": "中证全指全收益指数",
                 "indexNameEnAll": "CSI All Share Total Return Index", "close": close}
                for day, close in (("20180615", 5161.13),
                                   ("20180618", 5161.74),
                                   ("20180619", 4903.61))
            ]
            body = json.dumps({"code": "200", "data": rows},
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            fetch = parse_official_response(
                body, start=start, end=end,
                expected_trading_dates=(start, end),
                fetched_at_utc=datetime(2026, 9, 30, tzinfo=timezone.utc),
            )
            legacy_fetch = parse_official_response(
                body, start=start, end=end,
                expected_trading_dates=(start, end),
                fetched_at_utc=datetime(2026, 9, 30, tzinfo=timezone.utc),
                exclusion_rule_version="v1.3.0",
            )
            with self.assertRaisesRegex(ValueError, "current exclusion rule version"):
                publish_benchmark_snapshot(
                    root, legacy_fetch, calendar_snapshot_id=calendar_id,
                    start=start, end=end,
                )
            benchmark_id = publish_benchmark_snapshot(
                root, fetch, calendar_snapshot_id=calendar_id,
                start=start, end=end,
            )
            verified = verify_published_domain(root, benchmark_id, "benchmark")
            self.assertEqual(verified.snapshot_quality_flags, ("benchmark_excluded_dates",))
            self.assertEqual(verified.domain_details["benchmark_excluded_dates"], ("2018-06-18",))
            evidence = verified.domain_details["exclusion_evidence"][0]
            self.assertEqual(evidence["excluded_date"], "2018-06-18")
            self.assertEqual(evidence["calendar_verdict"], "NON_TRADING_DAY")
            self.assertEqual(evidence["rule_version"], "v1.3.1")
            self.assertIn("data[1]", evidence["evidence_ref"])
            self.assertEqual(verified.source_provenance["csindex"]["exclusion_policy"],
                             "explicit_whitelist_v1")
            reader = ParquetBenchmarkReader(root, benchmark_id)
            self.assertEqual(reader.exclusion_rule_version, "v1.3.1")
            self.assertEqual(reader.excluded_dates, (date(2018, 6, 18),))
            self.assertEqual(reader.values("H00985", start, end)[0].quality_flags,
                             ("benchmark_excluded_dates",))
            self.assertEqual(reader.values("H00985", end, end)[0].excluded_dates,
                             (date(2018, 6, 18),))
            self.assertEqual(reader.values("H00985", end, end)[0].quality_flags,
                             ("benchmark_excluded_dates",))
            self.assertEqual(reader.values("H00985", end, end)[0].exclusion_evidence,
                             reader.exclusion_evidence)
            meta_path = root / "snapshots" / benchmark_id / "meta.json"
            original_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for variant in (
                "snapshot_flag", "domain_flag", "excluded_dates",
                "exclusion_evidence", "exclusion_policy",
            ):
                damaged = deepcopy(original_meta)
                benchmark_meta = damaged["domains"]["benchmark"]
                if variant == "snapshot_flag":
                    damaged["data_quality_flags"] = []
                elif variant == "domain_flag":
                    benchmark_meta["quality_flags"] = []
                elif variant == "excluded_dates":
                    benchmark_meta["details"]["benchmark_excluded_dates"] = []
                elif variant == "exclusion_evidence":
                    benchmark_meta["details"]["exclusion_evidence"] = []
                else:
                    damaged["source_provenance"]["csindex"]["exclusion_policy"] = "none"
                meta_path.write_text(json.dumps(damaged, ensure_ascii=False),
                                     encoding="utf-8")
                expected_error = (
                    "benchmark exclusion" if variant in ("snapshot_flag", "exclusion_policy")
                    else "snapshot content hash mismatch"
                )
                with self.subTest(variant=variant), self.assertRaisesRegex(
                    ValueError, expected_error
                ):
                    ParquetBenchmarkReader(root, benchmark_id)
            meta_path.write_text(json.dumps(original_meta, ensure_ascii=False),
                                 encoding="utf-8")

    def test_reader_reconstructs_audit_time_from_its_own_snapshot(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            stamp = datetime(2026, 9, 3, 12, 30, tzinfo=timezone.utc)
            calendar_id, benchmark_id = _publish(root, stamp)
            verified = verify_published_domain(root, benchmark_id, "benchmark")
            reader = ParquetBenchmarkReader(root, benchmark_id)
            values = reader.values("H00985", START, END)
            self.assertEqual(len(values), 2)
            self.assertEqual(tuple(value.trade_date for value in values), expected_benchmark_dates(root, calendar_id, START, END))
            self.assertEqual(values[0].fetched_at_utc, stamp)
            self.assertEqual(values[0].source_response_hash, reader.response_hash)
            self.assertEqual(verified.source_provenance["csindex"]["fetch_time_utc"], "2026-09-03T12:30:00Z")
            physical = verified.snapshot_path / "benchmark" / "values.parquet"
            self.assertIn("response_hash", read_parquet_rows(physical)[0])
            self.assertNotIn("fetched_at_utc", read_parquet_rows(physical)[0])
            with self.assertRaisesRegex(ValueError, "exceeds snapshot coverage"):
                reader.values("H00985", START, date(2026, 9, 3))

    def test_same_response_regrabbed_at_different_times_has_same_snapshot_identity(self) -> None:
        with TemporaryDirectory() as first_dir, TemporaryDirectory() as second_dir:
            root_a, root_b = Path(first_dir), Path(second_dir)
            _, snapshot_a = _publish(root_a, datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc))
            _, snapshot_b = _publish(root_b, datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc))
            self.assertEqual(snapshot_a, snapshot_b)
            reader_a = ParquetBenchmarkReader(root_a, snapshot_a)
            reader_b = ParquetBenchmarkReader(root_b, snapshot_b)
            self.assertEqual(reader_a.response_hash, reader_b.response_hash)
            self.assertNotEqual(reader_a.fetched_at_utc, reader_b.fetched_at_utc)
            self.assertEqual(reader_a.values("H00985", START, END)[0].fetched_at_utc,
                             reader_a.fetched_at_utc)
            self.assertEqual(reader_b.values("H00985", START, END)[0].fetched_at_utc,
                             reader_b.fetched_at_utc)

    def test_revoked_benchmark_cannot_be_read(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, snapshot_id = _publish(root, datetime(2026, 9, 3, tzinfo=timezone.utc))
            _catalog(root, {snapshot_id: {"benchmark": {"reason": "fixture revocation"}}})
            with self.assertRaises(DomainRevokedError):
                ParquetBenchmarkReader(root, snapshot_id)

    def test_missing_snapshot_scoped_audit_timestamp_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, snapshot_id = _publish(root, datetime(2026, 9, 3, tzinfo=timezone.utc))
            meta_path = root / "snapshots" / snapshot_id / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            del meta["source_provenance"]["csindex"]["fetch_time_utc"]
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fetch_time_utc"):
                ParquetBenchmarkReader(root, snapshot_id)

    def test_real_published_cohort_read_only_smoke_when_available(self) -> None:
        root = Path(__file__).resolve().parents[1] / "storage"
        snapshot_id = "snapshot-d9fa4c6d8933fe39"
        if not (root / "snapshots" / snapshot_id / "meta.json").is_file():
            self.skipTest("local immutable H00985 cohort is unavailable")
        reader = ParquetBenchmarkReader(root, snapshot_id)
        self.assertIsNone(reader.exclusion_rule_version)
        self.assertEqual(len(reader.values("H00985", date(2018, 6, 19), date(2026, 9, 24))), 2010)
        recent = reader.values("H00985", date(2026, 9, 1), date(2026, 9, 24))
        self.assertEqual(len(recent), 18)
        self.assertEqual(str(recent[0].close), "8105.12")
        self.assertEqual(str(recent[-1].close), "7907.95")

    def test_real_full_history_snapshot_keeps_exclusions_on_subqueries(self) -> None:
        root = Path(__file__).resolve().parents[1] / "storage"
        snapshot_id = "snapshot-9b72a2666190542a"
        if not (root / "snapshots" / snapshot_id / "meta.json").is_file():
            self.skipTest("local immutable full-history H00985 cohort is unavailable")
        verified = verify_published_domain(root, snapshot_id, "benchmark")
        self.assertEqual(verified.row_count, 5279)
        self.assertEqual(verified.snapshot_quality_flags, ("benchmark_excluded_dates",))
        self.assertEqual(verified.domain_details["raw_row_count"], 5281)
        self.assertEqual(
            verified.domain_details["benchmark_excluded_dates"],
            ("2005-01-01", "2018-06-18"),
        )
        self.assertEqual(len(verified.domain_details["exclusion_evidence"]), 2)
        self.assertEqual(
            tuple(item["rule_version"] for item in verified.domain_details["exclusion_evidence"]),
            ("v1.3.0", "v1.3.0"),
        )
        self.assertEqual(
            verified.source_provenance["csindex"]["exclusion_policy"],
            "explicit_whitelist_v1",
        )
        reader = ParquetBenchmarkReader(root, snapshot_id)
        self.assertEqual(reader.exclusion_rule_version, "v1.3.0")
        full = reader.values("H00985", date(2005, 1, 1), date(2026, 9, 24))
        self.assertEqual(len(full), 5279)
        subrange = reader.values("H00985", date(2020, 1, 1), date(2020, 12, 31))
        self.assertTrue(subrange)
        self.assertEqual(subrange[0].quality_flags, ("benchmark_excluded_dates",))
        self.assertEqual(
            subrange[0].excluded_dates,
            (date(2005, 1, 1), date(2018, 6, 18)),
        )
        self.assertEqual(subrange[0].exclusion_evidence, reader.exclusion_evidence)
        self.assertEqual(len(subrange[0].exclusion_evidence), 2)
        self.assertEqual(
            reader.values("H00985", date(2020, 1, 5), date(2020, 1, 5)),
            (),
        )
        self.assertEqual(reader.quality_flags, ("benchmark_excluded_dates",))
        self.assertEqual(reader.excluded_dates, subrange[0].excluded_dates)
        self.assertEqual(reader.exclusion_evidence, subrange[0].exclusion_evidence)


if __name__ == "__main__":
    unittest.main()
