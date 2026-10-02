"""Offline SHA-256 inventory and binary-safe Git blob verification.

An inventory detects loss or mutation; it cannot restore excluded raw data.
Capture is explicit, refuses overwrite, and checks the already reviewed baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/audits/storage-snapshot-manifest-2026-10-02.json"
RULE_SHA256 = "db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812"
SNAPSHOT_SHA256 = "2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270"
PROTECTED_PATHS = (
    "RULE_SPEC.md",
    "docs/releases/v1.3.1.md",
    "docs/releases/v1.3.1-identity-reattest.md",
    "docs/releases/v1.3.2.md",
    "turtle_quant/adapters/csindex_benchmark.py",
    "turtle_quant/pit/parquet_benchmark.py",
    "scripts/pilots/build_limited_diagnostics.py",
    "scripts/pilots/verify_minority_equity_000637.py",
    "docs/data-pilots/2026-10-02-limited-diagnostic-scope.json",
    "docs/data-pilots/2026-10-02-minority-equity-000637-inputs.json",
) + tuple(
    f"docs/data-pilots/limited-diagnostics-2026-10-02/{sample}-diagnostic-only.{ext}"
    for sample in ("shares-000858", "buybacks-600519", "cashflow-000637", "financial-002570")
    for ext in ("json", "md")
) + tuple(
    f"docs/data-pilots/minority-equity-000637-2026-10-02/diagnostic-only.{ext}"
    for ext in ("json", "md")
)


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path):
    return json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError(f"nonfinite JSON number: {value}")))


def relative_file(root: Path, relative: str) -> Path:
    path = root / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
            or path.resolve() != path.absolute() or not path.resolve().is_relative_to(root.resolve())):
        raise ValueError(f"unsafe or linked inventory path: {relative}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_inventory(root: Path) -> list[dict]:
    directory = root / "storage/snapshots"
    if not directory.is_dir():
        raise FileNotFoundError(f"required local snapshots absent: {directory}")
    rows = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            rows.append({"path": relative, "hash": sha256_file(relative_file(root, relative))})
    return rows


def inventory_sha256(rows: list[dict]) -> str:
    # Keep the pre-Git PowerShell inventory encoding: path precedes hash, no key sort.
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def capture_manifest(root: Path) -> dict:
    rows = snapshot_inventory(root)
    aggregate = inventory_sha256(rows)
    if len(rows) != 538 or aggregate != SNAPSHOT_SHA256:
        raise ValueError("snapshots differ from the reviewed 538-file baseline")
    protected = [{"path": path, "sha256": sha256_file(relative_file(root, path))}
                 for path in PROTECTED_PATHS]
    if protected[0]["sha256"] != RULE_SHA256:
        raise ValueError("RULE_SPEC differs from the approved v1.3.2 baseline")
    return {
        "schema_version": "workspace_integrity_inventory_v1",
        "baseline_date": "2026-10-02",
        "scope": "existing_production_snapshots_and_frozen_governance_diagnostics",
        "file_count": len(rows), "inventory_sha256": aggregate,
        "inventory_encoding": "UTF-8 compact JSON array; entries ordered by path; keys path,hash",
        "files": rows, "protected_files": protected,
        "not_a_backup": True,
        "raw_pdf_capture_inventory_included": False,
        "note": "538 个生产快照文件；不包含所有 storage/raw PDF。清单可检出变化，不能恢复数据。",
    }


def verify_manifest(root: Path, manifest: dict) -> dict:
    actual = capture_manifest(root)
    if manifest != actual:
        raise ValueError("storage/protected-file inventory drift or altered manifest")
    return {"file_count": actual["file_count"], "inventory_sha256": actual["inventory_sha256"],
            "rule_sha256": actual["protected_files"][0]["sha256"]}


def git_bytes(root: Path, *args: str) -> bytes:
    # Never pipe Git blobs through PowerShell text decoding/re-encoding.
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60).stdout


def verify_git_blobs(root: Path, paths, revision: str = "HEAD") -> dict:
    commit = git_bytes(root, "rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii").strip()
    checks = []
    for relative in paths:
        raw = relative_file(root, relative).read_bytes()
        blob = git_bytes(root, "show", f"{commit}:{relative}")
        if raw != blob:
            raise ValueError(f"Git blob differs from workspace bytes: {relative}")
        checks.append({"path": relative, "sha256": hashlib.sha256(blob).hexdigest()})
    return {"commit": commit, "verified_files": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / MANIFEST)
    parser.add_argument("--capture", action="store_true", help="create a NEW inventory only")
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    if args.capture:
        report = capture_manifest(ROOT)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        with args.manifest.open("xb") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n")
        summary = {"file_count": report["file_count"], "inventory_sha256": report["inventory_sha256"]}
    else:
        report = read_json(args.manifest)
        summary = verify_manifest(ROOT, report)
        summary["git"] = verify_git_blobs(ROOT, [item["path"] for item in report["protected_files"]],
                                          args.revision)
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
