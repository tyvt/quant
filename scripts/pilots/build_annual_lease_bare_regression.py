"""Offline bare-label payment-table regression, never admitted financial inputs.

Full row text stays under storage. The separate index projects only source
identities, allowlisted lease labels, numbers, geometry and evidence hashes.
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
from scripts.parsing.annual_report_parser import LEASE_LABELS, LEASE_CONTINUATION_LABEL, LEASE_BARE_LABEL
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.assess_annual_audit_narratives import read_assessment_scope, source_key
from scripts.pilots.assess_annual_lease_labels import branch_state, numeric_box, sha
from scripts.pilots.build_annual_lease_continuation_regression import public_index as previous_index
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

REFS = ("input_refs_scope", "baseline_private_report", "baseline_public_index")
SUPPORT = ("scripts/pilots/assess_annual_audit_narratives.py", "scripts/pilots/assess_annual_lease_labels.py",
           "scripts/pilots/build_annual_lease_label_regression.py", "scripts/pilots/assess_annual_lease_continuation.py",
           "scripts/pilots/build_annual_lease_continuation_regression.py",
           "scripts/pilots/capture_annual_holdout.py", "scripts/pilots/capture_financial_2024_000637.py")
LOADED_SUPPORT = {p: sha((ROOT / p).read_bytes()) for p in SUPPORT}
TOOL_SHA256 = sha(Path(__file__).read_bytes())
PERMISSIONS = ("production_reader_ready", "screening_input_exported", "real_pit_run_authorized", "official_selection")
POLICY = "BOTH_COLUMNS_ALL_COMPONENTS_EXPLICIT_NUMERIC_MATCH_TOTAL"


def read_plan(raw):
    plan = strict_json(raw)
    if (not isinstance(plan, dict) or set(plan) != {*REFS, "schema", "as_of", "implementation_base_commit",
            "expected_parser_code_sha256", "bare_label", "reconciliation_policy"}
            or plan["schema"] != "annual-lease-bare-regression-scope-v1" or plan["bare_label"] != LEASE_BARE_LABEL
            or plan["reconciliation_policy"] != POLICY
            or not re.fullmatch(r"[0-9a-f]{40}", str(plan["implementation_base_commit"]))
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(plan["as_of"]))
            or not isinstance(plan["expected_parser_code_sha256"], dict)
            or set(plan["expected_parser_code_sha256"]) != set(SOURCE_PATHS)
            or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h)
                   for h in plan["expected_parser_code_sha256"].values())):
        raise ValueError("invalid bounded bare-label regression scope")
    date.fromisoformat(plan["as_of"])
    for name in REFS:
        ref = plan[name]
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not isinstance(ref["path"], str) or not ref["path"]
                or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])):
            raise ValueError("invalid frozen bare-label reference")
    return plan


def verify_code(plan, root):
    code = {p: sha((root / p).read_bytes()) for p in SOURCE_PATHS}
    if (code != plan["expected_parser_code_sha256"]
            or {p: sha((root / p).read_bytes()) for p in SUPPORT} != LOADED_SUPPORT
            or sha(Path(__file__).read_bytes()) != TOOL_SHA256):
        raise ValueError("bare-label regression implementation drift")
    return code


def build_regression(raw, *, root=ROOT):
    plan = read_plan(raw)
    code = verify_code(plan, root)
    frozen = {n: verified_bytes(root, plan[n]["path"], plan[n]["sha256"]) for n in REFS}
    inputs, old = read_assessment_scope(frozen["input_refs_scope"]), strict_json(frozen["baseline_private_report"])
    if (canonical_bytes(previous_index(old)) + b"\n" != frozen["baseline_public_index"]
            or any(r["as_of"] != plan["as_of"] for r in (inputs, old))
            or old["manifest"]["input_scopes"] != inputs["inputs"]):
        raise ValueError("bare-label regression parent identity mismatch")
    previous = {source_key(r["source"]): r for r in old["observations"]}
    if len(previous) != len(old["observations"]):
        raise ValueError("duplicate bare-label baseline source")
    rows, seen, cache = [], set(), PDFCache()
    for ref in inputs["inputs"]:
        group = build_bundle(verified_bytes(root, ref["path"], ref["sha256"]), root=root, cache=cache)
        if group["as_of"] != plan["as_of"]:
            raise ValueError("mixed bare-label as_of")
        for bundle in group["bundles"]:
            source, current = bundle["source"], bundle["lease_financing_component"]
            key = source_key(source)
            if key in seen or key not in previous or previous[key]["source"] != source:
                raise ValueError("bare-label source identity drift")
            before = previous[key]["current_component"]
            unchanged = content_hash({k: v for k, v in bundle.items() if k != "lease_financing_component"})
            changed = before != current
            if unchanged != previous[key]["non_lease_bundle_content_hash"]:
                raise ValueError("non-lease source output changed")
            if changed and (before["observed_value_cny"] is not None or not current["candidates"]
                    or any(c["source_label"] != LEASE_BARE_LABEL or "payment_table_evidence" not in c
                           for c in current["candidates"])):
                raise ValueError("change outside bounded bare-label path")
            seen.add(key)
            rows.append({"source": source, "currency": bundle["currency"], "baseline_component": before,
                "current_component": current, "component_changed": changed,
                "existing_lease_branch": branch_state(bundle["currency"], current),
                "non_lease_bundle_content_hash": unchanged,
                "full_lease_cash": None, "full_lease_cash_pit": None, "FCF_conservative": None})
    if seen != set(previous):
        raise ValueError("bare-label baseline source missing")
    verify_code(plan, root)
    rows.sort(key=lambda r: source_key(r["source"]))
    result = {"schema": "annual-lease-bare-regression-v1", "diagnostic_only": True,
        "as_of": plan["as_of"], "scope_sha256": sha(raw), "method": "BOUNDED_PAYMENT_TABLE_REGRESSION_NOT_BLIND_SAMPLE",
        "observations": rows, "counts": {"issuers": len({k[0] for k in seen}), "PDF_versions": len(rows),
            "component_changed_PDFs": sum(r["component_changed"] for r in rows),
            "component_observed_PDFs": sum(r["current_component"]["observed_value_cny"] is not None for r in rows),
            "component_observed_issuers": len({r["source"]["security_id"] for r in rows if r["current_component"]["observed_value_cny"] is not None}),
            "evaluated_unknown_PDFs": sum(r["currency"] == "CNY" and r["current_component"]["observed_value_cny"] is None for r in rows),
            "currency_blocked_PDFs": sum(r["currency"] != "CNY" for r in rows)},
        "manifest": {"parser_code_sha256": code, "rule_sha256": RULE_SHA256, "tool_sha256": TOOL_SHA256,
            "support_code_sha256": LOADED_SUPPORT, "implementation_base_commit": plan["implementation_base_commit"],
            "base_commit_is_not_new_parser_identity": True, "frozen_refs": {n: plan[n] for n in REFS},
            "input_scopes": inputs["inputs"], "pdf_backend": group["manifest"]["pdf_backend"], "python_version": sys.version.split()[0]},
        "reconciliation_policy": POLICY, "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "diagnostic_available_at": None,
        "pit_admitted_observation_count": 0, **{k: False for k in PERMISSIONS}}
    result["logical_content_hash"] = content_hash(result)
    return result


def amount(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value)):
        raise ValueError("invalid public numeric amount")
    return value


def projected_cell(cell):
    if not isinstance(cell["state"], str) or not re.fullmatch(r"[A-Z_]{1,80}", cell["state"]):
        raise ValueError("invalid public cell state")
    return {"state": cell["state"], "value_cny": amount(cell["value_cny"]),
            "boxes": [numeric_box(b) for b in cell["boxes"]]}


def projected_table(e):
    if (e["all_components_and_both_totals_required"] is not True
            or any(e[k] is not False for k in ("unit_and_header_inherited", "label_or_amount_joined", "note_target_resolved",
                                               "complete_lease_cash_certified", "public_availability_verified"))):
        raise ValueError("bare payment evidence promotion")
    rows = [{"label_sha256": sha(r["source_label"].encode("utf-8")),
             "label_box": numeric_box(r["binding"]["label_box"]),
             **{k: projected_cell(r[k]) for k in ("current", "comparative")}}
            for r in e["components"]]
    return {"state": e["state"], "physical_page": e["physical_page"],
        "opening_box": numeric_box(e["opening"]["box"]), "closing_box": numeric_box(e["closing"]["box"]),
        "cropbox": numeric_box(e["cropbox"]), "mediabox": numeric_box(e["mediabox"]),
        "components": rows, "printed_total": {k: projected_cell(e["printed_total"][k]) for k in ("current", "comparative")},
        "reconciliations": {k: {"state": r["state"], "component_sum_cny": amount(r["component_sum_cny"]),
                               "printed_total_cny": amount(r["printed_total_cny"])} for k, r in e["reconciliations"].items()},
        "evidence_sha256": sha(canonical_bytes(e)), "complete_lease_cash_certified": False,
        "public_availability_verified": False}


def public_index(report):
    if (report.get("schema") != "annual-lease-bare-regression-v1"
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or report.get("diagnostic_only") is not True or report.get("diagnostic_available_at") is not None
            or report.get("timing_policy") != "UNKNOWN_UNLESS_VERIFIED" or report.get("reconciliation_policy") != POLICY
            or type(report.get("pit_admitted_observation_count")) is not int or report["pit_admitted_observation_count"] != 0
            or any(report.get(k) is not False for k in PERMISSIONS)):
        raise ValueError("invalid source-only bare-label report")
    rows = []
    for row in report["observations"]:
        value, candidates = row["current_component"], []
        if (value["is_complete_lease_cash"] is not False or value["full_lease_cash_not_already_deducted"] is not None
                or value["pit_value"] is not None or value["diagnostic_available_at"] is not None
                or any(row[k] is not None for k in ("full_lease_cash", "full_lease_cash_pit", "FCF_conservative"))):
            raise ValueError("bare cash/PIT promotion")
        for c in value["candidates"]:
            if c["source_label"] not in (*LEASE_LABELS, LEASE_CONTINUATION_LABEL, LEASE_BARE_LABEL):
                raise ValueError("non-allowlisted public lease label")
            b = c["binding"]
            if b["pit_admitted"] is not False or b["diagnostic_available_at"] is not None:
                raise ValueError("bare binding PIT promotion")
            selected = {"source_label": c["source_label"], "physical_page": b["physical_page"],
                "label_box": numeric_box(b["label_box"]), "document_sha256": b["document_sha256"],
                **{k: projected_cell(c[k]) for k in ("current", "comparative")},
                "period_end": b["period_end"], "statement_scope": b["statement_scope"],
                "classification_physical_page": c["classification_evidence"]["physical_page"],
                "header_sha256": sha(canonical_bytes(b["table_header"])),
                "classification_sha256": sha(canonical_bytes(c["classification_evidence"])), "historical_pit_status": "UNKNOWN"}
            if "payment_table_evidence" in c:
                selected["payment_table"] = projected_table(c["payment_table_evidence"])
            if "continuation_evidence" in c:
                selected["continuation_evidence_sha256"] = sha(canonical_bytes(c["continuation_evidence"]))
            candidates.append(selected)
        rows.append({"source": {k: row["source"][k] for k in ("security_id", "issuer", "fiscal_year", "version", "url", "announcement_id", "pdf_sha256", "page_count")},
            "currency": row["currency"], "component_changed": row["component_changed"], "baseline_state": row["baseline_component"]["state"],
            "current_state": value["state"], "observed_value_cny": amount(value["observed_value_cny"]),
            "comparative_not_target_value_cny": amount(value["comparative_not_target_value_cny"]),
            "existing_lease_branch": row["existing_lease_branch"], "candidates": candidates,
            "non_lease_bundle_content_hash": row["non_lease_bundle_content_hash"],
            "full_lease_cash": None, "full_lease_cash_pit": None, "FCF_conservative": None})
    result = {"schema": "annual-lease-bare-regression-public-index-v1", "diagnostic_only": True,
        "as_of": report["as_of"], "scope_sha256": report["scope_sha256"], "manifest": report["manifest"],
        "private_report_sha256": sha(canonical_bytes(report) + b"\n"), "private_report_logical_hash": report["logical_content_hash"],
        "counts": report["counts"], "observations": rows,
        "projection": "source identities, short lease labels, numeric cells/boxes and hashes; no original text channels",
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
            parser.error("bare-label outputs require unlinked private/public paths")
    report = build_regression(args.scope.read_bytes())
    outputs = ((args.output, canonical_bytes(report) + b"\n"), (args.public_index, canonical_bytes(public_index(report)) + b"\n"))
    if args.check:
        if any(p.read_bytes() != raw for p, raw in outputs):
            raise ValueError("bare-label regression/index byte mismatch")
    else:
        if any(p.exists() for p, _ in outputs):
            raise ValueError("refusing to overwrite bare-label regression")
        for p, raw in outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("xb") as stream:
                stream.write(raw)
    print(report["logical_content_hash"])


if __name__ == "__main__":
    main()
