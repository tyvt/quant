"""Probe or publish the official H00985 benchmark against a verified calendar."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from turtle_quant.adapters.csindex_benchmark import fetch_official_benchmark
from turtle_quant.pit.parquet_benchmark import ParquetBenchmarkReader
from turtle_quant.storage.benchmark import expected_benchmark_dates, publish_benchmark_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--calendar-snapshot-id", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--publish", action="store_true", help="Publish an immutable benchmark snapshot")
    args = parser.parse_args()
    expected = expected_benchmark_dates(
        args.storage_root, args.calendar_snapshot_id, args.start, args.end
    )
    if not expected:
        raise ValueError("requested benchmark interval has no trading days")
    fetched = fetch_official_benchmark(
        args.start, args.end, expected_trading_dates=expected
    )
    print(
        "calendar_expected", len(expected),
        "official_rows", len(fetched.observations),
        "first", fetched.observations[0].trade_date,
        "last", fetched.observations[-1].trade_date,
        "response_hash", fetched.source_response_hash,
        "excluded_dates", [item.excluded_date.isoformat() for item in fetched.exclusions],
    )
    if args.publish:
        snapshot_id = publish_benchmark_snapshot(
            args.storage_root,
            fetched,
            calendar_snapshot_id=args.calendar_snapshot_id,
            start=args.start,
            end=args.end,
        )
        reader = ParquetBenchmarkReader(args.storage_root, snapshot_id)
        rows = reader.values("H00985", args.start, args.end)
        print(
            "published_snapshot_id", snapshot_id,
            "reader_rows", len(rows),
            "fetch_time_utc", reader.fetched_at_utc.isoformat(),
            "quality_flags", reader.quality_flags,
        )


if __name__ == "__main__":
    main()
