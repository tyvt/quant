"""Offline lease-label assessment, not a new financial parser or PIT admission.

Full selected pages and native candidate words stay under ignored storage/.
Publish only an explicit, text-minimized evidence index. Short literal labels
are form observations, never proof of complete or non-duplicated lease cash.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
import hashlib
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import RULE_SHA256, build_bundle, verified_bytes
from scripts.parsing.field_binder import inside
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.assess_annual_audit_narratives import read_assessment_scope, source_key
from scripts.pilots.capture_annual_holdout import verify_parser
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

TOOL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SUPPORT_PATHS = ("scripts/pilots/assess_annual_audit_narratives.py",
                 "scripts/pilots/capture_annual_holdout.py",
                 "scripts/pilots/capture_financial_2024_000637.py")
LOADED_SUPPORT_SHA256 = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SUPPORT_PATHS}
SUPPORTED = {"偿还租赁负债支付的金额", "租赁支付的现金"}
PAYMENT_VARIANTS = {"支付租赁款", "支付租赁负债", "偿还租赁负债款",
                    "偿还租赁负债本金和利息所支付的现金", "长期租赁付款"}
AGGREGATES = {"与租赁相关的总现金流出", "与租赁相关的现金流出总额"}
EXPENSES = {"短期租赁费用", "租赁负债利息费用", "租赁负债的利息费用",
            "简化处理的短期租赁或低价值资产的租赁费用"}
PUBLIC_LABELS = SUPPORTED | PAYMENT_VARIANTS | AGGREGATES | EXPENSES | {"租赁负债"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def numeric_box(box):
    if (not isinstance(box, list) or len(box) != 4
            or any(type(n) not in (int, float) or not math.isfinite(n) for n in box)
            or not 0 <= box[0] <= box[2] or not 0 <= box[1] <= box[3]):
        raise ValueError("coordinates must be four ordered finite numbers, never text")
    return list(box)


def form_state(text):
    """Classify exact literal *form*, without editing text or interpreting cash."""
    if text in SUPPORTED:
        return "EXISTING_PAYMENT_LABEL_SYNTAX"
    if text in PAYMENT_VARIANTS:
        return "UNSUPPORTED_PAYMENT_LABEL_SYNTAX"
    if text == "租赁负债":
        return "BARE_LIABILITY_LABEL_CONTEXT_REQUIRED"
    if text in AGGREGATES:
        return "AGGREGATE_CASH_LABEL_NOT_NON_DUPLICATED_INPUT"
    if text in EXPENSES:
        return "EXPENSE_LABEL_NOT_PAID_CASH_PROOF"
    return "OTHER_LEASE_TEXT_NOT_CLASSIFIED"


def branch_state(currency, component):
    if currency != "CNY":
        if component["observed_value_cny"] is not None or component["candidates"]:
            raise ValueError("currency-blocked record has an executed lease observation")
        return "NOT_EVALUATED_CURRENCY_BLOCKED"
    return ("EXISTING_COMPONENT_OBSERVED_NOT_FULL_LEASE"
            if component["observed_value_cny"] is not None
            else "EVALUATED_COMPONENT_UNKNOWN_NOT_AUTOMATIC_LABEL_GAP")


def read_lease_scope(raw):
    scope = strict_json(raw)
    if (not isinstance(scope, dict) or set(scope) != {
            "schema", "as_of", "method", "parser_commit", "parser_code_sha256",
            "input_refs_scope", "review_pages", "source_bridges"}
            or scope["schema"] != "annual-lease-assessment-scope-v1"
            or scope["method"] != "OFFLINE_POSTHOC_LABEL_ASSESSMENT_NOT_PARSER_FIX"):
        raise ValueError("invalid lease assessment scope")
    if not isinstance(scope["input_refs_scope"], dict) or set(scope["input_refs_scope"]) != {"path", "sha256"}:
        raise ValueError("invalid input scope reference")
    if not isinstance(scope["review_pages"], list) or not scope["review_pages"]:
        raise ValueError("explicit review pages required")
    keys = set()
    for review in scope["review_pages"]:
        if not isinstance(review, dict) or set(review) != {"security_id", "fiscal_year", "version", "physical_pages"}:
            raise ValueError("invalid review identity")
        pages = review["physical_pages"]
        key = source_key(review)
        if (key in keys or not isinstance(pages, list) or not pages
                or any(type(n) is not int or n < 1 for n in pages) or pages != sorted(set(pages))):
            raise ValueError("invalid/duplicate review pages")
        keys.add(key)
    if not isinstance(scope["source_bridges"], list):
        raise ValueError("invalid source bridges")
    seen = set()
    bridge_keys = {"security_id", "fiscal_year", "version", "physical_page", "statement_y_range",
                   "statement_words_sha256", "component_row_y", "component_label",
                   "total_current_cny", "total_comparative_cny", "financing_current_cny", "financing_comparative_cny"}
    for bridge in scope["source_bridges"]:
        if not isinstance(bridge, dict) or set(bridge) != bridge_keys:
            raise ValueError("invalid bridge fields")
        key = source_key(bridge)
        if key in seen or key not in keys or bridge["component_label"] not in SUPPORTED:
            raise ValueError("invalid/duplicate bridge identity")
        seen.add(key)
        bounds = bridge["statement_y_range"]
        if (not isinstance(bounds, list) or len(bounds) != 2
                or any(type(n) not in (int, float) for n in bounds) or not 0 <= bounds[0] < bounds[1]
                or type(bridge["physical_page"]) is not int
                or type(bridge["component_row_y"]) not in (float, int)
                or not re.fullmatch(r"[0-9a-f]{64}", bridge["statement_words_sha256"])):
            raise ValueError("invalid bridge geometry/hash")
        for name in ("total_current_cny", "total_comparative_cny", "financing_current_cny", "financing_comparative_cny"):
            if not isinstance(bridge[name], str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", bridge[name]):
                raise ValueError("invalid exact source bridge money")
    return scope


def native_words(words):
    return [{"text": word.text, "box": list(word.box)} for word in words]


def page_record(page, source):
    return {"document_sha256": source["pdf_sha256"], "physical_page": page.number,
            "native_text": page.text, "native_text_sha256": sha(page.text.encode("utf-8")),
            "native_words": native_words(page.words), "page_width": page.width,
            "page_height": page.height, "rotation": page.rotation,
            "all_words_inside_unrotated_page": inside(page, page.words),
            "state": "SELECTED_POSTHOC_SOURCE_PAGE_NOT_PARSER_OUTPUT"}


def inventory(pdf):
    """Bounded native-word search, not all lease events/labels or OCR coverage."""
    rows = []
    for page in pdf.pages:
        for word in page.words:
            if ("租赁" not in word.text and "租金" not in word.text) or len(word.text) > 48:
                continue
            rows.append({"physical_page": page.number, "raw_text": word.text,
                         "raw_text_sha256": sha(word.text.encode("utf-8")), "box": list(word.box),
                         "form_state": form_state(word.text),
                         "geometry_observed": inside(page, (word,)),
                         "cash_classification_certified": False, "is_complete_lease_cash": False})
    return rows


def observed_bridge(page, plan):
    """Verify a frozen, post-hoc source statement and its table; no generic parsing.

    This explicitly records a source dedup explanation. The source supplies it;
    the arithmetic does not infer it. No paragraph is stored in public code.
    """
    low, high = plan["statement_y_range"]
    words = tuple(w for w in page.words if low < w.box[1] < high)
    raw_words = native_words(words)
    row = tuple(w for w in page.words if abs(w.box[1] - plan["component_row_y"]) < .01)
    if (not words or not inside(page, words + row) or high > page.height
            or sha(canonical_bytes(raw_words)) != plan["statement_words_sha256"]):
        raise ValueError("source bridge statement/geometry mismatch")
    # Exact row, no finding the same total or debt-movement number elsewhere.
    expected = [plan["component_label"], format(Decimal(plan["financing_current_cny"]), ",.2f"),
                format(Decimal(plan["financing_comparative_cny"]), ",.2f")]
    if [w.text for w in row] != expected or not all(a.box[2] < b.box[0] for a, b in zip(row, row[1:])):
        raise ValueError("source bridge financing row mismatch")
    statement = "".join(w.text for w in words)  # Only validates the frozen local block, never a parser fallback.
    if any(format(Decimal(plan[k]), ",.2f") not in statement
           for k in ("total_current_cny", "total_comparative_cny")):
        raise ValueError("source bridge total money mismatch")
    with localcontext() as context:
        context.prec = 28
        current = Decimal(plan["total_current_cny"]) - Decimal(plan["financing_current_cny"])
        prior = Decimal(plan["total_comparative_cny"]) - Decimal(plan["financing_comparative_cny"])
    return {"state": "OBSERVED_SOURCE_DEDUP_BRIDGE_NOT_RULE_INPUT", "physical_page": page.number,
            "source_dedup_statement_observed": True, "statement_words_sha256": plan["statement_words_sha256"],
            "statement_native_words": raw_words, "financing_row_native_words": native_words(row),
            **{k: plan[k] for k in ("total_current_cny", "total_comparative_cny", "financing_current_cny", "financing_comparative_cny")},
            "operating_remainder_current_cny_observed_arithmetic": format(current, "f"),
            "operating_remainder_comparative_cny_observed_arithmetic": format(prior, "f"),
            "bridge_method": "FROZEN_POSTHOC_SOURCE_STATEMENT_AND_SAME_PAGE_ROW",
            "full_lease_cash_rule_input": None, "historical_available_at": None,
            "version_chain_complete": False, "production_semantics_certified": False}


def build_assessment(raw_scope, *, root=ROOT):
    scope = read_lease_scope(raw_scope)
    verify_parser(scope, root)
    if {p: sha((root / p).read_bytes()) for p in SUPPORT_PATHS} != LOADED_SUPPORT_SHA256:
        raise ValueError("assessment support implementation drift")
    refs = scope["input_refs_scope"]
    parent = read_assessment_scope(verified_bytes(root, refs["path"], refs["sha256"]))
    if parent["as_of"] != scope["as_of"]:
        raise ValueError("assessment as_of drift")
    reviews = {source_key(r): r["physical_pages"] for r in scope["review_pages"]}
    bridges = {source_key(b): b for b in scope["source_bridges"]}
    cache, rows, seen, backend = PDFCache(), [], set(), None
    for ref in parent["inputs"]:
        bundle = build_bundle(verified_bytes(root, ref["path"], ref["sha256"]), root=root, cache=cache)
        if bundle["as_of"] != scope["as_of"]:
            raise ValueError("mixed source as_of")
        for item in bundle["bundles"]:
            source = item["source"]
            key = source_key(source)
            if key in seen:
                raise ValueError("duplicate source across input scopes")
            seen.add(key)
            pdf = cache.parse(verified_bytes(root, source["pdf_path"], source["pdf_sha256"]), source["pdf_sha256"])
            backend = pdf.backend_version
            pages = reviews.get(key, [])
            if any(n > len(pdf.pages) for n in pages):
                raise ValueError("selected physical page outside PDF")
            bridge = bridges.get(key)
            if bridge and bridge["physical_page"] not in pages:
                raise ValueError("source bridge page not selected for review")
            component = item["lease_financing_component"]
            rows.append({"source": source, "currency": item["currency"],
                         "existing_lease_branch": branch_state(item["currency"], component),
                         "existing_lease_component": component,
                         "literal_inventory": inventory(pdf),
                         "selected_pages": [page_record(pdf.pages[n - 1], source) for n in pages],
                         "source_bridge": observed_bridge(pdf.pages[bridge["physical_page"] - 1], bridge) if bridge else None,
                         "full_lease_cash": None, "full_lease_cash_pit": None,
                         "FCF_conservative": None, "audit_gate": None})
    if not set(reviews).issubset(seen):
        raise ValueError("selected review identity absent from sources")
    verify_parser(scope, root)
    if (sha(Path(__file__).read_bytes()) != TOOL_SHA256
            or {p: sha((root / p).read_bytes()) for p in SUPPORT_PATHS} != LOADED_SUPPORT_SHA256
            or sha((root / "RULE_SPEC.md").read_bytes()) != RULE_SHA256):
        raise ValueError("assessment tool changed during execution")
    rows.sort(key=lambda r: source_key(r["source"]))
    report = {"schema": "annual-lease-label-assessment-v1", "diagnostic_only": True,
              "as_of": scope["as_of"], "method": scope["method"],
              "scope_sha256": sha(raw_scope), "observations": rows,
              "counts": {"issuers": len({k[0] for k in seen}), "PDF_versions": len(rows),
                         "existing_component_observed_PDFs": sum(r["existing_lease_branch"] == "EXISTING_COMPONENT_OBSERVED_NOT_FULL_LEASE" for r in rows),
                         "evaluated_component_unknown_PDFs": sum(r["currency"] == "CNY" and r["existing_lease_component"]["observed_value_cny"] is None for r in rows),
                         "not_evaluated_currency_blocked_PDFs": sum(r["currency"] != "CNY" for r in rows),
                         "selected_pages": sum(len(r["selected_pages"]) for r in rows),
                         "source_dedup_bridges_observed": sum(r["source_bridge"] is not None for r in rows)},
              "inventory_boundary": "native words with 租赁 or 租金; at most 48 characters; no OCR, joining or exhaustive lease-event claim",
              "manifest": {"parser_commit": scope["parser_commit"], "parser_code_sha256": scope["parser_code_sha256"],
                           "tool_sha256": TOOL_SHA256, "rule_sha256": RULE_SHA256,
                           "support_code_sha256": LOADED_SUPPORT_SHA256,
                           "python_version": sys.version.split()[0],
                           "input_refs_scope": refs, "input_scopes": parent["inputs"], "pdf_backend_version": backend},
              "parser_modified": False, "diagnostic_available_at": None,
              "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "pit_admitted_observation_count": 0,
              "screening_input_exported": False, "production_reader_ready": False,
              "real_pit_run_authorized": False, "official_selection": False}
    report["logical_content_hash"] = content_hash(report)
    return report


def public_index(report):
    """Explicit projection: no raw pages/words/paragraphs or unlisted snippets."""
    if (report.get("schema") != "annual-lease-label-assessment-v1"
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})):
        raise ValueError("invalid local lease report identity")
    rows = []
    for row in report["observations"]:
        labels = []
        for item in row["literal_inventory"]:
            if item["raw_text"] not in PUBLIC_LABELS:
                continue
            labels.append({"label": item["raw_text"], "physical_page": item["physical_page"],
                           "box": numeric_box(item["box"]), "raw_text_sha256": item["raw_text_sha256"],
                           "form_state": item["form_state"], "geometry_observed": item["geometry_observed"]})
        bridge = row["source_bridge"]
        if bridge is not None:
            allowed = {"state", "physical_page", "source_dedup_statement_observed", "statement_words_sha256",
                       "total_current_cny", "total_comparative_cny", "financing_current_cny", "financing_comparative_cny",
                       "operating_remainder_current_cny_observed_arithmetic", "operating_remainder_comparative_cny_observed_arithmetic",
                       "bridge_method", "full_lease_cash_rule_input", "historical_available_at", "version_chain_complete", "production_semantics_certified"}
            bridge = {k: bridge[k] for k in sorted(allowed)}
        rows.append({"source": {k: row["source"][k] for k in (
                         "security_id", "issuer", "fiscal_year", "version", "announcement_id", "url", "pdf_sha256", "page_count")},
                     "currency": row["currency"], "existing_lease_branch": row["existing_lease_branch"],
                     "existing_component_state": row["existing_lease_component"]["state"],
                     "existing_component_observed_value_cny": row["existing_lease_component"]["observed_value_cny"],
                     "literal_labels_not_semantic_proof": labels,
                     "selected_pages": [{k: p[k] for k in ("document_sha256", "physical_page", "native_text_sha256", "state")}
                                        for p in row["selected_pages"]], "source_bridge": bridge,
                     "full_lease_cash": None, "full_lease_cash_pit": None, "FCF_conservative": None})
    result = {"schema": "annual-lease-public-evidence-index-v1", "diagnostic_only": True,
              "as_of": report["as_of"], "private_report_logical_hash": report["logical_content_hash"],
              "private_report_file_sha256": sha(canonical_bytes(report) + b"\n"),
              "scope_sha256": report["scope_sha256"], "manifest": report["manifest"],
              "counts": report["counts"], "observations": rows,
              "projection": "allowlisted short labels and metadata only; no complete page/word text or source statement",
              "parser_modified": False, "pit_admitted_observation_count": 0,
              "diagnostic_available_at": None, "production_reader_ready": False,
              "screening_input_exported": False, "real_pit_run_authorized": False, "official_selection": False}
    result["logical_content_hash"] = content_hash(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-index", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(argv)
    if (args.output.resolve() != args.output.absolute()
            or not args.output.resolve().is_relative_to((ROOT / "storage").resolve())):
        parser.error("full source report must remain below storage/")
    if (args.public_index.resolve() != args.public_index.absolute()
            or not args.public_index.resolve().is_relative_to((ROOT / "docs/data-pilots").resolve())):
        parser.error("public index must be an unlinked workspace data-pilots path")
    if args.check and args.render:
        parser.error("--check does not write renders")
    report = build_assessment(args.scope.read_bytes())
    artifacts = ((args.output, canonical_bytes(report) + b"\n"),
                 (args.public_index, canonical_bytes(public_index(report)) + b"\n"))
    if args.check:
        if any(path.read_bytes() != raw for path, raw in artifacts):
            raise ValueError("lease assessment/index byte mismatch")
    else:
        if any(path.exists() for path, _ in artifacts):
            raise ValueError("refusing to overwrite a frozen assessment/index")
        for path, raw in artifacts:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
        if args.render:
            import fitz
            images = args.output.parent / "review-renders"
            images.mkdir(exist_ok=False)
            for row in report["observations"]:
                source = row["source"]
                with fitz.open(stream=verified_bytes(ROOT, source["pdf_path"], source["pdf_sha256"]), filetype="pdf") as pdf:
                    for page in row["selected_pages"]:
                        number = page["physical_page"]
                        pdf[number - 1].get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False).save(
                            str(images / f"{source['security_id']}-{source['version']}-{number}.png"))
    print(report["logical_content_hash"])


if __name__ == "__main__":
    main()
