"""Offline native currency-form inventory, not a currency parser repair.

Only existing bounded policy subsections are searched. Never join tokens/rows,
rewrite punctuation, certify currency or export a financial screening input.
Full observations stay local; the public index has separate content identity.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import RULE_SHA256, SOURCE_PATHS, read_scope, verified_bytes
from scripts.parsing.annual_report_parser import _currency_section, _table, parse_annual
from scripts.parsing.field_binder import inside, union_box
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.assess_annual_audit_narratives import read_assessment_scope, source_key
from scripts.pilots.assess_annual_lease_labels import native_words, numeric_box, page_record, sha
from scripts.pilots.build_annual_note_suffix_regression import SUPPORT as NOTE_SUPPORT, public_index as parent_index
from scripts.pilots.capture_annual_holdout import verify_parser
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

SCHEMA = "annual-currency-comma-assessment"
METHOD = "OFFLINE_NATIVE_COMMA_FORM_ASSESSMENT_NOT_CURRENCY_PARSER_FIX"
SEARCH = {"scope": "EXISTING_BOUNDED_CURRENCY_SUBSECTION_ONLY", "native_word_contains": "记账本位币",
          "maximum_word_characters": 180, "join_tokens_or_rows": False}
EXACT = "本公司以人民币为记账本位币，本公司的个别子公司采用人民币以外的货币作为记账本位币。"
TARGET_FORM = "EXACT_ISSUER_COMMA_SUBSIDIARY_EXCEPTION_LITERAL_NOT_PROOF"
FORMS = {TARGET_FORM, "PERIOD_BEFORE_SUBSIDIARY_CONTEXT_LITERAL_NOT_PROOF",
         "OTHER_SUBSIDIARY_OR_SPLIT_COMMA_CONTEXT_NOT_PROOF", "CURRENCY_TEXT_WITHOUT_CHINESE_COMMA",
         "OTHER_COMMA_CURRENCY_TEXT_NOT_PROOF"}
STATES = {"NOT_SCANNED_SUBSECTION_NOT_IDENTIFIED", "OBSERVED_BOUNDED_NATIVE_FORMS_NOT_CURRENCY_PROOF"}
GUARD_KEYS = {"first_body_row_single_native_token", "same_page_as_subsection_heading", "native_membership_and_geometry",
              "heading_to_row_gap_bounded", "uncropped_origin_page"}
COUNT_KEYS = {"issuers", "PDF_versions", "unchanged_bundles_and_tables", "legacy_currency_identified",
              "legacy_currency_blocked", "subsections_not_scanned", "native_currency_words", "literal_surface_forms",
              "future_exact_form_candidates"}
PERMISSIONS = ("production_reader_ready", "screening_input_exported", "real_pit_run_authorized", "official_selection")
REFS = ("input_refs_scope", "baseline_private_report", "baseline_public_index")
SUPPORT = (*NOTE_SUPPORT, "scripts/pilots/build_annual_note_suffix_regression.py")
LOADED_SUPPORT = {p: sha((ROOT / p).read_bytes()) for p in SUPPORT}
TOOL_SHA256 = sha(Path(__file__).read_bytes())


def read_plan(raw):
    p = strict_json(raw)
    keys = {"schema", "as_of", "method", "parser_commit", "parser_code_sha256", "search", "review_pages", *REFS}
    if (not isinstance(p, dict) or set(p) != keys or p["schema"] != SCHEMA + "-scope-v1"
            or p["method"] != METHOD or p["search"] != SEARCH
            or type(p["search"].get("maximum_word_characters")) is not int
            or p["search"].get("join_tokens_or_rows") is not False
            or not isinstance(p["parser_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", p["parser_commit"])
            or not isinstance(p["as_of"], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", p["as_of"])):
        raise ValueError("invalid bounded currency assessment scope")
    date.fromisoformat(p["as_of"])
    code = p["parser_code_sha256"]
    if (not isinstance(code, dict) or set(code) != set(SOURCE_PATHS)
            or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in code.values())):
        raise ValueError("currency parser whitelist mismatch")
    for key in REFS:
        ref = p[key]
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"} or not isinstance(ref["path"], str)
                or not ref["path"] or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])):
            raise ValueError("invalid currency parent reference")
    reviews = p["review_pages"]
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("explicit review pages required")
    seen = set()
    for r in reviews:
        if (not isinstance(r, dict) or set(r) != {"security_id", "fiscal_year", "version", "physical_pages"}
                or not isinstance(r["security_id"], str) or not re.fullmatch(r"(?:sh|sz)\.[0-9]{6}", r["security_id"])
                or type(r["fiscal_year"]) is not int or not 1900 <= r["fiscal_year"] <= 9999
                or not isinstance(r["version"], str) or not r["version"]):
            raise ValueError("invalid currency review identity")
        key, pages = source_key(r), r["physical_pages"]
        if (key in seen or not isinstance(pages, list) or not pages
                or any(type(n) is not int or n < 1 for n in pages) or pages != sorted(set(pages))):
            raise ValueError("duplicate identity or invalid currency review pages")
        seen.add(key)
    return p


def surface_form(text):
    """Literal categories only; even an exact match never proves CNY."""
    if text == EXACT:
        return TARGET_FORM
    if re.match(r"(?:本公司|本集团)[^。]*记账本位币[^。]*。.*子公司", text):
        return "PERIOD_BEFORE_SUBSIDIARY_CONTEXT_LITERAL_NOT_PROOF"
    if "，" in text and "子公司" in text:
        return "OTHER_SUBSIDIARY_OR_SPLIT_COMMA_CONTEXT_NOT_PROOF"
    return "OTHER_COMMA_CURRENCY_TEXT_NOT_PROOF" if "，" in text else "CURRENCY_TEXT_WITHOUT_CHINESE_COMMA"


def inspect_section(pdf):
    section = _currency_section(pdf)  # Unchanged locator, NOT a new positive currency path.
    result = {"state": "NOT_SCANNED_SUBSECTION_NOT_IDENTIFIED", "bounds": {}, "native_form_observations": [],
              "excluded_overlength_words": 0, "currency_verified": False, "public_availability_verified": False}
    if section is None:
        return result
    result["state"] = "OBSERVED_BOUNDED_NATIVE_FORMS_NOT_CURRENCY_PROOF"
    lines = section["lines"]
    for key in ("start", "index", "section_end", "end"):
        page, words, _ = lines[section[key]]
        result["bounds"][key] = {"physical_page": page.number, "words": native_words(words), "box": union_box(words)}
    heading_page, heading, _ = lines[section["index"]]
    for pos in range(section["index"] + 1, section["section_end"]):
        page, words, _ = lines[pos]
        for word in words:
            if SEARCH["native_word_contains"] not in word.text:
                continue
            if len(word.text) > SEARCH["maximum_word_characters"]:
                result["excluded_overlength_words"] += 1
                continue
            guards = {"first_body_row_single_native_token": pos == section["index"] + 1 and len(words) == 1,
                      "same_page_as_subsection_heading": page.number == heading_page.number,
                      "native_membership_and_geometry": word in page.words and inside(page, (word,)),
                      "heading_to_row_gap_bounded": 0 <= word.box[1] - max(w.box[3] for w in heading) <= 48,
                      "uncropped_origin_page": page.cropbox == page.mediabox == (0, 0, page.width, page.height)}
            form = surface_form(word.text)
            result["native_form_observations"].append({"physical_page": page.number, "native_word": word.text,
                "box": list(word.box), "surface_form": form, "observed_guards": guards,
                "future_exact_form_candidate": form == TARGET_FORM and all(guards.values()),
                "currency_verified": False, "public_availability_verified": False})
    return result


def verify_code(p, root):
    verify_parser(p, root)
    if (sha((root / "RULE_SPEC.md").read_bytes()) != RULE_SHA256
            or {name: sha((root / name).read_bytes()) for name in SUPPORT} != LOADED_SUPPORT
            or sha(Path(__file__).read_bytes()) != TOOL_SHA256):
        raise ValueError("currency assessment implementation drift")


def build_assessment(raw, *, root=ROOT):
    root = root.resolve(); p = read_plan(raw); verify_code(p, root)
    refs = {key: verified_bytes(root, p[key]["path"], p[key]["sha256"]) for key in REFS}
    inputs, parent = read_assessment_scope(refs["input_refs_scope"]), strict_json(refs["baseline_private_report"])
    if (parent["schema"] != "annual-note-hyphen-subitem-regression-v1"
            or canonical_bytes(parent_index(parent)) + b"\n" != refs["baseline_public_index"]
            or inputs["as_of"] != p["as_of"] or parent["as_of"] != p["as_of"]
            or parent["manifest"]["parser_code_sha256"] != p["parser_code_sha256"]
            or parent["manifest"]["input_scopes"] != inputs["inputs"]):
        raise ValueError("currency assessment parent identity mismatch")
    old = {source_key(o["source"]): o for o in parent["observations"]}
    reviews = {source_key(r): r["physical_pages"] for r in p["review_pages"]}
    if len(old) != len(parent["observations"]) or not set(reviews).issubset(old):
        raise ValueError("duplicate or missing currency assessment source")
    rows, seen, cache = [], set(), PDFCache()
    for ref in inputs["inputs"]:
        scope = read_scope(verified_bytes(root, ref["path"], ref["sha256"]))
        if scope["as_of"] != p["as_of"]:
            raise ValueError("mixed currency assessment as_of")
        for reference in scope["reference_reports"]:
            verified_bytes(root, reference["path"], reference["sha256"])
        for source in scope["sources"]:
            key = source_key(source)
            if key in seen or key not in old or source != old[key]["source"]:
                raise ValueError("currency assessment source identity drift")
            pdf = cache.parse(verified_bytes(root, source["pdf_path"], source["pdf_sha256"]), source["pdf_sha256"])
            if len(pdf.pages) != source["page_count"] or any(n > len(pdf.pages) for n in reviews.get(key, [])):
                raise ValueError("currency source/review physical page count mismatch")
            bundle = parse_annual(pdf, source)
            tables = {k: (_table(pdf, source, k) if bundle["currency"] == "CNY" else
                         {"state": "CURRENCY_EVIDENCE_UNKNOWN", "rows": []}) for k in ("balance", "income", "cashflow")}
            if bundle != old[key]["baseline_snapshot"]["bundle"] or tables != old[key]["current_tables"]:
                raise ValueError("currency assessment changed existing bundle or tables")
            rows.append({"source": source, "legacy_currency": bundle["currency"],
                "legacy_bundle_sha256": content_hash(bundle), "legacy_tables_sha256": content_hash(tables),
                "bundle_and_tables_unchanged": True, "subsection_observation": inspect_section(pdf),
                "selected_page_observations": [page_record(pdf.pages[n - 1], source) for n in reviews.get(key, [])],
                "currency_inferred": None, "rule_input": None, "full_lease_cash": None,
                "full_lease_cash_pit": None, "FCF_conservative": None})
            seen.add(key)
    if seen != set(old):
        raise ValueError("currency assessment missing source")
    verify_code(p, root); rows.sort(key=lambda r: source_key(r["source"]))
    forms = [f for r in rows for f in r["subsection_observation"]["native_form_observations"]]
    result = {"schema": SCHEMA + "-v1", "diagnostic_only": True, "as_of": p["as_of"], "method": METHOD,
        "scope_sha256": sha(raw), "manifest": {"parser_commit": p["parser_commit"],
            "parser_code_sha256": p["parser_code_sha256"], "tool_sha256": TOOL_SHA256,
            "support_code_sha256": LOADED_SUPPORT, "rule_sha256": RULE_SHA256, "input_scopes": inputs["inputs"],
            "frozen_refs": {k: p[k] for k in REFS}, "pdf_backend_version": pdf.backend_version,
            "python_version": sys.version.split()[0]},
        "counts": {"issuers": len({k[0] for k in seen}), "PDF_versions": len(rows), "unchanged_bundles_and_tables": len(rows),
            "legacy_currency_identified": sum(r["legacy_currency"] == "CNY" for r in rows),
            "legacy_currency_blocked": sum(r["legacy_currency"] is None for r in rows),
            "subsections_not_scanned": sum(r["subsection_observation"]["state"] == "NOT_SCANNED_SUBSECTION_NOT_IDENTIFIED" for r in rows),
            "native_currency_words": len(forms), "literal_surface_forms": dict(sorted(Counter(f["surface_form"] for f in forms).items())),
            "future_exact_form_candidates": sum(f["future_exact_form_candidate"] for f in forms)},
        "observations": rows, "currency_support_implemented": False, "currency_verified_by_assessment": False,
        "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "diagnostic_available_at": None,
        "pit_admitted_observation_count": 0, **{k: False for k in PERMISSIONS}}
    result["logical_content_hash"] = content_hash(result)
    return result


def public_index(report):
    if (report.get("schema") != SCHEMA + "-v1" or report.get("diagnostic_only") is not True
            or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items() if k != "logical_content_hash"})
            or report.get("timing_policy") != "UNKNOWN_UNLESS_VERIFIED" or report.get("diagnostic_available_at") is not None
            or type(report.get("pit_admitted_observation_count")) is not int or report["pit_admitted_observation_count"] != 0
            or any(report.get(k) is not False for k in (*PERMISSIONS, "currency_support_implemented", "currency_verified_by_assessment"))):
        raise ValueError("invalid source-only currency assessment")
    counts = report["counts"]
    if (set(counts) != COUNT_KEYS
            or any(type(v) is not int or v < 0 for k, v in counts.items() if k != "literal_surface_forms")
            or not isinstance(counts["literal_surface_forms"], dict) or not set(counts["literal_surface_forms"]).issubset(FORMS)
            or any(type(v) is not int or v < 0 for v in counts["literal_surface_forms"].values())):
        raise ValueError("non-allowlisted currency counts")
    rows = []
    for r in report["observations"]:
        if (r["legacy_currency"] not in (None, "CNY") or r["bundle_and_tables_unchanged"] is not True
                or any(r[k] is not None for k in ("currency_inferred", "rule_input", "full_lease_cash", "full_lease_cash_pit", "FCF_conservative"))):
            raise ValueError("currency assessment evidence promotion")
        s = r["subsection_observation"]
        if s["state"] not in STATES or s["currency_verified"] is not False or s["public_availability_verified"] is not False:
            raise ValueError("currency subsection promotion")
        expected_bounds = set() if s["state"] == "NOT_SCANNED_SUBSECTION_NOT_IDENTIFIED" else {"start", "index", "section_end", "end"}
        if set(s["bounds"]) != expected_bounds:
            raise ValueError("non-allowlisted currency bounds")
        for b in s["bounds"].values():
            if type(b["physical_page"]) is not int or not 1 <= b["physical_page"] <= r["source"]["page_count"]:
                raise ValueError("invalid currency boundary page")
        forms = []
        for f in s["native_form_observations"]:
            if (f["surface_form"] not in FORMS or f["surface_form"] != surface_form(f["native_word"])
                    or type(f["physical_page"]) is not int or f["physical_page"] < 1
                    or f["currency_verified"] is not False or f["public_availability_verified"] is not False
                    or set(f["observed_guards"]) != GUARD_KEYS
                    or any(type(v) is not bool for v in f["observed_guards"].values())
                    or type(f["future_exact_form_candidate"]) is not bool
                    or f["future_exact_form_candidate"] != (f["surface_form"] == TARGET_FORM and all(f["observed_guards"].values()))):
                raise ValueError("currency form projection mismatch or promotion")
            forms.append({k: f[k] for k in ("physical_page", "surface_form", "observed_guards", "future_exact_form_candidate")}
                         | {"native_word_sha256": sha(f["native_word"].encode("utf-8")), "box": numeric_box(f["box"])})
        for p in r["selected_page_observations"]:
            if (type(p["physical_page"]) is not int or not 1 <= p["physical_page"] <= r["source"]["page_count"]
                    or not isinstance(p["native_text_sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", p["native_text_sha256"])):
                raise ValueError("invalid currency selected-page hash or page")
        rows.append({"source": {k: r["source"][k] for k in ("security_id", "issuer", "fiscal_year", "version", "url", "announcement_id", "pdf_sha256", "page_count")},
            **{k: r[k] for k in ("legacy_currency", "legacy_bundle_sha256", "legacy_tables_sha256", "bundle_and_tables_unchanged")},
            "subsection_state": s["state"], "subsection_bounds": {k: {"physical_page": b["physical_page"],
                "box": numeric_box(b["box"]), "native_words_sha256": sha(canonical_bytes(b["words"]))} for k, b in s["bounds"].items()},
            "native_form_observations": forms,
            "selected_page_hashes": [{"physical_page": p["physical_page"], "native_text_sha256": p["native_text_sha256"],
                "native_words_sha256": sha(canonical_bytes(p["native_words"]))} for p in r["selected_page_observations"]]})
    result = {"schema": SCHEMA + "-public-index-v1", "diagnostic_only": True, "as_of": report["as_of"],
        "scope_sha256": report["scope_sha256"], "manifest": report["manifest"], "counts": report["counts"], "observations": rows,
        "private_report_sha256": sha(canonical_bytes(report) + b"\n"), "private_report_logical_hash": report["logical_content_hash"],
        "projection": "source identities, form states, numeric coordinates and hashes only; no sentences or page words",
        "currency_support_implemented": False, "currency_verified_by_assessment": False,
        "diagnostic_available_at": None, "pit_admitted_observation_count": 0, **{k: False for k in PERMISSIONS}}
    result["logical_content_hash"] = content_hash(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("scope", "output", "public-index"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--check", action="store_true"); args = parser.parse_args(argv)
    for path, base in ((args.output, ROOT / "storage"), (args.public_index, ROOT / "docs/data-pilots")):
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(base.resolve()):
            parser.error("currency assessment requires unlinked private/public paths")
    if not args.check and any(p.exists() for p in (args.output, args.public_index)):
        raise ValueError("refusing to overwrite frozen currency assessment")
    report = build_assessment(args.scope.read_bytes())
    outputs = ((args.output, canonical_bytes(report) + b"\n"), (args.public_index, canonical_bytes(public_index(report)) + b"\n"))
    if args.check:
        if any(p.read_bytes() != raw for p, raw in outputs):
            raise ValueError("currency assessment/index byte mismatch")
    else:
        for path, raw in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
    print(report["logical_content_hash"])


if __name__ == "__main__":
    main()
