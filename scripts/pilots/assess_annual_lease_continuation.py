"""Bounded offline source-continuation observations, never parser admission.

Only the frozen native payment-word inventory and selected pages are examined.
No OCR, page-text repair, arbitrary paragraph joins or new financial aliases.
The detailed report remains local; a text-minimized index has separate identity.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import RULE_SHA256, SOURCE_PATHS, build_bundle, verified_bytes
from scripts.parsing.annual_report_parser import _header, _lines, _title
from scripts.parsing.field_binder import cell, compact, inside
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.assess_annual_audit_narratives import read_assessment_scope, source_key
from scripts.pilots.assess_annual_lease_labels import native_words, numeric_box, page_record, sha
from scripts.pilots.build_annual_lease_label_regression import public_index as baseline_index
from scripts.pilots.capture_annual_holdout import verify_parser
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

TARGET_LABEL = "偿还租赁负债本金和利息所支付的现金"
PAYMENTS = ("偿还租赁负债支付的金额", "租赁支付的现金", "支付租赁款", "长期租赁付款",
            "支付租赁负债", "偿还租赁负债款", TARGET_LABEL)
TOOL_SHA256 = sha(Path(__file__).read_bytes())
SUPPORT_PATHS = ("scripts/pilots/assess_annual_audit_narratives.py", "scripts/pilots/assess_annual_lease_labels.py",
                 "scripts/pilots/build_annual_lease_label_regression.py", "scripts/pilots/capture_annual_holdout.py",
                 "scripts/pilots/capture_financial_2024_000637.py")
LOADED_SUPPORT = {p: sha((ROOT / p).read_bytes()) for p in SUPPORT_PATHS}
PERMISSIONS = ("production_reader_ready", "screening_input_exported", "real_pit_run_authorized", "official_selection")


def read_plan(raw):
    plan = strict_json(raw)
    if (not isinstance(plan, dict) or set(plan) != {"schema", "as_of", "method", "parser_commit", "parser_code_sha256",
            "input_refs_scope", "baseline_private_report", "baseline_public_index", "search", "review_cases"}
            or plan["schema"] != "annual-lease-continuation-assessment-scope-v1"
            or plan["method"] != "OFFLINE_POSTHOC_CONTINUATION_ASSESSMENT_NOT_PARSER_FIX"
            or not isinstance(plan["parser_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", plan["parser_commit"])
            or plan["search"] != {"exact_native_payment_labels": list(PAYMENTS),
                                  "maximum_word_characters": 48, "previous_page_limit": 1}
            or type(plan["search"]["maximum_word_characters"]) is not int
            or type(plan["search"]["previous_page_limit"]) is not int):
        raise ValueError("invalid bounded continuation scope")
    for name in ("input_refs_scope", "baseline_private_report", "baseline_public_index"):
        ref = plan[name]
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not isinstance(ref["path"], str) or not ref["path"]
                or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])):
            raise ValueError("invalid frozen continuation reference")
    cases = plan["review_cases"]
    seen = set()
    if not isinstance(cases, list) or not cases:
        raise ValueError("explicit continuation cases required")
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"security_id", "fiscal_year", "version", "physical_pages", "role"}:
            raise ValueError("invalid continuation case")
        key, pages = source_key(case), case["physical_pages"]
        if (key in seen or not isinstance(pages, list) or len(pages) not in (1, 2)
                or any(type(p) is not int or p < 1 for p in pages)
                or len(pages) == 2 and pages[1] != pages[0] + 1
                or case["role"] not in ("CROSS_PAGE_TARGET", "SAME_LABEL_SAME_PAGE_CURRENCY_BLOCKED_CONTROL")
                or (case["role"] == "CROSS_PAGE_TARGET") != (len(pages) == 2)):
            raise ValueError("duplicate, nonadjacent or inconsistent continuation case")
        seen.add(key)
    return plan


def cash_contexts(page, before=None):
    return [w for w in page.words if (before is None or w.y < before) and len(w.text) <= 48
            and re.search(r"与(?:经营|投资|筹资)活动有关的现金", w.text)]


def nearest(words):
    if not words:
        return []
    last = max(w.y for w in words)
    return [w for w in words if abs(w.y - last) <= 2]


def payment_inventory(pdf):
    """Native exact labels, at most one previous page; context is NOT inherited."""
    rows = []
    for index, page in enumerate(pdf.pages):
        for w in page.words:
            if len(w.text) > 48 or w.text not in PAYMENTS:
                continue
            same = nearest(cash_contexts(page, w.y))
            prior_page = pdf.pages[index - 1] if index else None
            previous = nearest(cash_contexts(prior_page)) if prior_page is not None else []
            state = ("SAME_PAGE_CONTEXT_OBSERVED_NOT_CERTIFIED" if same
                     else "PREVIOUS_PAGE_CONTEXT_CANDIDATE_NOT_LINKED" if previous
                     else "NO_SAME_OR_PREVIOUS_PAGE_CONTEXT_IDENTIFIED")
            rows.append({"physical_page": page.number, "label": w.text, "label_box": list(w.box),
                         "context_state": state, "same_page_context": native_words(same),
                         "previous_page_number": prior_page.number if prior_page is not None else None,
                         "previous_page_context": native_words(previous), "classification_certified": False})
    return rows


def body_words(page):
    # These are search bounds and exact page-folio exclusions, NOT repaired text.
    return [w for w in page.words if 60 <= w.box[1] and w.box[3] <= page.height - 45
            and not re.fullmatch(r"[0-9]+/[0-9]+", w.text)]


def inspect_case(pdf, source, case):
    numbers = case["physical_pages"]
    if any(n > len(pdf.pages) for n in numbers):
        raise ValueError("continuation review outside source PDF")
    pages = [pdf.pages[n - 1] for n in numbers]
    if [p.number for p in pages] != numbers:
        raise ValueError("physical page order/identity drift")
    first, last = pages[0], pages[-1]
    labels = [w for w in last.words if w.text == TARGET_LABEL]
    row = labels[0] if len(labels) == 1 else None
    same = nearest(cash_contexts(last, row.y)) if row is not None else []
    previous = nearest(cash_contexts(first)) if len(pages) == 2 else []
    heading = previous[0] if len(previous) == 1 else None
    trailing = [w for w in body_words(first) if heading is not None and w.y > heading.y]
    groups = [g for g in _lines(last.words) if row is not None and g[0].y < row.y
              and any(compact(w.text) == "项目" for w in g)]
    group = max(groups, key=lambda g: g[0].y) if groups else []
    units = [w for w in last.words if group and w.y < group[0].y and "单位" in compact(w.text)]
    unit = max(units, key=lambda w: w.y) if units else None
    header = _header(last, (unit, *group), source["fiscal_year"], "lease", row) if unit and row else None
    amounts = (cell(last, last.words, row.y, header["label_right"], header["column_split"], header["unit_multiplier"])
               if header else {c: {"state": "HEADER_OR_UNIT_UNSUPPORTED", "value_cny": None, "raw_text": [], "boxes": []}
                               for c in ("current", "comparative")})
    starts = [(p.number, w.y) for p in pdf.pages for w in p.words if _title(w.text) == "合并财务报表项目注释"]
    ends = [(p.number, w.y) for p in pdf.pages for w in p.words if _title(w.text) == "母公司财务报表主要项目注释"]
    scope_observed = (len(starts) == len(ends) == 1 and row is not None
                      and starts[0] < (last.number, row.y) < ends[0]
                      and heading is not None and starts[0] < (first.number, heading.y) < ends[0])
    next_notes = [w for w in body_words(last) if re.match(r"[0-9]+[、.．][\u4e00-\u9fff]", w.text)
                  and (header is None or w.box[0] < header["label_right"])]
    next_boundary = min(next_notes, key=lambda w: w.y) if next_notes else None
    guards = {"adjacent_pages": len(pages) == 2 and last.number == first.number + 1,
              "same_unrotated_dimensions": all(p.rotation == 0 and abs(p.width - first.width) <= 1
                                                and abs(p.height - first.height) <= 1 for p in pages),
              "unique_complete_target_token": row is not None and inside(last, (row,)),
              "unique_previous_page_financing_payment_heading": heading is not None
                  and "支付" in heading.text and "与筹资活动有关的现金" in heading.text and inside(first, (heading,)),
              "only_applicability_after_heading": heading is not None
                  and all(w.text in ("√适用", "□不适用") for w in trailing),
              "no_same_page_competing_cash_context": not same,
              "first_same_page_table_header": bool(group) and group == groups[0],
              "same_page_supported_unit_and_two_columns": header is not None,
              "two_unambiguous_numeric_row_cells": all(amounts[c]["state"] == "OBSERVED_NUMERIC" for c in amounts),
              "next_note_after_target_and_header": next_boundary is not None and row is not None
                  and row.y < next_boundary.y and (not group or group[0].y < next_boundary.y),
              "inside_explicit_consolidated_note_interval": scope_observed}
    success = len(pages) == 2 and all(guards.values())
    return {"source": source, "role": case["role"],
            "state": "OBSERVED_CONTINUATION_CONDITIONS_NOT_CERTIFIED" if success
                     else "SAME_PAGE_CONTROL_NOT_CONTINUATION" if len(pages) == 1
                     else "CONTINUATION_CONDITIONS_NOT_CLOSED",
            "observed_guards": guards, "unsatisfied_guards": sorted(k for k, v in guards.items() if not v),
            "heading_page": first.number if heading else None, "heading_native_words": native_words(previous),
            "same_page_context_native_words": native_words(same), "post_heading_native_words": native_words(trailing),
            "target_row_native_words": native_words([w for w in last.words if row is not None and abs(w.y - row.y) <= 2]),
            "target_label": TARGET_LABEL if row else None, "target_page": last.number,
            "table_header_observation": header, "row_amount_observations": amounts,
            "next_note_native_words": native_words([next_boundary]) if next_boundary else [],
            "selected_pages": [page_record(p, source) for p in pages],
            "source_continuation_certified": False, "cash_classification_certified": False,
            "rule_input": None, "full_lease_cash": None, "available_at": None}


def target_table_reconciliation(pdf, case):
    """One selected table, bounded by the first header and next note; no backfill."""
    page = pdf.pages[case["target_page"] - 1]
    header = case["table_header_observation"]
    if header is None or not case["next_note_native_words"]:
        return None
    end = case["next_note_native_words"][0]["box"][1]
    labels = [w for w in page.words if header["header_bottom"] < w.y < end and w.box[0] < header["label_right"]]
    totals = [w for w in labels if w.text == "合计"]
    if len(totals) != 1:
        return None
    total = totals[0]
    components = [w for w in labels if w.y < total.y]
    values = [{"label": w.text, "label_box": list(w.box),
               "cells": cell(page, page.words, w.y, header["label_right"], header["column_split"], header["unit_multiplier"])}
              for w in components]
    total_values = cell(page, page.words, total.y, header["label_right"], header["column_split"], header["unit_multiplier"])
    checks = {}
    for c in ("current", "comparative"):
        complete = bool(values) and all(v["cells"][c]["state"] == "OBSERVED_NUMERIC" for v in values)
        if complete and total_values[c]["state"] == "OBSERVED_NUMERIC":
            with localcontext() as context:
                context.prec = 28
                subtotal = sum((Decimal(v["cells"][c]["value_cny"]) for v in values), Decimal(0))
                difference = subtotal - Decimal(total_values[c]["value_cny"])
            checks[c] = {"state": "SOURCE_ARITHMETIC_RECONCILED" if difference == 0 else "SOURCE_ARITHMETIC_MISMATCH",
                         "component_sum_cny": format(subtotal, "f"), "difference_cny": format(difference, "f")}
        else:
            checks[c] = {"state": "UNKNOWN_INCOMPLETE_COMPONENTS", "component_sum_cny": None, "difference_cny": None}
    return {"components": values, "total_native_cells": total_values, "checks": checks, "blank_filled_as_zero": False}


def build_assessment(raw, *, root=ROOT):
    plan = read_plan(raw)
    verify_parser(plan, root)
    frozen = {}
    for name in ("input_refs_scope", "baseline_private_report", "baseline_public_index"):
        ref = plan[name]
        frozen[name] = verified_bytes(root, ref["path"], ref["sha256"])
    inputs = read_assessment_scope(frozen["input_refs_scope"])
    baseline = strict_json(frozen["baseline_private_report"])
    if (canonical_bytes(baseline_index(baseline)) + b"\n" != frozen["baseline_public_index"]
            or inputs["as_of"] != plan["as_of"] or baseline["as_of"] != plan["as_of"]
            or baseline["manifest"]["parser_code_sha256"] != plan["parser_code_sha256"]
            or baseline["manifest"]["input_scopes"] != inputs["inputs"]):
        raise ValueError("continuation baseline/input identity mismatch")
    old = {source_key(r["source"]): r for r in baseline["observations"]}
    if len(old) != len(baseline["observations"]):
        raise ValueError("duplicate baseline source")
    selected = {source_key(c): c for c in plan["review_cases"]}
    cache, rows, cases, seen = PDFCache(), [], [], set()
    for ref in inputs["inputs"]:
        bundle = build_bundle(verified_bytes(root, ref["path"], ref["sha256"]), root=root, cache=cache)
        for item in bundle["bundles"]:
            source, component = item["source"], item["lease_financing_component"]
            key = source_key(source)
            if (key in seen or key not in old or source != old[key]["source"] or item["currency"] != old[key]["currency"]
                    or component != old[key]["current_component"] or bundle["as_of"] != plan["as_of"]):
                raise ValueError("continuation source or unchanged parser observation drift")
            seen.add(key)
            pdf = cache.parse(verified_bytes(root, source["pdf_path"], source["pdf_sha256"]), source["pdf_sha256"])
            rows.append({"source": source, "currency": item["currency"], "unchanged_lease_component": component,
                         "payment_label_locations_not_cash_certification": payment_inventory(pdf)})
            if key in selected:
                case = inspect_case(pdf, source, selected[key])
                case["unchanged_parser_currency"] = item["currency"]
                case["unchanged_parser_lease_component_state"] = component["state"]
                case["unchanged_parser_lease_component_value_cny"] = component["observed_value_cny"]
                case["target_table_source_reconciliation"] = target_table_reconciliation(pdf, case) if len(selected[key]["physical_pages"]) == 2 else None
                cases.append(case)
    if seen != set(old) or not set(selected).issubset(seen):
        raise ValueError("continuation sources/cases missing")
    verify_parser(plan, root)
    if (sha(Path(__file__).read_bytes()) != TOOL_SHA256
            or {p: sha((root / p).read_bytes()) for p in SUPPORT_PATHS} != LOADED_SUPPORT):
        raise ValueError("continuation assessment implementation drift")
    rows.sort(key=lambda r: source_key(r["source"]))
    cases.sort(key=lambda c: source_key(c["source"]))
    locations = [loc for row in rows for loc in row["payment_label_locations_not_cash_certification"]]
    report = {"schema": "annual-lease-continuation-assessment-v1", "diagnostic_only": True,
              "as_of": plan["as_of"], "scope_sha256": sha(raw), "method": plan["method"],
              "observations": rows, "selected_cases": cases,
              "counts": {"issuers": len({k[0] for k in seen}), "PDF_versions": len(rows),
                         "native_payment_label_locations": len(locations),
                         "previous_page_context_candidates_not_linked": sum(l["context_state"] == "PREVIOUS_PAGE_CONTEXT_CANDIDATE_NOT_LINKED" for l in locations),
                         "selected_cases": len(cases), "selected_pages": sum(len(c["selected_pages"]) for c in cases),
                         "selected_cross_page_conditions_observed": sum(c["state"] == "OBSERVED_CONTINUATION_CONDITIONS_NOT_CERTIFIED" for c in cases)},
              "search_boundary": plan["search"], "parser_modified": False,
              "manifest": {"parser_commit": plan["parser_commit"], "parser_code_sha256": plan["parser_code_sha256"],
                           "rule_sha256": RULE_SHA256, "tool_sha256": TOOL_SHA256, "support_code_sha256": LOADED_SUPPORT,
                           "input_refs_scope": plan["input_refs_scope"], "input_scopes": inputs["inputs"],
                           "baseline_private_report": plan["baseline_private_report"], "baseline_public_index": plan["baseline_public_index"],
                           "pdf_backend_version": pdf.backend_version, "python_version": sys.version.split()[0]},
              "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "diagnostic_available_at": None,
              "pit_admitted_observation_count": 0, **{k: False for k in PERMISSIONS}}
    report["logical_content_hash"] = content_hash(report)
    return report


def public_index(report):
    if (report.get("schema") != "annual-lease-continuation-assessment-v1" or report.get("diagnostic_only") is not True
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or report.get("parser_modified") is not False or report.get("diagnostic_available_at") is not None
            or type(report.get("pit_admitted_observation_count")) is not int or report["pit_admitted_observation_count"] != 0
            or any(report.get(k) is not False for k in PERMISSIONS)):
        raise ValueError("not a canonical source-only continuation assessment")
    def source_index(source):
        return {k: source[k] for k in ("security_id", "issuer", "fiscal_year", "version", "announcement_id", "url", "pdf_sha256", "page_count")}
    rows, cases = [], []
    for row in report["observations"]:
        locations = []
        for loc in row["payment_label_locations_not_cash_certification"]:
            if loc["label"] not in PAYMENTS:
                raise ValueError("non-allowlisted public payment label")
            locations.append({"label": loc["label"], "physical_page": loc["physical_page"], "label_box": numeric_box(loc["label_box"]),
                              "context_state": loc["context_state"], "previous_page_number": loc["previous_page_number"],
                              "same_page_context_sha256": sha(canonical_bytes(loc["same_page_context"])),
                              "previous_page_context_sha256": sha(canonical_bytes(loc["previous_page_context"])),
                              "classification_certified": False})
        rows.append({"source": source_index(row["source"]), "currency": row["currency"],
                     "unchanged_parser_lease_state": row["unchanged_lease_component"]["state"],
                     "unchanged_parser_lease_value_cny": row["unchanged_lease_component"]["observed_value_cny"],
                     "payment_locations_not_semantic_proof": locations})
    for case in report["selected_cases"]:
        if (any(type(v) is not bool for v in case["observed_guards"].values())
                or any(case[k] is not False for k in ("source_continuation_certified", "cash_classification_certified"))
                or any(case[k] is not None for k in ("rule_input", "full_lease_cash", "available_at"))):
            raise ValueError("continuation case contains nonboolean guards or promoted semantics")
        reconciliation = case["target_table_source_reconciliation"]
        cases.append({"source": source_index(case["source"]), "role": case["role"], "state": case["state"],
                      "observed_guards": case["observed_guards"], "unsatisfied_guards": case["unsatisfied_guards"],
                      "heading_page": case["heading_page"], "target_page": case["target_page"],
                      "heading_words_sha256": sha(canonical_bytes(case["heading_native_words"])),
                      "row_words_sha256": sha(canonical_bytes(case["target_row_native_words"])),
                      "header_sha256": sha(canonical_bytes(case["table_header_observation"])),
                      "row_amounts": {c: {"state": v["state"], "observed_value_cny_not_rule_input": v["value_cny"],
                                         "boxes": [numeric_box(b) for b in v["boxes"]]}
                                      for c, v in case["row_amount_observations"].items()},
                      "source_table_checks": reconciliation["checks"] if reconciliation else None,
                      "source_table_evidence_sha256": sha(canonical_bytes(reconciliation)),
                      "selected_pages": [{k: p[k] for k in ("document_sha256", "physical_page", "native_text_sha256", "state")}
                                         for p in case["selected_pages"]],
                      "source_continuation_certified": False, "cash_classification_certified": False,
                      "rule_input": None, "full_lease_cash": None, "available_at": None})
    index = {"schema": "annual-lease-continuation-public-index-v1", "diagnostic_only": True,
             "as_of": report["as_of"], "scope_sha256": report["scope_sha256"], "manifest": report["manifest"],
             "private_report_sha256": sha(canonical_bytes(report) + b"\n"), "private_report_logical_hash": report["logical_content_hash"],
             "counts": report["counts"], "observations": rows, "selected_cases": cases,
             "projection": "allowlisted short labels, source identities, numbers, numeric boxes and hashes; no page/token/header/paragraph text",
             "parser_modified": False, "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
             **{k: False for k in PERMISSIONS}}
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
            parser.error("continuation artifacts require unlinked private/public output paths")
    report = build_assessment(args.scope.read_bytes())
    artifacts = ((args.output, canonical_bytes(report) + b"\n"), (args.public_index, canonical_bytes(public_index(report)) + b"\n"))
    if args.check:
        if any(path.read_bytes() != raw for path, raw in artifacts):
            raise ValueError("continuation assessment/index byte mismatch")
    else:
        if any(path.exists() for path, _ in artifacts):
            raise ValueError("refusing to overwrite frozen continuation artifacts")
        for path, raw in artifacts:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
    print(report["logical_content_hash"])


if __name__ == "__main__":
    main()
