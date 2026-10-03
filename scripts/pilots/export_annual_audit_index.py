"""Explicit public projection: no page, paragraph, or native word text export."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash


TYPE_TEXT = {"标准的无保留意见", "带强调事项段的无保留意见"}
SOURCE_KEYS = ("security_id", "issuer", "fiscal_year", "version", "pdf_sha256",
               "url", "announcement_id", "page_count")
BLOCK_STATES = {"NOT_IDENTIFIED", "TITLE_PAIR_MISSING_OR_NOT_UNIQUE", "TITLE_PAIR_NOT_SAME_PAGE_ORDER",
                "BLOCK_GEOMETRY_UNSUPPORTED", "NESTED_OR_OTHER_SECTION_UNSUPPORTED",
                "NON_ANNUAL_AUDIT_CONTEXT_UNSUPPORTED", "OBJECT_OR_OPINION_SENTENCE_UNSUPPORTED",
                "OBJECT_PERIOD_OR_COMPLETENESS_UNSUPPORTED", "OBSERVED_NARRATIVE_OPINION_BLOCK_NOT_TYPE",
                "NOT_EVALUATED_TABLE_TYPE_TEXT_ALREADY_OBSERVED"}


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid public digest")
    return value


def boxes(values):
    if any(not isinstance(b, list) or len(b) != 4 or any(type(x) not in (int, float) for x in b) for b in values):
        raise ValueError("public geometry must contain only four numeric coordinates")
    return values


def public_index(raw):
    report = strict_json(raw)
    if (report.get("schema") not in ("annual-audit-assessment-diagnostic-v1", "annual-audit-block-diagnostic-v1")
            or report.get("diagnostic_only") is not True
            or any(report.get(k) is not False for k in ("screening_input_exported", "real_pit_run_authorized",
                                                       "production_reader_ready", "official_selection"))
            or type(report.get("pit_admitted_observation_count")) is not int
            or report["pit_admitted_observation_count"] != 0
            or report.get("diagnostic_available_at") is not None
            or raw != canonical_bytes(report) + b"\n"
            or report.get("logical_content_hash") != content_hash(
                {k: v for k, v in report.items() if k != "logical_content_hash"})):
        raise ValueError("not a canonical source-only audit diagnostic")
    rows = []
    allowed_counts = {"issuers", "PDF_versions", "legacy_raw_type_identified", "legacy_raw_type_unknown",
                      "selected_review_pages", "narrative_raw_blocks_observed", "narrative_raw_blocks_unresolved"}
    if (not isinstance(report["counts"], dict) or set(report["counts"]) - allowed_counts
            or any(type(n) is not int or n < 0 for n in report["counts"].values())):
        raise ValueError("invalid audit diagnostic counts")
    for row in report["observations"]:
        audit = row["legacy_audit_text_observation"] if "legacy_audit_text_observation" in row else row["audit_text_observation"]
        pages = []
        for page in row.get("selected_page_observations", []):
            # Removing native_text alone is insufficient: word text reconstructs it.
            pages.append({k: page[k] for k in ("document_sha256", "physical_page", "evidence_ref",
                                               "native_text_sha256", "page_width", "page_height", "rotation")})
            pages[-1].update(native_word_count=len(page["native_words"]),
                             native_word_boxes=boxes([w["box"] for w in page["native_words"]]))
        block = audit.get("narrative_opinion_block")
        public_block = None
        if block is not None:
            if block["state"] not in BLOCK_STATES:
                raise ValueError("unknown narrative observation state")
            public_block = {"state": block["state"], "physical_page": block.get("physical_page"),
                            "opinion_type_inferred": None, "audit_gate_result": None,
                            "report_object_verified": False, "public_availability_verified": False,
                            "latest_audit_version_verified": False}
            if block.get("lines"):
                body = canonical_bytes(block["lines"])
                public_block.update(native_block_sha256=hashlib.sha256(body).hexdigest(),
                                    native_line_count=len(block["lines"]),
                                    native_word_boxes=boxes([w["box"] for line in block["lines"] for w in line["words"]]),
                                    binding={k: block["binding"][k] for k in
                                             ("document_sha256", "physical_page", "opinion_heading_box", "basis_heading_box")})
        raw_type = audit["raw_opinion_type"]
        rows.append({"source": {k: row["source"][k] for k in SOURCE_KEYS if k in row["source"]},
                     "legacy_raw_type_text": raw_type if raw_type in TYPE_TEXT else None,
                     "legacy_raw_type_identified": raw_type is not None,
                     "selected_page_indices": pages, "narrative_opinion_block_index": public_block})
    manifest = report["manifest"]
    provenance = {"scope_sha256": sha(report["scope_sha256"]),
                  "rule_sha256": sha(manifest["rule_sha256"]), "tool_sha256": sha(manifest["tool_sha256"]),
                  "parser_code_sha256": {k: sha(v) for k, v in manifest["parser_code_sha256"].items()}}
    from scripts.extract_annual_report_bundle import SOURCE_PATHS
    if set(provenance["parser_code_sha256"]) != set(SOURCE_PATHS):
        raise ValueError("invalid public parser whitelist")
    result = {"schema": "annual-audit-evidence-index-v1", "diagnostic_only": True,
              "publication_mode": "INDEX_NO_PAGE_OR_BODY_WORD_TEXT", "as_of": report["as_of"],
              "private_report_sha256": hashlib.sha256(raw).hexdigest(),
              "private_report_logical_content_hash": report["logical_content_hash"],
              "counts": report["counts"], "provenance": provenance, "observations": rows,
              "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
              "screening_input_exported": False, "real_pit_run_authorized": False,
              "production_reader_ready": False, "official_selection": False}
    result["logical_content_hash"] = content_hash(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    raw = canonical_bytes(public_index(args.report.read_bytes())) + b"\n"
    if args.check:
        if args.output.read_bytes() != raw:
            raise ValueError("public audit index identity mismatch")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(raw)
    print(hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
