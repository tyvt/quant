"""Offline post-hoc audit-page inventory; does NOT implement narrative parsing.

Run only the unchanged legacy table-label audit observer. Explicit review pages
preserve native text/words/geometry, not an inferred opinion type, report object,
going-concern finding, latest version or hard-gate result. No network or clocks.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import RULE_SHA256, read_scope, verified_bytes
from scripts.parsing.annual_report_parser import _audit
from scripts.parsing.field_binder import compact, inside
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.capture_annual_holdout import verify_parser
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

TOOL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def source_key(source):
    return source["security_id"], source["fiscal_year"], source["version"]


def page_observation(page, source):
    """Literal surface evidence only. Do not merge lines or classify opinions."""
    text = compact(page.text)
    return {
        "document_sha256": source["pdf_sha256"], "physical_page": page.number,
        "evidence_ref": f"pdf:sha256:{source['pdf_sha256']}:physical-page:{page.number}",
        "native_text": page.text, "native_text_sha256": hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
        "native_words": [{"text": word.text, "box": list(word.box)} for word in page.words],
        "page_width": page.width, "page_height": page.height, "rotation": page.rotation,
        "all_native_words_inside_unrotated_page": inside(page, page.words),
        "literal_markers_not_semantic_proof": {
            "legacy_opinion_type_word": any(compact(word.text) == "审计意见类型" for word in page.words),
            "legacy_body_label": "审计报告正文" in text,
            "legacy_report_number_label": "审计报告文号" in text,
            "declared_issuer_characters": compact(source["issuer"]) in text,
            "declared_period_end_characters": f"{source['fiscal_year']}年12月31" in text,
            "narrative_opinion_heading_characters": "审计意见" in text,
            "we_audited_characters": "我们审计了" in text,
            "we_believe_characters": "我们认为" in text,
        },
        "state": "OBSERVED_SELECTED_NATIVE_PAGE_NOT_OPINION_TYPE",
        "opinion_type_inferred": None, "report_object_verified": False,
        "whole_audit_report_reviewed": False, "public_availability_verified": False,
        "latest_audit_version_verified": False, "audit_gate_result": None,
    }


def read_assessment_scope(raw):
    value = strict_json(raw)
    keys = {"schema", "as_of", "parser_commit", "parser_code_sha256", "inputs", "baseline_reports",
            "review_pages", "method"}
    if (not isinstance(value, dict) or set(value) != keys
            or value["schema"] != "annual-audit-assessment-scope-v1"
            or value["method"] != "EXPLICIT_POSTHOC_NATIVE_PAGES_NOT_NARRATIVE_PARSER_OR_BLIND_RUN"):
        raise ValueError("invalid audit assessment scope")
    for key in ("inputs", "baseline_reports", "review_pages"):
        if not isinstance(value[key], list) or not value[key]:
            raise ValueError("nonempty explicit assessment references required")
    for key in ("inputs", "baseline_reports"):
        seen = set()
        for ref in value[key]:
            if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                    or not isinstance(ref["path"], str) or ref["path"] in seen):
                raise ValueError("invalid/duplicate assessment reference")
            seen.add(ref["path"])
    seen = set()
    for review in value["review_pages"]:
        if not isinstance(review, dict) or set(review) != {"security_id", "fiscal_year", "version", "physical_pages"}:
            raise ValueError("invalid review identity")
        identity = source_key(review)
        pages = review["physical_pages"]
        if (identity in seen or not isinstance(pages, list) or not pages
                or any(type(n) is not int or n < 1 for n in pages) or pages != sorted(set(pages))):
            raise ValueError("duplicate identity or invalid review pages")
        seen.add(identity)
    return value


def baseline_sources(refs, root):
    sources = {}
    for ref in refs:
        raw = verified_bytes(root, ref["path"], ref["sha256"])
        report = strict_json(raw)
        if (report.get("diagnostic_only") is not True or report.get("production_reader_ready") is not False
                or type(report.get("pit_admitted_observation_count")) is not int
                or report["pit_admitted_observation_count"] != 0
                or report.get("logical_content_hash") != content_hash({k: v for k, v in report.items()
                                                                       if k != "logical_content_hash"})):
            raise ValueError("baseline report is not a valid source-only diagnostic")
        if report.get("schema") == "annual-gap-map-diagnostic-v1":
            records = [(r["source"], r["audit_raw_type_identified"]) for r in report["observations"]]
        elif report.get("schema") == "annual-source-bundle-diagnostic-v1":
            records = [(r["source"], r["audit_text_observation"]["raw_opinion_type"] is not None)
                       for r in report["bundles"]]
        else:
            raise ValueError("unsupported baseline report")
        for source, identified in records:
            key = source_key(source)
            if key in sources or type(identified) is not bool:
                raise ValueError("duplicate baseline source or non-boolean audit state")
            sources[key] = (source, identified)
    return sources


def build_assessment(raw_scope, *, root=ROOT):
    root = root.resolve()
    scope = read_assessment_scope(raw_scope)
    verify_parser(scope, root)
    if hashlib.sha256((root / "RULE_SPEC.md").read_bytes()).hexdigest() != RULE_SHA256:
        raise ValueError("RULE_SPEC baseline drift")
    baseline = baseline_sources(scope["baseline_reports"], root)
    sources = {}
    for ref in scope["inputs"]:
        parsed = read_scope(verified_bytes(root, ref["path"], ref["sha256"]))
        if parsed["as_of"] != scope["as_of"]:
            raise ValueError("mixed assessment as_of")
        for source in parsed["sources"]:
            key = source_key(source)
            if key in sources or key not in baseline or source != baseline[key][0]:
                raise ValueError("source identity drift or duplicate across scopes")
            sources[key] = source
    if set(sources) != set(baseline):
        raise ValueError("missing baseline sources")
    reviews = {source_key(r): r["physical_pages"] for r in scope["review_pages"]}
    expected_reviews = {key for key, (_, identified) in baseline.items() if not identified}
    if set(reviews) != expected_reviews:
        raise ValueError("explicit review set must match baseline unknowns")
    cache, records = PDFCache(), []
    for key, source in sorted(sources.items()):
        pdf = cache.parse(verified_bytes(root, source["pdf_path"], source["pdf_sha256"]), source["pdf_sha256"])
        if len(pdf.pages) != source["page_count"] or any(n > len(pdf.pages) for n in reviews.get(key, [])):
            raise ValueError("source/review physical page count mismatch")
        audit = _audit(pdf, source)  # Existing TABLE observer only; never a narrative fallback.
        if (audit["raw_opinion_type"] is not None) != baseline[key][1]:
            raise ValueError("legacy audit result drift from frozen baseline")
        records.append({"source": source, "legacy_audit_text_observation": audit,
                        "selected_page_observations": [page_observation(pdf.pages[n - 1], source)
                                                       for n in reviews.get(key, [])],
                        "narrative_opinion_type": None, "report_object_verified": False,
                        "whole_audit_report_reviewed": False, "latest_version_or_PIT_verified": False,
                        "audit_gate_result": None})
    verify_parser(scope, root)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != TOOL_SHA256:
        raise ValueError("assessment tool changed during run")
    report = {"schema": "annual-audit-assessment-diagnostic-v1", "diagnostic_only": True,
              "as_of": scope["as_of"], "scope_sha256": hashlib.sha256(raw_scope).hexdigest(),
              "method": scope["method"], "manifest": {
                  "parser_commit": scope["parser_commit"], "parser_code_sha256": scope["parser_code_sha256"],
                  "tool_sha256": TOOL_SHA256, "rule_sha256": RULE_SHA256,
                  "baseline_reports": scope["baseline_reports"], "input_scopes": scope["inputs"],
                  "pdf_backend": {"name": "PyMuPDF", "version": pdf.backend_version}},
              "counts": {"issuers": len({s[0] for s in sources}), "PDF_versions": len(sources),
                         "legacy_raw_type_identified": sum(r["legacy_audit_text_observation"]["raw_opinion_type"] is not None
                                                           for r in records),
                         "legacy_raw_type_unknown": len(expected_reviews), "selected_review_pages": sum(map(len, reviews.values()))},
              "observations": records, "narrative_parser_implemented": False,
              "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
              "screening_input_exported": False, "real_pit_run_authorized": False,
              "production_reader_ready": False, "official_selection": False}
    report["logical_content_hash"] = content_hash(report)
    return report


def markdown(report):
    lines = ["# 叙述式审计入口：原文评估（未实现解析器）", "",
             "只保存既有表格式观察和指定源页；不推断叙述式意见类型、最新版本、PIT 或审计硬门。", "",
             f"logical_content_hash：`{report['logical_content_hash']}`。", "",
             f"范围：{report['counts']['issuers']} 家，{report['counts']['PDF_versions']} 份 PDF；"
             f"既有原文类型已识别 {report['counts']['legacy_raw_type_identified']}，"
             f"未知 {report['counts']['legacy_raw_type_unknown']}。", "",
             "| 证券／年度／声明版本 | 既有表格式原文类型 | 事后指定物理页 |", "|---|---|---|"]
    for row in report["observations"]:
        source = row["source"]
        pages = [p["physical_page"] for p in row["selected_page_observations"]]
        lines.append(f"| {source['security_id']}／{source['fiscal_year']}／{source['version']} | "
                     f"{row['legacy_audit_text_observation']['raw_opinion_type'] or 'UNKNOWN'} | {pages} |")
    lines += ["", "指定页原文、词元及坐标见 JSON；未查整份审计，不把未见关键词当无强调事项或无持续经营不确定性。",
              "原文识别／报告对象和版本语义／硬门结论分离；所有叙述式类型及硬门结果保持 UNKNOWN。",
              "本报告不是新样本盲跑，不估计市场准确率；不合并币种、租赁或金额列修复。",
              "历史 PIT 准入 0，九域与真实策略编排 not_ready 不变。", ""]
    return "\n".join(lines).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build_assessment(args.scope.read_bytes())
    artifacts = {"diagnostic-only.json": canonical_bytes(result) + b"\n", "diagnostic-only.md": markdown(result)}
    if args.check:
        if any((args.output / name).read_bytes() != raw for name, raw in artifacts.items()):
            raise ValueError("assessment byte identity mismatch")
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        for name, raw in artifacts.items():
            with (args.output / name).open("xb") as stream:
                stream.write(raw)
    print(result["logical_content_hash"])


if __name__ == "__main__":
    main()
