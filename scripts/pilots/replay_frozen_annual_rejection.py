"""Replay a frozen CLI rejection, not a fabricated normal annual bundle.

Execute SHA-verified Git code in a temporary workspace, without checkout,
network, modifications of old artifacts, or bypass of identity guards.
The nonzero exit status and stdout/stderr must be byte-identical; no normal
JSON/Markdown bundle may be created. This does not prove document PIT.
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
from scripts.screening.contracts import canonical_bytes, content_hash


def replay_frozen_rejection(plan_path, scope_path, rejection_path, *, root=ROOT):
    root = root.resolve()
    plan_raw, scope_raw, frozen_raw = (p.read_bytes() for p in (plan_path, scope_path, rejection_path))
    plan, scope, record = strict_json(plan_raw), read_scope(scope_raw), strict_json(frozen_raw)
    if (record.get("schema") != "annual-source-bundle-rejection-v1"
            or record.get("diagnostic_only") is not True or record.get("normal_bundle_created") is not False
            or record.get("stage") != "DECLARED_DOCUMENT_IDENTITY_REJECTED"
            or record.get("timing_policy") != "UNKNOWN_UNLESS_VERIFIED"
            or record.get("diagnostic_available_at") is not None
            or type(record.get("pit_admitted_observation_count")) is not int
            or record["pit_admitted_observation_count"] != 0
            or any(record.get(key) is not False for key in
                   ("real_pit_run_authorized", "screening_input_exported", "production_reader_ready"))):
        raise ValueError("not a source-only frozen rejection")
    if (frozen_raw != canonical_bytes(record) + b"\n" or record.get("logical_content_hash") !=
            content_hash({k: v for k, v in record.items() if k != "logical_content_hash"})):
        raise ValueError("frozen rejection content identity mismatch")
    manifest, process = record["manifest"], record["process"]
    commit = manifest["parser_commit"]
    if (not re.fullmatch(r"[0-9a-f]{40}", commit) or plan["parser_commit"] != commit
            or manifest["code_sha256"] != plan["parser_code_sha256"]
            or set(manifest["code_sha256"]) != set(SOURCE_PATHS)
            or manifest["scope_sha256"] != hashlib.sha256(scope_raw).hexdigest()
            or manifest["plan_sha256"] != hashlib.sha256(plan_raw).hexdigest()
            or len(scope["sources"]) != 1 or scope["reference_reports"]
            or record["source"] != scope["sources"][0]
            or any(record["source"][key] != plan["source"][key] for key in
                   ("security_id", "issuer", "fiscal_year", "version", "announcement_id", "url"))):
        raise ValueError("frozen plan/code/scope/source identity mismatch")
    import fitz
    if (manifest["pdf_backend"] != {"name": "PyMuPDF", "version": fitz.VersionBind}
            or manifest["python_version"] != sys.version.split()[0]):
        raise ValueError("frozen rejection runtime version mismatch")
    if (type(process["exit_code"]) is not int or process["exit_code"] <= 0
            or not isinstance(process["stdout_utf8"], str) or not isinstance(process["stderr_utf8"], str)):
        raise ValueError("invalid frozen rejection process outcome")

    def blob(name, digest):
        raw = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=root)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"frozen Git code/rule hash mismatch: {name}")
        return raw

    files = {name: blob(name, digest) for name, digest in manifest["code_sha256"].items()}
    files["RULE_SPEC.md"] = blob("RULE_SPEC.md", manifest["rule_sha256"])
    dependencies = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit, "turtle_quant"], cwd=root).decode("utf-8").splitlines()
    support_hashes = {}
    for name in dependencies:
        if not name.startswith("turtle_quant/") or not name.endswith(".py") or ".." in Path(name).parts:
            continue
        raw = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=root)
        files[name] = raw
        support_hashes[name] = hashlib.sha256(raw).hexdigest()
    source = scope["sources"][0]
    if source["pdf_path"] in files:
        raise ValueError("source path collides with executable replay code")
    files[source["pdf_path"]] = verified_bytes(root, source["pdf_path"], source["pdf_sha256"])
    with tempfile.TemporaryDirectory(prefix="annual-rejection-replay-") as directory:
        replay_root = Path(directory).resolve()
        for relative, raw in files.items():
            target = replay_root / relative
            if target.resolve() != target.absolute() or not target.resolve().is_relative_to(replay_root):
                raise ValueError("unsafe replay artifact path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
        scope_file, output = replay_root / "frozen-input-scope.json", replay_root / "generated"
        with scope_file.open("xb") as stream:
            stream.write(scope_raw)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        result = subprocess.run([sys.executable, "-X", "utf8", str(replay_root / "scripts/extract_annual_report_bundle.py"),
                                 "--scope", str(scope_file), "--output", str(output)], cwd=replay_root,
                                env=env, capture_output=True, timeout=30)
        if (result.returncode != process["exit_code"] or result.stdout != process["stdout_utf8"].encode("utf-8")
                or result.stderr != process["stderr_utf8"].encode("utf-8")):
            raise ValueError("frozen rejection replay outcome is not byte-identical")
        if any((output / name).exists() for name in ("diagnostic-only.json", "diagnostic-only.md")):
            raise ValueError("frozen rejection unexpectedly generated a normal bundle")
    return {"code_commit": commit, "logical_content_hash": record["logical_content_hash"],
            "exit_code": result.returncode, "normal_bundle_created": False, "verified_code_files": len(SOURCE_PATHS),
            "rejection_sha256": hashlib.sha256(frozen_raw).hexdigest(), "support_code_sha256": support_hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--scope", required=True, type=Path)
    parser.add_argument("--rejection", required=True, type=Path)
    args = parser.parse_args()
    result = replay_frozen_rejection(args.plan, args.scope, args.rejection)
    print(json.dumps({k: v for k, v in result.items() if k != "support_code_sha256"}))


if __name__ == "__main__":
    main()
