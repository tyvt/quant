"""Offline bounded adjacent-page lease context regression; no financial admission.

Full native rows remain local. The public index contains allowlisted short labels,
numbers, geometry and hashes only, and has its own identity.
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
from scripts.parsing.annual_report_parser import LEASE_LABELS, LEASE_CONTINUATION_LABEL
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.assess_annual_audit_narratives import read_assessment_scope, source_key
from scripts.pilots.assess_annual_lease_labels import branch_state, numeric_box, sha
from scripts.pilots.build_annual_lease_label_regression import public_index as baseline_index
from scripts.pilots.assess_annual_lease_continuation import public_index as assessment_index
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

REFS = ("input_refs_scope", "baseline_private_report", "baseline_public_index", "assessment_scope",
        "assessment_private_report", "assessment_public_index")
SUPPORT = ("scripts/pilots/assess_annual_audit_narratives.py", "scripts/pilots/assess_annual_lease_labels.py",
           "scripts/pilots/build_annual_lease_label_regression.py", "scripts/pilots/assess_annual_lease_continuation.py",
           "scripts/pilots/capture_annual_holdout.py", "scripts/pilots/capture_financial_2024_000637.py")
LOADED_SUPPORT = {p: sha((ROOT / p).read_bytes()) for p in SUPPORT}
TOOL_SHA256 = sha(Path(__file__).read_bytes())
PERMISSIONS = ("production_reader_ready", "screening_input_exported", "real_pit_run_authorized", "official_selection")


def read_plan(raw):
    plan = strict_json(raw)
    if (not isinstance(plan, dict) or set(plan) != {*REFS, "schema", "as_of", "implementation_base_commit",
            "expected_parser_code_sha256", "continuation_label"}
            or plan["schema"] != "annual-lease-continuation-regression-scope-v1"
            or plan["continuation_label"] != LEASE_CONTINUATION_LABEL
            or not re.fullmatch(r"[0-9a-f]{40}", str(plan["implementation_base_commit"]))
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(plan["as_of"]))
            or not isinstance(plan["expected_parser_code_sha256"], dict)
            or set(plan["expected_parser_code_sha256"]) != set(SOURCE_PATHS)
            or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h)
                   for h in plan["expected_parser_code_sha256"].values())):
        raise ValueError("invalid bounded continuation regression scope")
    date.fromisoformat(plan["as_of"])
    for name in REFS:
        ref = plan[name]
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not isinstance(ref["path"], str) or not ref["path"]
                or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])):
            raise ValueError("invalid frozen continuation reference")
    return plan


def verify_code(plan, root):
    code = {p: sha((root / p).read_bytes()) for p in SOURCE_PATHS}
    if (code != plan["expected_parser_code_sha256"]
            or {p: sha((root / p).read_bytes()) for p in SUPPORT} != LOADED_SUPPORT
            or sha(Path(__file__).read_bytes()) != TOOL_SHA256):
        raise ValueError("continuation regression implementation drift")
    return code


def build_regression(raw, *, root=ROOT):
    plan = read_plan(raw)
    code = verify_code(plan, root)
    frozen = {n: verified_bytes(root, plan[n]["path"], plan[n]["sha256"]) for n in REFS}
    inputs = read_assessment_scope(frozen["input_refs_scope"])
    old, assessed = strict_json(frozen["baseline_private_report"]), strict_json(frozen["assessment_private_report"])
    if (canonical_bytes(baseline_index(old)) + b"\n" != frozen["baseline_public_index"]
            or canonical_bytes(assessment_index(assessed)) + b"\n" != frozen["assessment_public_index"]
            or assessed["scope_sha256"] != sha(frozen["assessment_scope"])
            or any(r["as_of"] != plan["as_of"] for r in (inputs, old, assessed))
            or old["manifest"]["input_scopes"] != inputs["inputs"]
            or assessed["manifest"]["input_scopes"] != inputs["inputs"]):
        raise ValueError("continuation regression parent identity mismatch")
    previous = {source_key(r["source"]): r for r in old["observations"]}
    if len(previous) != len(old["observations"]):
        raise ValueError("duplicate continuation baseline source")
    rows, seen, cache = [], set(), PDFCache()
    for ref in inputs["inputs"]:
        group = build_bundle(verified_bytes(root, ref["path"], ref["sha256"]), root=root, cache=cache)
        if group["as_of"] != plan["as_of"]:
            raise ValueError("mixed continuation as_of")
        for bundle in group["bundles"]:
            source, current = bundle["source"], bundle["lease_financing_component"]
            key = source_key(source)
            if key in seen or key not in previous or previous[key]["source"] != source:
                raise ValueError("continuation source identity drift")
            before = previous[key]["current_component"]
            unchanged = content_hash({k: v for k, v in bundle.items() if k != "lease_financing_component"})
            changed = before != current
            if unchanged != previous[key]["non_lease_bundle_content_hash"]:
                raise ValueError("non-lease source output changed")
            if changed and (before["observed_value_cny"] is not None or not current["candidates"]
                    or any(c["source_label"] != LEASE_CONTINUATION_LABEL or "continuation_evidence" not in c
                           for c in current["candidates"])):
                raise ValueError("change outside bounded continuation path")
            seen.add(key)
            rows.append({"source": source, "currency": bundle["currency"], "baseline_component": before,
                         "current_component": current, "component_changed": changed,
                         "existing_lease_branch": branch_state(bundle["currency"], current),
                         "non_lease_bundle_content_hash": unchanged,
                         "full_lease_cash": None, "full_lease_cash_pit": None, "FCF_conservative": None})
    if seen != set(previous):
        raise ValueError("continuation baseline source missing")
    verify_code(plan, root)
    rows.sort(key=lambda r: source_key(r["source"]))
    result = {"schema": "annual-lease-continuation-regression-v1", "diagnostic_only": True,
        "as_of": plan["as_of"], "scope_sha256": sha(raw), "method": "BOUNDED_CONTEXT_REGRESSION_NOT_BLIND_SAMPLE",
        "observations": rows, "counts": {"issuers": len({k[0] for k in seen}), "PDF_versions": len(rows),
            "component_changed_PDFs": sum(r["component_changed"] for r in rows),
            "component_observed_PDFs": sum(r["current_component"]["observed_value_cny"] is not None for r in rows),
            "evaluated_unknown_PDFs": sum(r["currency"] == "CNY" and r["current_component"]["observed_value_cny"] is None for r in rows),
            "currency_blocked_PDFs": sum(r["currency"] != "CNY" for r in rows)},
        "manifest": {"parser_code_sha256": code, "rule_sha256": RULE_SHA256, "tool_sha256": TOOL_SHA256,
            "support_code_sha256": LOADED_SUPPORT, "implementation_base_commit": plan["implementation_base_commit"],
            "base_commit_is_not_new_parser_identity": True, "frozen_refs": {n: plan[n] for n in REFS},
            "input_scopes": inputs["inputs"], "pdf_backend": group["manifest"]["pdf_backend"], "python_version": sys.version.split()[0]},
        "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "diagnostic_available_at": None,
        "pit_admitted_observation_count": 0, **{k: False for k in PERMISSIONS}}
    result["logical_content_hash"] = content_hash(result)
    return result


def public_index(report):
    if (report.get("schema") != "annual-lease-continuation-regression-v1"
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or report.get("diagnostic_only") is not True or report.get("diagnostic_available_at") is not None
            or report.get("timing_policy") != "UNKNOWN_UNLESS_VERIFIED"
            or type(report.get("pit_admitted_observation_count")) is not int or report["pit_admitted_observation_count"] != 0
            or any(report.get(k) is not False for k in PERMISSIONS)):
        raise ValueError("invalid source-only continuation report")
    rows = []
    for row in report["observations"]:
        value, candidates = row["current_component"], []
        if (value["is_complete_lease_cash"] is not False or value["full_lease_cash_not_already_deducted"] is not None
                or value["pit_value"] is not None or value["diagnostic_available_at"] is not None
                or any(row[k] is not None for k in ("full_lease_cash", "full_lease_cash_pit", "FCF_conservative"))):
            raise ValueError("continuation cash/PIT promotion")
        for c in value["candidates"]:
            if c["source_label"] not in (*LEASE_LABELS, LEASE_CONTINUATION_LABEL):
                raise ValueError("non-allowlisted public continuation label")
            b = c["binding"]
            if b["pit_admitted"] is not False or b["diagnostic_available_at"] is not None:
                raise ValueError("continuation binding PIT promotion")
            selected = {"source_label": c["source_label"], "physical_page": b["physical_page"],
                "label_box": numeric_box(b["label_box"]), "document_sha256": b["document_sha256"],
                "current_amount_boxes": [numeric_box(x) for x in c["current"]["boxes"]],
                "comparative_amount_boxes": [numeric_box(x) for x in c["comparative"]["boxes"]],
                "period_end": b["period_end"], "statement_scope": b["statement_scope"],
                "classification_physical_page": c["classification_evidence"]["physical_page"],
                "header_sha256": sha(canonical_bytes(b["table_header"])),
                "classification_sha256": sha(canonical_bytes(c["classification_evidence"])),
                "historical_pit_status": "UNKNOWN"}
            if "continuation_evidence" in c:
                e = c["continuation_evidence"]
                if any(e[k] is not False for k in ("unit_and_header_inherited", "label_or_amount_joined",
                                                 "complete_lease_cash_certified", "public_availability_verified")):
                    raise ValueError("continuation context promotion")
                selected["continuation"] = {"state": e["state"], "heading_physical_page": e["heading_physical_page"],
                    "table_physical_page": e["table_physical_page"], "next_note_physical_page": e["next_note"]["physical_page"],
                    "next_note_box": numeric_box(e["next_note"]["box"]), "evidence_sha256": sha(canonical_bytes(e))}
            candidates.append(selected)
        rows.append({"source": {k: row["source"][k] for k in ("security_id", "issuer", "fiscal_year", "version", "url", "announcement_id", "pdf_sha256", "page_count")},
            "currency": row["currency"], "component_changed": row["component_changed"], "baseline_state": row["baseline_component"]["state"],
            "current_state": value["state"], "observed_value_cny": value["observed_value_cny"],
            "comparative_not_target_value_cny": value["comparative_not_target_value_cny"],
            "existing_lease_branch": row["existing_lease_branch"], "candidates": candidates,
            "non_lease_bundle_content_hash": row["non_lease_bundle_content_hash"],
            "full_lease_cash": None, "full_lease_cash_pit": None, "FCF_conservative": None})
    result = {"schema": "annual-lease-continuation-regression-public-index-v1", "diagnostic_only": True,
        "as_of": report["as_of"], "scope_sha256": report["scope_sha256"], "manifest": report["manifest"],
        "private_report_sha256": sha(canonical_bytes(report) + b"\n"), "private_report_logical_hash": report["logical_content_hash"],
        "counts": report["counts"], "observations": rows,
        "projection": "allowlisted short labels, source identities, numeric values/boxes and hashes; no original text channels",
        "diagnostic_available_at": None, "pit_admitted_observation_count": 0, **{k: False for k in PERMISSIONS}}
    result["logical_content_hash"] = content_hash(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-index", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    for path, base in ((args.output, ROOT / "storage"), (args.public_index, ROOT / "docs/data-pilots")):
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(base.resolve()):
            parser.error("continuation outputs require unlinked private/public paths")
    report = build_regression(args.scope.read_bytes())
    outputs = ((args.output, canonical_bytes(report) + b"\n"), (args.public_index, canonical_bytes(public_index(report)) + b"\n"))
    if args.check:
        if any(p.read_bytes() != raw for p, raw in outputs):
            raise ValueError("continuation regression/index byte mismatch")
    else:
        if any(p.exists() for p, _ in outputs):
            raise ValueError("refusing to overwrite continuation regression")
        for p, raw in outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("xb") as stream:
                stream.write(raw)
    print(report["logical_content_hash"])


if __name__ == "__main__":
    main()
