"""Reproduce a frozen source-only annual bundle with its exact Git code bytes.

No checkout, network or changes to old artifacts. Only SHA-verified source bytes
and whitelisted code blobs enter an isolated temporary workspace. The old CLI
must reproduce BOTH canonical JSON and Markdown byte-for-byte. The installed
PDF backend must match the frozen manifest; determinism does not prove PIT.
"""

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
from scripts.screening.contracts import content_hash


def replay_frozen_bundle(scope_path, frozen_directory, code_commit, *, root=ROOT):
    if not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ValueError("replay requires a complete immutable Git commit ID")
    root = root.resolve()
    raw_scope = scope_path.read_bytes()
    scope = read_scope(raw_scope)
    expected_json = (frozen_directory / "diagnostic-only.json").read_bytes()
    expected_md = (frozen_directory / "diagnostic-only.md").read_bytes()
    expected = strict_json(expected_json)
    if (expected.get("schema") != "annual-source-bundle-diagnostic-v1"
            or expected.get("diagnostic_only") is not True
            or expected.get("production_reader_ready") is not False
            or expected.get("real_pit_run_authorized") is not False
            or type(expected.get("pit_admitted_observation_count")) is not int
            or expected["pit_admitted_observation_count"] != 0):
        raise ValueError("not a frozen source-only report")
    if expected["logical_content_hash"] != content_hash({k: v for k, v in expected.items()
                                                       if k != "logical_content_hash"}):
        raise ValueError("frozen logical content hash mismatch")
    manifest = expected["manifest"]
    if manifest["scope_sha256"] != hashlib.sha256(raw_scope).hexdigest():
        raise ValueError("frozen scope identity mismatch")
    if set(manifest["code_sha256"]) != set(SOURCE_PATHS):
        raise ValueError("replay code set is not the explicit annual CLI whitelist")
    import fitz
    if manifest["pdf_backend"] != {"name": "PyMuPDF", "version": fitz.VersionBind}:
        raise ValueError("frozen PDF backend version mismatch")

    def git_blob(relative, digest):
        raw = subprocess.check_output(["git", "show", f"{code_commit}:{relative}"], cwd=root)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"frozen Git code/rule hash mismatch: {relative}")
        return raw

    # All source/code checks complete before any historical code is executed.
    files = {name: git_blob(name, digest) for name, digest in manifest["code_sha256"].items()}
    files["RULE_SPEC.md"] = git_blob("RULE_SPEC.md", manifest["rule_sha256"])
    # The old serialization module imports dataclass definitions even though
    # this source-only CLI never runs their gates. Use their frozen Git Python
    # bytes as well, not current modules or hand-written stubs.
    dependencies = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", code_commit, "turtle_quant"], cwd=root).decode("utf-8").splitlines()
    support_hashes = {}
    for name in dependencies:
        if not name.startswith("turtle_quant/") or not name.endswith(".py") or ".." in Path(name).parts:
            continue
        raw = subprocess.check_output(["git", "show", f"{code_commit}:{name}"], cwd=root)
        files[name] = raw
        support_hashes[name] = hashlib.sha256(raw).hexdigest()
    for source in scope["sources"]:
        if source["pdf_path"] in files:
            raise ValueError("source path collides with frozen executable code")
        files[source["pdf_path"]] = verified_bytes(root, source["pdf_path"], source["pdf_sha256"])
    for ref in scope["reference_reports"]:
        if ref["path"] in files:
            raise ValueError("reference path collides with another replay asset")
        files[ref["path"]] = verified_bytes(root, ref["path"], ref["sha256"])
    with tempfile.TemporaryDirectory(prefix="annual-frozen-replay-") as directory:
        replay_root = Path(directory).resolve()
        for relative, raw in files.items():
            target = replay_root / relative
            if target.resolve() != target.absolute() or not target.resolve().is_relative_to(replay_root):
                raise ValueError("unsafe replay artifact path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
        input_path = replay_root / "frozen-input-scope.json"
        with input_path.open("xb") as stream:
            stream.write(raw_scope)
        output = replay_root / "generated"
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        completed = subprocess.run([sys.executable, "-X", "utf8", str(replay_root / "scripts/extract_annual_report_bundle.py"),
                                    "--scope", str(input_path), "--output", str(output)], cwd=replay_root,
                                   env=env, capture_output=True, timeout=30)
        if completed.returncode:
            raise ValueError("frozen CLI replay failed: " + completed.stderr.decode("utf-8", errors="replace"))
        actual_json, actual_md = ((output / name).read_bytes() for name in ("diagnostic-only.json", "diagnostic-only.md"))
        if actual_json != expected_json or actual_md != expected_md:
            raise ValueError("frozen old-code replay is not byte-identical")
        report = strict_json(actual_json)
    return {"code_commit": code_commit, "logical_content_hash": report["logical_content_hash"],
            "verified_code_files": len(SOURCE_PATHS), "json_sha256": hashlib.sha256(actual_json).hexdigest(),
            "markdown_sha256": hashlib.sha256(actual_md).hexdigest(),
            "support_code_sha256": support_hashes, "report": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, type=Path)
    parser.add_argument("--frozen-directory", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    result = replay_frozen_bundle(args.scope, args.frozen_directory, args.code_commit)
    print(json.dumps({key: value for key, value in result.items() if key not in ("report", "support_code_sha256")}))


if __name__ == "__main__":
    main()
