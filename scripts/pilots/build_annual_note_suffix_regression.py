"""Explicit bounded note-grammar scopes; no target or semantic resolution.

Actually execute the six frozen baseline parser blobs, then compare all three
tables. Full observations stay local; the public projection is allowlisted.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import RULE_SHA256, SOURCE_PATHS, read_scope, verified_bytes
from scripts.parsing.annual_report_parser import parse_annual, _table
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.assess_annual_audit_narratives import read_assessment_scope, source_key
from scripts.pilots.assess_annual_lease_labels import numeric_box, sha
from scripts.pilots.build_annual_lease_bare_regression import SUPPORT as BARE_SUPPORT, public_index as parent_index, projected_cell
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

SUPPORT = (*BARE_SUPPORT, "scripts/pilots/build_annual_lease_bare_regression.py")
LOADED_SUPPORT = {p: sha((ROOT / p).read_bytes()) for p in SUPPORT}
TOOL_SHA256 = sha(Path(__file__).read_bytes())
REFS = ("input_refs_scope", "baseline_private_report", "baseline_public_index")
PERMISSIONS = ("production_reader_ready", "screening_input_exported", "real_pit_run_authorized", "official_selection")
FORM = "CHAPTER_FULLWIDTH_PARENS_ITEM_SUFFIX"
DUNHAO_FORM = "CHAPTER_DUNHAO_ITEM_FULLWIDTH_PARENS_SUBITEM"
HYPHEN_FORM = "CHAPTER_HYPHEN_ITEM_FULLWIDTH_PARENS_SUBITEM"
SCHEMAS = {FORM: "annual-note-suffix-regression",
           DUNHAO_FORM: "annual-note-dunhao-subitem-regression",
           HYPHEN_FORM: "annual-note-hyphen-subitem-regression"}
CHAPTER = r"(?:[一二三四五六七八九]|十[一二三四五六七八九]?|[二三四五六七八九]十[一二三四五六七八九]?)"
FORMS = {FORM: CHAPTER + r"（[1-9][0-9]*）[1-9][0-9]*",
         "DUNHAO_PARENS_SUBITEM_NOT_IMPLEMENTED": CHAPTER + r"、[1-9][0-9]*（[1-9][0-9]*）",
         "HYPHEN_PARENS_SUBITEM_NOT_IMPLEMENTED": CHAPTER + r"-[1-9][0-9]*（[1-9][0-9]*）"}


def grammar_forms(form):
    if form not in SCHEMAS:
        raise ValueError("unsupported bounded note form")
    names = {} if form == FORM else {"DUNHAO_PARENS_SUBITEM_NOT_IMPLEMENTED": DUNHAO_FORM}
    if form == HYPHEN_FORM:
        names["HYPHEN_PARENS_SUBITEM_NOT_IMPLEMENTED"] = HYPHEN_FORM
    return {names.get(key, key): value for key, value in FORMS.items()}

# ASCII source is intentional: no PowerShell pipe, locale-dependent transcoding
# or current-repository imports can rewrite the frozen parser's native tokens.
DRIVER = r'''
import json,sys
from pathlib import Path
import fitz
from scripts.extract_annual_report_bundle import read_scope,verified_bytes
from scripts.parsing.annual_report_parser import parse_annual,_table
from scripts.parsing.generic_extractor import PDFCache
from scripts.screening.contracts import canonical_bytes
params=json.loads(sys.stdin.buffer.read().decode('utf-8'))
root=Path(params['root']).resolve(); cache=PDFCache(); observations=[]
for ref in params['inputs']:
    scope=read_scope(verified_bytes(root,ref['path'],ref['sha256']))
    if scope['as_of']!=params['as_of']: raise ValueError('mixed snapshot as_of')
    for refdoc in scope['reference_reports']:
        verified_bytes(root,refdoc['path'],refdoc['sha256'])
    for source in scope['sources']:
        pdf=cache.parse(verified_bytes(root,source['pdf_path'],source['pdf_sha256']),source['pdf_sha256'])
        if len(pdf.pages)!=source['page_count']: raise ValueError('snapshot page count mismatch')
        bundle=parse_annual(pdf,source)
        tables={k:(_table(pdf,source,k) if bundle['currency']=='CNY' else
                   {'state':'CURRENCY_EVIDENCE_UNKNOWN','rows':[]}) for k in ('balance','income','cashflow')}
        observations.append({'source':source,'bundle':bundle,'tables':tables})
observations.sort(key=lambda r:(r['source']['security_id'],r['source']['fiscal_year'],r['source']['version']))
sys.stdout.buffer.write(canonical_bytes({'observations':observations,'pdf_backend_version':fitz.VersionBind,
                                       'python_version':sys.version.split()[0]}))
'''


def read_plan(raw):
    plan = strict_json(raw)
    keys = {*REFS, "schema", "as_of", "baseline_code_commit", "baseline_parser_code_sha256",
            "expected_parser_code_sha256", "new_reference_form"}
    if (not isinstance(plan, dict) or set(plan) != keys
            or plan.get("new_reference_form") not in SCHEMAS
            or plan["schema"] != SCHEMAS[plan["new_reference_form"]] + "-scope-v1"
            or not re.fullmatch(r"[0-9a-f]{40}", str(plan["baseline_code_commit"]))
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(plan["as_of"]))):
        raise ValueError("invalid bounded note-suffix scope")
    date.fromisoformat(plan["as_of"])
    for key in ("baseline_parser_code_sha256", "expected_parser_code_sha256"):
        if (not isinstance(plan[key], dict) or set(plan[key]) != set(SOURCE_PATHS)
                or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in plan[key].values())):
            raise ValueError("note-suffix parser whitelist mismatch")
    for name in REFS:
        ref = plan[name]
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not isinstance(ref["path"], str) or not ref["path"]
                or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])):
            raise ValueError("invalid frozen note-suffix reference")
    return plan


def verify_code(plan, root):
    code = {p: sha((root / p).read_bytes()) for p in SOURCE_PATHS}
    if (code != plan["expected_parser_code_sha256"] or sha((root / "RULE_SPEC.md").read_bytes()) != RULE_SHA256
            or {p: sha((root / p).read_bytes()) for p in SUPPORT} != LOADED_SUPPORT
            or sha(Path(__file__).read_bytes()) != TOOL_SHA256):
        raise ValueError("note-suffix implementation drift")
    return code


def frozen_snapshot(plan, inputs, root):
    with tempfile.TemporaryDirectory(prefix="annual-note-suffix-baseline-") as directory:
        temporary = Path(directory).resolve()
        files = {}
        for name, expected in plan["baseline_parser_code_sha256"].items():
            raw = subprocess.check_output(["git", "show", plan["baseline_code_commit"] + ":" + name], cwd=root)
            if sha(raw) != expected:
                raise ValueError("frozen baseline parser blob mismatch")
            files[name] = raw
        names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", plan["baseline_code_commit"], "turtle_quant"], cwd=root).decode("utf-8").splitlines()
        support = {}
        for name in names:
            if name.startswith("turtle_quant/") and name.endswith(".py") and ".." not in Path(name).parts:
                files[name] = subprocess.check_output(["git", "show", plan["baseline_code_commit"] + ":" + name], cwd=root)
                support[name] = sha(files[name])
        for name, raw in files.items():
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        env.update(PYTHONDONTWRITEBYTECODE="1")
        run = subprocess.run([sys.executable, "-X", "utf8", "-c", DRIVER], cwd=temporary, env=env,
            input=canonical_bytes({"root": str(root), "inputs": inputs, "as_of": plan["as_of"]}),
            capture_output=True, timeout=60)
        if run.returncode:
            raise ValueError("frozen note baseline failed: " + run.stderr.decode("utf-8", errors="replace"))
        result = strict_json(run.stdout)
        if run.stdout != canonical_bytes(result):
            raise ValueError("noncanonical frozen note snapshot")
        result["baseline_python_support_sha256"] = support
        return result


def row_changes(before, after, *, form=FORM):
    pattern = grammar_forms(form)[form]
    if {k: v for k, v in before.items() if k != "rows"} != {k: v for k, v in after.items() if k != "rows"}:
        raise ValueError("table boundary/header change outside note grammar")
    if len(before["rows"]) != len(after["rows"]):
        raise ValueError("row inventory changed outside note grammar")
    changes = []
    for old, new in zip(before["rows"], after["rows"]):
        if old == new:
            continue
        note = new.get("note_column_observation", {})
        old_note = old.get("note_column_observation", {})
        if (len(note.get("raw_text", [])) != 1 or not re.fullmatch(pattern, note["raw_text"][0])
                or note.get("syntax_state") != "OBSERVED_SINGLE_REFERENCE_SYNTAX" or note.get("reference_form") != form
                or old_note.get("syntax_state") != "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE"
                or any(note.get(k) is not False for k in ("note_target_resolved", "note_semantics_certified"))):
            raise ValueError("row change outside bounded note-suffix syntax")
        masked = deepcopy(new)
        masked["note_column_observation"]["syntax_state"] = old_note["syntax_state"]
        masked["note_column_observation"]["reference_form"] = old_note["reference_form"]
        for key in ("current", "comparative"):
            if old[key]["state"] != "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE" or old[key]["value_cny"] is not None:
                raise ValueError("unexpected previously observed note-suffix amount")
            masked[key]["state"], masked[key]["value_cny"] = old[key]["state"], old[key]["value_cny"]
        if masked != old:
            raise ValueError("binding, native token or geometry changed outside note grammar")
        changes.append({"before": old, "after": new})
    return changes


def build_regression(raw, *, root=ROOT):
    root = root.resolve()
    plan = read_plan(raw)
    form = plan["new_reference_form"]
    forms = grammar_forms(form)
    code = verify_code(plan, root)
    frozen = {k: verified_bytes(root, plan[k]["path"], plan[k]["sha256"]) for k in REFS}
    inputs, parent = read_assessment_scope(frozen["input_refs_scope"]), strict_json(frozen["baseline_private_report"])
    projection = parent_index(parent) if form == FORM else public_index(parent)
    expected_parent = {DUNHAO_FORM: SCHEMAS[FORM] + "-v1",
                       HYPHEN_FORM: SCHEMAS[DUNHAO_FORM] + "-v1"}
    if ((form in expected_parent and parent.get("schema") != expected_parent[form])
            or canonical_bytes(projection) + b"\n" != frozen["baseline_public_index"]
            or parent["manifest"]["parser_code_sha256"] != plan["baseline_parser_code_sha256"]
            or inputs["as_of"] != plan["as_of"] or parent["as_of"] != plan["as_of"]
            or parent["manifest"]["input_scopes"] != inputs["inputs"]):
        raise ValueError("note-suffix parent identity mismatch")
    previous = frozen_snapshot(plan, inputs["inputs"], root)
    parents = {source_key(r["source"]): r for r in parent["observations"]}
    old = {source_key(r["source"]): r for r in previous["observations"]}
    if len(old) != len(previous["observations"]) or set(old) != set(parents):
        raise ValueError("duplicate or missing frozen snapshot source")
    rows, seen, cache = [], set(), PDFCache()
    for ref in inputs["inputs"]:
        scope = read_scope(verified_bytes(root, ref["path"], ref["sha256"]))
        if scope["as_of"] != plan["as_of"]:
            raise ValueError("mixed note-suffix as_of")
        for reference in scope["reference_reports"]:
            verified_bytes(root, reference["path"], reference["sha256"])
        for source in scope["sources"]:
            key = source_key(source)
            if key in seen or key not in old or old[key]["source"] != source or parents[key]["source"] != source:
                raise ValueError("note-suffix source identity drift")
            pdf = cache.parse(verified_bytes(root, source["pdf_path"], source["pdf_sha256"]), source["pdf_sha256"])
            if len(pdf.pages) != source["page_count"]:
                raise ValueError("note-suffix page count mismatch")
            bundle = parse_annual(pdf, source)
            tables = {k: (_table(pdf, source, k) if bundle["currency"] == "CNY" else
                         {"state": "CURRENCY_EVIDENCE_UNKNOWN", "rows": []}) for k in ("balance", "income", "cashflow")}
            before = old[key]
            if form != FORM and (before["tables"] != parents[key]["current_tables"]
                    or content_hash(before["bundle"]) != parents[key]["bundle_content_hash"]):
                raise ValueError("frozen baseline differs from approved parent content")
            # Main seven fields, currency, audit, lease, source identity and all
            # other bundle outputs must be identical, not merely numerically close.
            component = (parents[key]["current_component"] if form == FORM else
                         parents[key]["baseline_snapshot"]["bundle"]["lease_financing_component"])
            if bundle != before["bundle"] or bundle["lease_financing_component"] != component:
                raise ValueError("non-note bundle or lease output changed")
            changes = {k: row_changes(before["tables"][k], tables[k], form=form) for k in tables}
            inventory = [{"reference_form": name, "native_reference": w.text, "physical_page": p.number, "box": list(w.box)}
                         for p in pdf.pages for w in p.words for name, pattern in forms.items()
                         if re.fullmatch(pattern, w.text)]
            rows.append({"source": source, "currency": bundle["currency"], "bundle_content_hash": content_hash(bundle),
                "baseline_snapshot": before, "current_tables": tables, "changes": changes, "native_reference_inventory": inventory,
                "bundle_unchanged": True, "full_lease_cash": None, "full_lease_cash_pit": None, "FCF_conservative": None})
            seen.add(key)
    if seen != set(old):
        raise ValueError("frozen note-suffix source missing")
    if previous["pdf_backend_version"] != pdf.backend_version or previous["python_version"] != sys.version.split()[0]:
        raise ValueError("frozen/current backend mismatch")
    verify_code(plan, root)
    rows.sort(key=lambda r: source_key(r["source"]))
    result = {"schema": SCHEMAS[form] + "-v1", "diagnostic_only": True, "as_of": plan["as_of"],
        "scope_sha256": sha(raw), "method": "SINGLE_NATIVE_TOKEN_SYNTAX_ONLY_NOT_TARGET_RESOLUTION",
        "new_reference_form": form, "observations": rows,
        "counts": {"issuers": len({key[0] for key in seen}), "PDF_versions": len(rows),
            "changed_PDFs": sum(any(r["changes"].values()) for r in rows),
            "changed_rows": sum(len(v) for r in rows for v in r["changes"].values()),
            "raw_multilevel_tokens": sum(len(r["native_reference_inventory"]) for r in rows),
            "currency_blocked_PDFs": sum(r["currency"] != "CNY" for r in rows), "unchanged_bundles": len(rows)},
        "manifest": {"parser_code_sha256": code, "baseline_parser_code_sha256": plan["baseline_parser_code_sha256"],
            "baseline_code_commit": plan["baseline_code_commit"], "baseline_execution": "ACTUAL_FROZEN_CODE_NOT_SAVED_OUTPUT",
            "baseline_python_support_sha256": previous["baseline_python_support_sha256"],
            "rule_sha256": RULE_SHA256, "tool_sha256": TOOL_SHA256, "support_code_sha256": LOADED_SUPPORT,
            "frozen_refs": {k: plan[k] for k in REFS}, "input_scopes": inputs["inputs"],
            "pdf_backend_version": pdf.backend_version, "python_version": sys.version.split()[0]},
        "note_target_resolved": False, "note_semantics_certified": False, "timing_policy": "UNKNOWN_UNLESS_VERIFIED",
        "diagnostic_available_at": None, "pit_admitted_observation_count": 0, **{k: False for k in PERMISSIONS}}
    result["logical_content_hash"] = content_hash(result)
    return result


def public_index(report):
    form = report.get("new_reference_form")
    if (form not in SCHEMAS or report.get("schema") != SCHEMAS[form] + "-v1"
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or report.get("diagnostic_only") is not True or report.get("diagnostic_available_at") is not None
            or type(report.get("pit_admitted_observation_count")) is not int or report["pit_admitted_observation_count"] != 0
            or report.get("timing_policy") != "UNKNOWN_UNLESS_VERIFIED"
            or any(report.get(k) is not False for k in (*PERMISSIONS, "note_target_resolved", "note_semantics_certified"))):
        raise ValueError("invalid source-only note-suffix report")
    rows = []
    for r in report["observations"]:
        if r["bundle_unchanged"] is not True or any(r[k] is not None for k in ("full_lease_cash", "full_lease_cash_pit", "FCF_conservative")):
            raise ValueError("note-suffix evidence promotion")
        changes = []
        for kind, values in r["changes"].items():
            if kind not in ("balance", "income", "cashflow"):
                raise ValueError("unknown note table")
            for change in values:
                c, n = change["after"], change["after"]["note_column_observation"]
                if (len(n["raw_text"]) != 1 or not re.fullmatch(grammar_forms(form)[form], n["raw_text"][0])
                        or n["reference_form"] != form or n["syntax_state"] != "OBSERVED_SINGLE_REFERENCE_SYNTAX"
                        or any(n[k] is not False for k in ("note_target_resolved", "note_semantics_certified"))):
                    raise ValueError("non-allowlisted note reference or promotion")
                b = c["binding"]
                if b["pit_admitted"] is not False or b["diagnostic_available_at"] is not None:
                    raise ValueError("note binding PIT promotion")
                changes.append({"section": kind, "native_reference": n["raw_text"][0], "physical_page": b["physical_page"],
                    "note_boxes": [numeric_box(box) for box in n["boxes"]], "label_box": numeric_box(b["label_box"]),
                    "label_sha256": sha(c["source_label"].encode("utf-8")), "header_sha256": sha(canonical_bytes(b["table_header"])),
                    "reference_form": form, "syntax_state": n["syntax_state"],
                    **{key: projected_cell(c[key]) for key in ("current", "comparative")},
                    "note_target_resolved": False, "note_semantics_certified": False})
        rows.append({"source": {k: r["source"][k] for k in ("security_id", "issuer", "fiscal_year", "version", "url", "announcement_id", "pdf_sha256", "page_count")},
            "currency": r["currency"], "bundle_unchanged": True, "bundle_content_hash": r["bundle_content_hash"], "changes": changes,
            "baseline_tables_sha256": sha(canonical_bytes(r["baseline_snapshot"]["tables"])),
            "current_tables_sha256": sha(canonical_bytes(r["current_tables"])),
            "native_reference_inventory_sha256": sha(canonical_bytes(r["native_reference_inventory"]))})
    result = {"schema": SCHEMAS[form] + "-public-index-v1", "diagnostic_only": True, "as_of": report["as_of"],
        "scope_sha256": report["scope_sha256"], "manifest": report["manifest"], "counts": report["counts"], "observations": rows,
        "private_report_sha256": sha(canonical_bytes(report) + b"\n"), "private_report_logical_hash": report["logical_content_hash"],
        "projection": "source identities, short reference syntax, numeric cells/boxes and hashes only",
        "note_target_resolved": False, "note_semantics_certified": False, "diagnostic_available_at": None,
        "pit_admitted_observation_count": 0, **{k: False for k in PERMISSIONS}}
    result["logical_content_hash"] = content_hash(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("scope", "output", "public-index"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    for path, base in ((args.output, ROOT / "storage"), (args.public_index, ROOT / "docs/data-pilots")):
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(base.resolve()):
            parser.error("note-suffix outputs require unlinked private/public paths")
    if not args.check and any(p.exists() for p in (args.output, args.public_index)):
        raise ValueError("refusing to overwrite note-suffix regression")
    report = build_regression(args.scope.read_bytes())
    outputs = ((args.output, canonical_bytes(report) + b"\n"), (args.public_index, canonical_bytes(public_index(report)) + b"\n"))
    if args.check:
        if any(p.read_bytes() != raw for p, raw in outputs):
            raise ValueError("note-suffix regression/index byte mismatch")
    else:
        for p, raw in outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("xb") as stream:
                stream.write(raw)
    print(report["logical_content_hash"])


if __name__ == "__main__":
    main()
