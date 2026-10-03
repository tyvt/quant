"""Execute frozen gap-inventory Git code, not saved output or current parsers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import SOURCE_PATHS, read_scope, verified_bytes
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash


def replay_frozen_gap_map(scope_path, frozen_directory, code_commit, *, root=ROOT):
    if not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ValueError("gap replay requires a full immutable Git commit ID")
    root = root.resolve()
    raw_scope = scope_path.read_bytes()
    scope = strict_json(raw_scope)
    expected_json = (frozen_directory / "diagnostic-only.json").read_bytes()
    expected_md = (frozen_directory / "diagnostic-only.md").read_bytes()
    report = strict_json(expected_json)
    if (report.get("schema") != "annual-gap-map-diagnostic-v1" or report.get("diagnostic_only") is not True
            or any(report.get(key) is not False for key in ("screening_input_exported", "real_pit_run_authorized",
                                                           "production_reader_ready", "official_selection"))
            or type(report.get("pit_admitted_observation_count")) is not int
            or report["pit_admitted_observation_count"] != 0):
        raise ValueError("not a frozen source-only gap map")
    if (report["logical_content_hash"] != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or expected_json != canonical_bytes(report) + b"\n"):
        raise ValueError("frozen gap-map canonical/hash mismatch")
    if report["scope_sha256"] != hashlib.sha256(raw_scope).hexdigest():
        raise ValueError("frozen gap-map scope mismatch")
    manifest = report["manifest"]
    if (set(manifest["parser_code_sha256"]) != set(SOURCE_PATHS)
            or manifest["parser_code_sha256"] != scope["parser_code_sha256"]
            or manifest["parser_commit"] != scope["parser_commit"]):
        raise ValueError("frozen gap-map parser whitelist mismatch")
    import fitz
    if manifest["pdf_backend"] != {"name": "PyMuPDF", "version": fitz.VersionBind}:
        raise ValueError("frozen gap-map PDF backend mismatch")

    def blob(name, digest=None, *, commit=code_commit):
        raw = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=root)
        if digest is not None and hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("frozen gap replay Git blob mismatch: " + name)
        return raw

    files = {name: blob(name, digest) for name, digest in manifest["parser_code_sha256"].items()}
    for name, digest in manifest["parser_code_sha256"].items():
        if files[name] != blob(name, digest, commit=scope["parser_commit"]):
            raise ValueError("inventory and parser commits disagree")
    files["RULE_SPEC.md"] = blob("RULE_SPEC.md", manifest["rule_sha256"])
    files["scripts/pilots/build_annual_gap_map.py"] = blob("scripts/pilots/build_annual_gap_map.py", manifest["tool_sha256"])
    files["scripts/pilots/capture_annual_holdout.py"] = blob("scripts/pilots/capture_annual_holdout.py", manifest["capture_guard_sha256"])
    files["scripts/pilots/capture_financial_2024_000637.py"] = blob("scripts/pilots/capture_financial_2024_000637.py")
    dependencies = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", code_commit, "turtle_quant"], cwd=root).decode("utf-8").splitlines()
    support = {}
    for name in dependencies:
        if name.startswith("turtle_quant/") and name.endswith(".py") and ".." not in Path(name).parts:
            files[name] = blob(name)
            support[name] = hashlib.sha256(files[name]).hexdigest()
    executable_paths = set(files)

    def asset(name, digest):
        if name in executable_paths:
            raise ValueError("gap replay asset collides with executable code")
        raw = verified_bytes(root, name, digest)
        if name in files and files[name] != raw:
            raise ValueError("conflicting gap replay asset bytes")
        files[name] = raw
        return raw

    for ref in scope["inputs"]:
        parsed = read_scope(asset(ref["path"], ref["sha256"]))
        for source in parsed["sources"]:
            asset(source["pdf_path"], source["pdf_sha256"])
        for parent in parsed["reference_reports"]:
            asset(parent["path"], parent["sha256"])

    # The frozen guard invokes read-only git show. It reads original objects,
    # while its working code/source bytes come solely from the temporary root.
    git_dir = subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"], cwd=root).decode("utf-8").strip()
    with tempfile.TemporaryDirectory(prefix="annual-gap-frozen-replay-") as directory:
        temporary_root = Path(directory).resolve()
        for name, raw in files.items():
            target = temporary_root / name
            if target.resolve() != target.absolute() or not target.resolve().is_relative_to(temporary_root):
                raise ValueError("unsafe frozen gap replay path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
        source_path = temporary_root / "frozen-gap-map-scope.json"
        with source_path.open("xb") as stream:
            stream.write(raw_scope)
        output = temporary_root / "generated"
        env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "GIT_INDEX_FILE")}
        env.update(GIT_DIR=git_dir, GIT_WORK_TREE=str(temporary_root))
        completed = subprocess.run([sys.executable, "-X", "utf8", str(temporary_root / "scripts/pilots/build_annual_gap_map.py"),
                                    "--scope", str(source_path), "--output", str(output)], cwd=temporary_root,
                                   env=env, capture_output=True, timeout=45)
        if completed.returncode:
            raise ValueError("frozen gap CLI failed: " + completed.stderr.decode("utf-8", errors="replace"))
        actual_json, actual_md = ((output / name).read_bytes() for name in ("diagnostic-only.json", "diagnostic-only.md"))
        if actual_json != expected_json or actual_md != expected_md:
            raise ValueError("frozen gap-map execution not byte-identical")
    return {"code_commit": code_commit, "verified_parser_files": len(SOURCE_PATHS),
            "json_sha256": hashlib.sha256(actual_json).hexdigest(),
            "markdown_sha256": hashlib.sha256(actual_md).hexdigest(), "support_code_sha256": support,
            "report": strict_json(actual_json)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--frozen-directory", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    result = replay_frozen_gap_map(args.scope, args.frozen_directory, args.code_commit)
    print(json.dumps({key: value for key, value in result.items() if key not in ("report", "support_code_sha256")}))


if __name__ == "__main__":
    main()
