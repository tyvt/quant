"""Run the old audit assessment from Git blobs; never apply the current parser."""

from __future__ import annotations

import argparse
import hashlib
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


def replay_frozen_assessment(scope_path, frozen_directory, code_commit, *, root=ROOT):
    if not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ValueError("audit replay requires a full Git commit ID")
    root = root.resolve()
    raw_scope = scope_path.read_bytes()
    scope = strict_json(raw_scope)
    expected = {name: (frozen_directory / name).read_bytes() for name in ("diagnostic-only.json", "diagnostic-only.md")}
    report = strict_json(expected["diagnostic-only.json"])
    if (report.get("schema") != "annual-audit-assessment-diagnostic-v1"
            or report.get("diagnostic_only") is not True
            or any(report.get(k) is not False for k in ("screening_input_exported", "real_pit_run_authorized",
                                                       "production_reader_ready", "official_selection", "narrative_parser_implemented"))
            or type(report.get("pit_admitted_observation_count")) is not int
            or report["pit_admitted_observation_count"] != 0
            or expected["diagnostic-only.json"] != canonical_bytes(report) + b"\n"
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or report["scope_sha256"] != hashlib.sha256(raw_scope).hexdigest()):
        raise ValueError("invalid frozen raw audit assessment")
    manifest = report["manifest"]
    if (set(manifest["parser_code_sha256"]) != set(SOURCE_PATHS)
            or manifest["parser_code_sha256"] != scope["parser_code_sha256"]
            or manifest["parser_commit"] != scope["parser_commit"]):
        raise ValueError("audit replay parser whitelist mismatch")
    import fitz
    if manifest["pdf_backend"] != {"name": "PyMuPDF", "version": fitz.VersionBind}:
        raise ValueError("audit replay PDF backend mismatch")

    def blob(name, digest=None, *, commit=code_commit):
        data = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=root)
        if digest is not None and hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("audit replay code blob mismatch: " + name)
        return data

    files = {name: blob(name, sha) for name, sha in manifest["parser_code_sha256"].items()}
    for name, sha in manifest["parser_code_sha256"].items():
        if files[name] != blob(name, sha, commit=scope["parser_commit"]):
            raise ValueError("audit code and parser commit differ")
    tool = "scripts/pilots/assess_annual_audit_narratives.py"
    files[tool] = blob(tool, manifest["tool_sha256"])
    files["RULE_SPEC.md"] = blob("RULE_SPEC.md", manifest["rule_sha256"])
    for name in ("scripts/pilots/capture_annual_holdout.py", "scripts/pilots/capture_financial_2024_000637.py"):
        files[name] = blob(name)
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", code_commit, "turtle_quant"], cwd=root).decode("utf-8").splitlines()
    for name in names:
        if name.startswith("turtle_quant/") and name.endswith(".py") and ".." not in Path(name).parts:
            files[name] = blob(name)
    executable_paths = set(files)

    def asset(name, sha):
        if name in executable_paths:
            raise ValueError("audit replay asset collides with code")
        data = verified_bytes(root, name, sha)
        if name in files and files[name] != data:
            raise ValueError("audit replay conflicting asset")
        files[name] = data
        return data

    for ref in scope["inputs"]:
        parsed = read_scope(asset(ref["path"], ref["sha256"]))
        for source in parsed["sources"]:
            asset(source["pdf_path"], source["pdf_sha256"])
        for parent in parsed["reference_reports"]:
            asset(parent["path"], parent["sha256"])
    for ref in scope["baseline_reports"]:
        asset(ref["path"], ref["sha256"])
    git_dir = subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"], cwd=root).decode("utf-8").strip()
    with tempfile.TemporaryDirectory(prefix="audit-assessment-frozen-") as folder:
        temporary = Path(folder).resolve()
        for name, data in files.items():
            target = temporary / name
            if target.resolve() != target.absolute() or not target.resolve().is_relative_to(temporary):
                raise ValueError("unsafe audit replay path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
        scope_file = temporary / "scope.json"
        with scope_file.open("xb") as stream:
            stream.write(raw_scope)
        output = temporary / "generated"
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "GIT_INDEX_FILE")}
        env.update(GIT_DIR=git_dir, GIT_WORK_TREE=str(temporary))
        run = subprocess.run([sys.executable, "-X", "utf8", str(temporary / tool), "--scope", str(scope_file),
                              "--output", str(output)], cwd=temporary, env=env, capture_output=True, timeout=45)
        if run.returncode:
            raise ValueError("frozen assessment CLI failed: " + run.stderr.decode("utf-8", errors="replace"))
        actual = {name: (output / name).read_bytes() for name in expected}
        if actual != expected:
            raise ValueError("frozen audit assessment execution not byte-identical")
    return {"code_commit": code_commit, "json_sha256": hashlib.sha256(actual["diagnostic-only.json"]).hexdigest(),
            "markdown_sha256": hashlib.sha256(actual["diagnostic-only.md"]).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--frozen-directory", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    print(replay_frozen_assessment(args.scope, args.frozen_directory, args.code_commit))


if __name__ == "__main__":
    main()
