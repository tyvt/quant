"""Command-line boundary for foundation snapshot synchronization."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.metadata
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from turtle_quant.adapters.baostock_adapter import BaostockAdapter
from turtle_quant.adapters.chinabond import (
    CHINABOND_HISTORY_ENDPOINT,
    ChinabondAdapter,
)
from turtle_quant.adapters.stockdb_rd import StockDBLocalAdapter

from .snapshot import IngestConfig, sha256_file
from .sync import FOUNDATION_STEP_ORDER, FoundationSyncRunner


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected ISO date YYYY-MM-DD, got {value!r}"
        ) from exc


def _parse_unit_decimal(value: str) -> Decimal:
    try:
        converted = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(
            "expected a decimal ratio in [0, 1]"
        ) from exc
    if not Decimal("0") <= converted <= Decimal("1"):
        raise argparse.ArgumentTypeError(
            "expected a decimal ratio in [0, 1]"
        )
    return converted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize foundation raw data into an immutable local snapshot."
        )
    )
    parser.add_argument("--start-date", required=True, type=_parse_date)
    parser.add_argument("--end-date", required=True, type=_parse_date)
    parser.add_argument("--ingest-calendar-date", type=_parse_date)
    parser.add_argument(
        "--steps",
        default=",".join(FOUNDATION_STEP_ORDER),
        help="comma-separated foundation domains",
    )
    parser.add_argument("--max-symbols", type=int)
    parser.add_argument(
        "--minimum-market-coverage",
        type=_parse_unit_decimal,
        default=Decimal("0.98"),
    )
    parser.add_argument("--batch-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--parent-security-master-snapshot",
        help="reuse a verified security_master domain from this snapshot",
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path("storage"),
    )
    parser.add_argument(
        "--stockdb-pybao",
        type=Path,
        default=Path(r"d:\repository\stockdb\pybao"),
    )
    return parser


def build_config_from_namespace(
    namespace: argparse.Namespace,
    *,
    source_descriptors: Mapping[str, object],
    shanghai_today: date,
) -> IngestConfig:
    steps = tuple(
        step.strip()
        for step in str(namespace.steps).split(",")
        if step.strip()
    )
    if namespace.max_symbols == 0 and set(steps).intersection(
        {"market_daily", "adjustment_factors"}
    ):
        raise ValueError(
            "--max-symbols 0 requires omitting per-security market/factor steps"
        )
    ingest_day = namespace.ingest_calendar_date or shanghai_today
    return IngestConfig(
        ingest_calendar_date=ingest_day,
        steps=steps,
        start_date=namespace.start_date,
        end_date=namespace.end_date,
        max_symbols=namespace.max_symbols,
        board_filter_version="main_board_v1",
        source_provenance_template=source_descriptors,
        minimum_market_coverage=namespace.minimum_market_coverage,
    )


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _source_tree_hash(repository_root: Path) -> str:
    digest = hashlib.sha256()
    candidates = list((repository_root / "turtle_quant").rglob("*.py"))
    candidates.extend(
        path
        for path in (
            repository_root / "scripts" / "sync_local_data.py",
            repository_root / "RULE_SPEC.md",
            repository_root / "docs" / "data-ingestion-contract.md",
            repository_root / "pyproject.toml",
        )
        if path.is_file()
    )
    for path in sorted(candidates, key=lambda item: item.as_posix()):
        relative = path.relative_to(repository_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_source_descriptors(
    *,
    pybao_path: Path,
    steps: tuple[str, ...],
) -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[2]
    sdk_path = pybao_path / "stock_sdk.py"
    stockdb_descriptor: dict[str, object] = {
        "interface": "local_rd",
        "endpoint": "127.0.0.1:7899",
    }
    if sdk_path.is_file():
        stockdb_descriptor["sdk_sha256"] = sha256_file(sdk_path)
    descriptors: dict[str, object] = {
        "turtle_quant": {
            "version": _distribution_version("turtle-quant"),
            "snapshot_schema": 1,
            "source_tree_sha256": _source_tree_hash(repository_root),
        },
        "pyarrow": {
            "version": _distribution_version("pyarrow"),
            "parquet_version": "2.6",
            "compression": "zstd",
        },
        "baostock": {
            "distribution_version": _distribution_version("baostock"),
            "module_version": _baostock_module_version(),
        },
        "stockdb_rd": stockdb_descriptor,
    }
    if "chinabond_10y" in steps:
        descriptors["chinabond"] = {
            "endpoint": CHINABOND_HISTORY_ENDPOINT,
            "curve_id": "ycqx",
            "tenor": "10Y",
        }
        descriptors["requests"] = {
            "version": _distribution_version("requests")
        }
    return descriptors


def _baostock_module_version() -> str:
    try:
        import baostock
    except ImportError:
        return "unavailable"
    return str(getattr(baostock, "__version__", "unknown"))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    provisional_steps = tuple(
        step.strip()
        for step in str(namespace.steps).split(",")
        if step.strip()
    )
    descriptors = build_source_descriptors(
        pybao_path=namespace.stockdb_pybao,
        steps=provisional_steps,
    )
    if namespace.parent_security_master_snapshot:
        parent_meta_path = (
            namespace.storage_root
            / "snapshots"
            / namespace.parent_security_master_snapshot
            / "meta.json"
        )
        if not parent_meta_path.is_file():
            parser.error("parent security-master snapshot is not published")
        import json

        parent_meta = json.loads(parent_meta_path.read_text("utf-8"))
        descriptors["parent_security_master"] = {
            "snapshot_id": namespace.parent_security_master_snapshot,
            "content_hash": parent_meta.get("content_hash"),
        }
    config = build_config_from_namespace(
        namespace,
        source_descriptors=descriptors,
        shanghai_today=datetime.now(
            ZoneInfo("Asia/Shanghai")
        ).date(),
    )
    stockdb = StockDBLocalAdapter(pybao_path=namespace.stockdb_pybao)
    def run_with_baostock(baostock: object) -> str:
        runner = FoundationSyncRunner(
            storage_root=namespace.storage_root,
            config=config,
            stockdb=stockdb,
            baostock=baostock,
            chinabond=ChinabondAdapter(),
            progress=lambda message: print(message, flush=True),
            parent_security_master_snapshot=(
                namespace.parent_security_master_snapshot
            ),
        )
        return runner.run(
            batch_id=namespace.batch_id,
            resume=namespace.resume,
        )

    needs_baostock = (
        namespace.parent_security_master_snapshot is None
        or "calendar" in provisional_steps
    )
    if needs_baostock:
        with BaostockAdapter() as baostock:
            snapshot_id = run_with_baostock(baostock)
    else:
        snapshot_id = run_with_baostock(None)
    print(snapshot_id)
    return 0
