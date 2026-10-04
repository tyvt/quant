"""Execute whitelisted frozen, indexed annual pilots without checkout or network.

Both the private report and its public projection must be reproduced by the old
CLI, not by returning saved output. Only verified code and input bytes enter an
isolated temporary workspace. No changes to existing reports or Git history.
"""

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

TOOLS = {"annual-lease-label-assessment-v1": "scripts/pilots/assess_annual_lease_labels.py",
         "annual-audit-block-diagnostic-v1": "scripts/pilots/build_annual_audit_blocks.py",
         "annual-lease-label-regression-v1": "scripts/pilots/build_annual_lease_label_regression.py",
         "annual-lease-continuation-assessment-v1": "scripts/pilots/assess_annual_lease_continuation.py",
         "annual-lease-continuation-regression-v1": "scripts/pilots/build_annual_lease_continuation_regression.py",
         "annual-lease-bare-regression-v1": "scripts/pilots/build_annual_lease_bare_regression.py",
         "annual-note-suffix-regression-v1": "scripts/pilots/build_annual_note_suffix_regression.py",
         "annual-note-dunhao-subitem-regression-v1": "scripts/pilots/build_annual_note_suffix_regression.py"}
SUPPORT = ("scripts/pilots/assess_annual_audit_narratives.py",
           "scripts/pilots/capture_annual_holdout.py",
           "scripts/pilots/capture_financial_2024_000637.py")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def validated_report(raw):
    report = strict_json(raw)
    if (not isinstance(report, dict) or report.get("schema") not in TOOLS
            or raw != canonical_bytes(report) + b"\n"
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or report.get("diagnostic_only") is not True
            or any(report.get(k) is not False for k in ("screening_input_exported", "real_pit_run_authorized", "production_reader_ready", "official_selection"))
            or type(report.get("pit_admitted_observation_count")) is not int
            or report["pit_admitted_observation_count"] != 0 or report.get("diagnostic_available_at") is not None):
        raise ValueError("not a canonical indexed source-only annual pilot")
    return report


def replay_indexed_pilot(scope_path, private_path, public_path, code_commit, *, root=ROOT):
    if not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ValueError("indexed replay requires a full immutable Git commit ID")
    root = root.resolve()
    scope_raw, expected_raw, expected_index = scope_path.read_bytes(), private_path.read_bytes(), public_path.read_bytes()
    report = validated_report(expected_raw)
    scope, index, manifest = strict_json(scope_raw), strict_json(expected_index), report["manifest"]
    if report["scope_sha256"] != digest(scope_raw):
        raise ValueError("indexed replay scope hash mismatch")
    if (expected_index != canonical_bytes(index) + b"\n"
            or index.get("logical_content_hash") != content_hash({k: v for k, v in index.items() if k != "logical_content_hash"})
            or index.get("private_report_file_sha256", index.get("private_report_sha256")) != digest(expected_raw)):
        raise ValueError("indexed replay public/private identity mismatch")
    if set(manifest["parser_code_sha256"]) != set(SOURCE_PATHS):
        raise ValueError("indexed replay parser whitelist mismatch")
    import fitz
    backend = manifest.get("pdf_backend_version", manifest.get("pdf_backend", {}).get("version"))
    if backend != fitz.VersionBind or manifest.get("python_version", sys.version.split()[0]) != sys.version.split()[0]:
        raise ValueError("indexed replay backend/Python version mismatch")

    def blob(name, expected=None):
        raw = subprocess.check_output(["git", "show", f"{code_commit}:{name}"], cwd=root)
        if expected is not None and digest(raw) != expected:
            raise ValueError("indexed replay Git blob mismatch: " + name)
        return raw

    files = {p: blob(p, sha) for p, sha in manifest["parser_code_sha256"].items()}
    tool = TOOLS[report["schema"]]
    files[tool] = blob(tool, manifest["tool_sha256"])
    files["RULE_SPEC.md"] = blob("RULE_SPEC.md", manifest["rule_sha256"])
    for p in SUPPORT:
        files[p] = blob(p, manifest.get("support_code_sha256", {}).get(p))
    extra = ()
    if report["schema"] == "annual-lease-label-regression-v1":
        extra = ("scripts/pilots/assess_annual_lease_labels.py",)
    elif report["schema"] == "annual-lease-continuation-assessment-v1":
        extra = ("scripts/pilots/assess_annual_lease_labels.py", "scripts/pilots/build_annual_lease_label_regression.py")
    elif report["schema"] == "annual-lease-continuation-regression-v1":
        extra = ("scripts/pilots/assess_annual_lease_labels.py", "scripts/pilots/build_annual_lease_label_regression.py",
                 "scripts/pilots/assess_annual_lease_continuation.py")
    elif report["schema"] == "annual-lease-bare-regression-v1":
        extra = ("scripts/pilots/assess_annual_lease_labels.py", "scripts/pilots/build_annual_lease_label_regression.py",
                 "scripts/pilots/assess_annual_lease_continuation.py", "scripts/pilots/build_annual_lease_continuation_regression.py")
    elif report["schema"] in ("annual-note-suffix-regression-v1", "annual-note-dunhao-subitem-regression-v1"):
        extra = ("scripts/pilots/assess_annual_lease_labels.py", "scripts/pilots/build_annual_lease_label_regression.py",
                 "scripts/pilots/assess_annual_lease_continuation.py", "scripts/pilots/build_annual_lease_continuation_regression.py",
                 "scripts/pilots/build_annual_lease_bare_regression.py")
    for p in extra:
        files[p] = blob(p, manifest["support_code_sha256"][p])
    if report["schema"] == "annual-audit-block-diagnostic-v1":
        p = "scripts/pilots/export_annual_audit_index.py"
        files[p] = blob(p)
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", code_commit, "turtle_quant"], cwd=root).decode("utf-8").splitlines()
    for name in names:
        if name.startswith("turtle_quant/") and name.endswith(".py") and ".." not in Path(name).parts:
            files[name] = blob(name)
    executable = set(files)

    def asset(ref):
        name = ref["path"]
        if name in executable:
            raise ValueError("indexed replay asset collides with executable code")
        raw = verified_bytes(root, name, ref["sha256"])
        if name in files and files[name] != raw:
            raise ValueError("conflicting indexed replay asset")
        files[name] = raw
        return raw

    if report["schema"] in ("annual-lease-label-assessment-v1", "annual-lease-continuation-assessment-v1"):
        parent = strict_json(asset(scope["input_refs_scope"]))
        if report["schema"] == "annual-lease-continuation-assessment-v1":
            asset(scope["baseline_private_report"])
            asset(scope["baseline_public_index"])
    elif report["schema"] == "annual-lease-label-regression-v1":
        old_scope = strict_json(asset(scope["assessment_scope"]))
        parent = strict_json(asset(old_scope["input_refs_scope"]))
        asset(scope["baseline_private_report"])
        asset(scope["baseline_public_index"])
    elif report["schema"] == "annual-lease-continuation-regression-v1":
        parent = strict_json(asset(scope["input_refs_scope"]))
        for name in ("baseline_private_report", "baseline_public_index", "assessment_scope",
                     "assessment_private_report", "assessment_public_index"):
            asset(scope[name])
    elif report["schema"] in ("annual-lease-bare-regression-v1", "annual-note-suffix-regression-v1",
                              "annual-note-dunhao-subitem-regression-v1"):
        parent = strict_json(asset(scope["input_refs_scope"]))
        asset(scope["baseline_private_report"])
        asset(scope["baseline_public_index"])
    else:
        parent = scope
    if parent["inputs"] != manifest.get("input_scopes") or parent["as_of"] != report["as_of"]:
        raise ValueError("indexed replay source scope identity mismatch")
    for ref in parent["inputs"]:
        inputs = read_scope(asset(ref))
        for source in inputs["sources"]:
            asset({"path": source["pdf_path"], "sha256": source["pdf_sha256"]})
        for reference in inputs["reference_reports"]:
            asset(reference)
    git_dir = subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"], cwd=root).decode("utf-8").strip()
    with tempfile.TemporaryDirectory(prefix="annual-indexed-frozen-") as directory:
        temporary = Path(directory).resolve()
        for relative, raw in files.items():
            target = temporary / relative
            if target.resolve() != target.absolute() or not target.resolve().is_relative_to(temporary):
                raise ValueError("unsafe indexed replay path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
        scope_file, output, projection = temporary / "scope.json", temporary / "storage/generated/report.json", temporary / "docs/data-pilots/generated/index.json"
        with scope_file.open("xb") as stream:
            stream.write(scope_raw)
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")}
        env.update(GIT_DIR=git_dir, GIT_WORK_TREE=str(temporary))
        run = subprocess.run([sys.executable, "-X", "utf8", str(temporary / tool), "--scope", str(scope_file),
                              "--output", str(output), "--public-index", str(projection)],
                             cwd=temporary, env=env, capture_output=True, timeout=60)
        if run.returncode:
            raise ValueError("frozen indexed CLI failed: " + run.stderr.decode("utf-8", errors="replace"))
        actual_raw, actual_index = output.read_bytes(), projection.read_bytes()
        if actual_raw != expected_raw or actual_index != expected_index:
            raise ValueError("frozen indexed execution is not byte-identical")
    return {"code_commit": code_commit, "private_sha256": digest(actual_raw),
            "public_sha256": digest(actual_index), "report": strict_json(actual_raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--private-report", type=Path, required=True)
    parser.add_argument("--public-index", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    result = replay_indexed_pilot(args.scope, args.private_report, args.public_index, args.code_commit)
    print({k: v for k, v in result.items() if k != "report"})


if __name__ == "__main__":
    main()
