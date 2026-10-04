"""Re-run fixed annual sources after an exact lease-label-only extension.

Never infer full lease cash or admit PIT. Raw rows stay in storage/, and an
explicit index exports only amounts, short labels, source identity and geometry.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import RULE_SHA256, SOURCE_PATHS, build_bundle, verified_bytes
from scripts.parsing.annual_report_parser import LEASE_LABELS
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.assess_annual_audit_narratives import read_assessment_scope, source_key
from scripts.pilots.assess_annual_lease_labels import read_lease_scope, branch_state, numeric_box, public_index as old_index, sha
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

ADDED = ("支付租赁款", "长期租赁付款", "支付租赁负债")
TOOL_SHA256 = sha(Path(__file__).read_bytes())
SUPPORT_PATHS = ("scripts/pilots/assess_annual_lease_labels.py", "scripts/pilots/assess_annual_audit_narratives.py",
                 "scripts/pilots/capture_annual_holdout.py", "scripts/pilots/capture_financial_2024_000637.py")
LOADED_SUPPORT = {p: sha((ROOT / p).read_bytes()) for p in SUPPORT_PATHS}


def read_regression_scope(raw):
    scope = strict_json(raw)
    if (not isinstance(scope, dict) or set(scope) != {"schema", "as_of", "implementation_base_commit", "assessment_scope",
            "baseline_private_report", "baseline_public_index", "added_exact_labels", "expected_parser_code_sha256"}
            or scope["schema"] != "annual-lease-label-regression-scope-v1"
            or scope["added_exact_labels"] != list(ADDED)
            or set(scope["expected_parser_code_sha256"]) != set(SOURCE_PATHS)):
        raise ValueError("invalid bounded lease regression scope")
    for name in ("assessment_scope", "baseline_private_report", "baseline_public_index"):
        if (not isinstance(scope[name], dict) or set(scope[name]) != {"path", "sha256"}
                or not isinstance(scope[name]["path"], str) or not scope[name]["path"]
                or not isinstance(scope[name]["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", scope[name]["sha256"])):
            raise ValueError("invalid frozen lease reference")
    if (not isinstance(scope["as_of"], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", scope["as_of"])
            or not isinstance(scope["implementation_base_commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", scope["implementation_base_commit"])
            or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h)
                   for h in scope["expected_parser_code_sha256"].values())):
        raise ValueError("invalid lease regression date/commit/code identity")
    date.fromisoformat(scope["as_of"])
    return scope


def verify_code(scope, root):
    actual = {p: sha((root / p).read_bytes()) for p in SOURCE_PATHS}
    if (actual != scope["expected_parser_code_sha256"]
            or LEASE_LABELS != ("偿还租赁负债支付的金额", "租赁支付的现金", *ADDED)
            or {p: sha((root / p).read_bytes()) for p in SUPPORT_PATHS} != LOADED_SUPPORT
            or sha(Path(__file__).read_bytes()) != TOOL_SHA256):
        raise ValueError("lease regression code or whitelist drift")
    return actual


def build_regression(raw_scope, *, root=ROOT):
    scope = read_regression_scope(raw_scope)
    code = verify_code(scope, root)
    refs = {}
    for name in ("assessment_scope", "baseline_private_report", "baseline_public_index"):
        ref = scope[name]
        refs[name] = verified_bytes(root, ref["path"], ref["sha256"])
    old_scope = read_lease_scope(refs["assessment_scope"])
    baseline = strict_json(refs["baseline_private_report"])
    if (canonical_bytes(old_index(baseline)) + b"\n" != refs["baseline_public_index"]
            or baseline["scope_sha256"] != sha(refs["assessment_scope"])
            or baseline["as_of"] != scope["as_of"] or old_scope["as_of"] != scope["as_of"]
            or baseline["manifest"]["parser_code_sha256"] != old_scope["parser_code_sha256"]):
        raise ValueError("baseline lease assessment identity mismatch")
    parent = old_scope["input_refs_scope"]
    inputs = read_assessment_scope(verified_bytes(root, parent["path"], parent["sha256"]))
    previous = {source_key(r["source"]): r for r in baseline["observations"]}
    if len(previous) != len(baseline["observations"]):
        raise ValueError("duplicate baseline lease source")
    cache, rows, seen = PDFCache(), [], set()
    for ref in inputs["inputs"]:
        group = build_bundle(verified_bytes(root, ref["path"], ref["sha256"]), root=root, cache=cache)
        if group["as_of"] != scope["as_of"]:
            raise ValueError("mixed lease regression as_of")
        for bundle in group["bundles"]:
            source = bundle["source"]
            key = source_key(source)
            if key in seen or key not in previous or previous[key]["source"] != source:
                raise ValueError("lease regression source identity drift/duplicate")
            seen.add(key)
            old, current = previous[key]["existing_lease_component"], bundle["lease_financing_component"]
            changed = old != current
            if changed and (old["observed_value_cny"] is not None or not current["candidates"]
                            or any(r["source_label"] not in ADDED for r in current["candidates"])):
                raise ValueError("change beyond bounded added lease labels")
            rows.append({"source": source, "currency": bundle["currency"],
                         "existing_lease_branch": branch_state(bundle["currency"], current),
                         "baseline_component": old, "current_component": current, "component_changed": changed,
                         "non_lease_bundle_content_hash": content_hash({k: v for k, v in bundle.items() if k != "lease_financing_component"}),
                         "full_lease_cash": None, "full_lease_cash_pit": None, "FCF_conservative": None})
    if seen != set(previous):
        raise ValueError("missing baseline lease source")
    verify_code(scope, root)
    rows.sort(key=lambda r: source_key(r["source"]))
    report = {"schema": "annual-lease-label-regression-v1", "diagnostic_only": True, "as_of": scope["as_of"],
              "scope_sha256": sha(raw_scope), "method": "EXACT_LABEL_REGRESSION_NOT_NEW_BLIND_SAMPLE",
              "observations": rows,
              "counts": {"issuers": len({k[0] for k in seen}), "PDF_versions": len(rows),
                         "component_changed_PDFs": sum(r["component_changed"] for r in rows),
                         "component_observed_PDFs": sum(r["current_component"]["observed_value_cny"] is not None for r in rows),
                         "evaluated_unknown_PDFs": sum(r["currency"] == "CNY" and r["current_component"]["observed_value_cny"] is None for r in rows),
                         "currency_blocked_PDFs": sum(r["currency"] != "CNY" for r in rows)},
              "manifest": {"parser_code_sha256": code, "rule_sha256": RULE_SHA256, "tool_sha256": TOOL_SHA256,
                           "support_code_sha256": LOADED_SUPPORT, "implementation_base_commit": scope["implementation_base_commit"],
                           "base_commit_is_not_new_parser_identity": True,
                           "input_scopes": inputs["inputs"], "baseline_private_report": scope["baseline_private_report"],
                           "baseline_public_index": scope["baseline_public_index"], "assessment_scope": scope["assessment_scope"],
                           "pdf_backend": group["manifest"]["pdf_backend"], "python_version": sys.version.split()[0]},
              "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "diagnostic_available_at": None,
              "pit_admitted_observation_count": 0, "production_reader_ready": False,
              "screening_input_exported": False, "real_pit_run_authorized": False, "official_selection": False}
    report["logical_content_hash"] = content_hash(report)
    return report


def public_index(report):
    if (report.get("schema") != "annual-lease-label-regression-v1"
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or report.get("diagnostic_only") is not True
            or report.get("timing_policy") != "UNKNOWN_UNLESS_VERIFIED"
            or report.get("diagnostic_available_at") is not None
            or type(report.get("pit_admitted_observation_count")) is not int
            or report.get("pit_admitted_observation_count") != 0
            or any(report.get(k) is not False for k in ("production_reader_ready", "screening_input_exported", "real_pit_run_authorized", "official_selection"))):
        raise ValueError("invalid source-only lease regression identity")
    rows = []
    for row in report["observations"]:
        value, candidates = row["current_component"], []
        for candidate in value["candidates"]:
            if candidate["source_label"] not in LEASE_LABELS:
                raise ValueError("non-allowlisted public lease label")
            bind, classification = candidate["binding"], candidate["classification_evidence"]
            header = bind["table_header"]
            candidates.append({"source_label": candidate["source_label"], "physical_page": bind["physical_page"],
                               "label_box": numeric_box(bind["label_box"]), "document_sha256": bind["document_sha256"],
                               "current_amount_boxes": [numeric_box(b) for b in candidate["current"]["boxes"]],
                               "comparative_amount_boxes": [numeric_box(b) for b in candidate["comparative"]["boxes"]],
                               "period_end": bind["period_end"], "statement_scope": bind["statement_scope"],
                               "header_sha256": sha(canonical_bytes(header)),
                               "classification_sha256": sha(canonical_bytes(classification)),
                               "classification": classification["classification"], "historical_pit_status": "UNKNOWN"})
        source = row["source"]
        rows.append({"source": {k: source[k] for k in ("security_id", "issuer", "fiscal_year", "version", "url", "announcement_id", "pdf_sha256", "page_count")},
                     "currency": row["currency"], "existing_lease_branch": row["existing_lease_branch"],
                     "component_changed": row["component_changed"], "baseline_state": row["baseline_component"]["state"],
                     "current_state": value["state"], "observed_value_cny": value["observed_value_cny"],
                     "comparative_not_target_value_cny": value["comparative_not_target_value_cny"],
                     "candidates": candidates, "non_lease_bundle_content_hash": row["non_lease_bundle_content_hash"],
                     "full_lease_cash": None, "full_lease_cash_pit": None, "FCF_conservative": None})
    index = {"schema": "annual-lease-label-regression-public-index-v1", "diagnostic_only": True,
             "as_of": report["as_of"], "private_report_sha256": sha(canonical_bytes(report) + b"\n"),
             "private_report_logical_hash": report["logical_content_hash"], "scope_sha256": report["scope_sha256"],
             "manifest": report["manifest"], "counts": report["counts"], "observations": rows,
             "projection": "short labels, numeric values, geometry and hashes only; no original page or paragraph text",
             "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
             "production_reader_ready": False, "screening_input_exported": False,
             "real_pit_run_authorized": False, "official_selection": False}
    index["logical_content_hash"] = content_hash(index)
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-index", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    for path, base in ((args.output, ROOT / "storage"), (args.public_index, ROOT / "docs/data-pilots")):
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(base.resolve()):
            parser.error("private report/public index path outside allowed unlinked directory")
    report = build_regression(args.scope.read_bytes())
    artifacts = ((args.output, canonical_bytes(report) + b"\n"),
                 (args.public_index, canonical_bytes(public_index(report)) + b"\n"))
    if args.check:
        if any(path.read_bytes() != raw for path, raw in artifacts):
            raise ValueError("lease regression/index byte mismatch")
    else:
        if any(path.exists() for path, _ in artifacts):
            raise ValueError("refusing to overwrite frozen lease regression")
        for path, raw in artifacts:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
    print(report["logical_content_hash"])


if __name__ == "__main__":
    main()
