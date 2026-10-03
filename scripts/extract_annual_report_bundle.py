"""Offline grouped PDF observations. Never produces admitted screening inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.parsing.annual_report_parser import parse_annual
from scripts.parsing.generic_extractor import PDFCache
from scripts.screening.contracts import canonical_bytes, content_hash

RULE_SHA256 = "db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812"
SOURCE_PATHS = ("scripts/parsing/__init__.py", "scripts/parsing/generic_extractor.py",
                "scripts/parsing/field_binder.py", "scripts/parsing/annual_report_parser.py",
                "scripts/extract_annual_report_bundle.py", "scripts/screening/contracts.py")
SOURCE_KEYS = {"security_id", "issuer", "fiscal_year", "version", "announcement_id",
               "url", "pdf_path", "pdf_sha256", "page_count"}


def _code_hashes(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}


LOADED_CODE_SHA256 = _code_hashes(ROOT)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"nonfinite JSON number: {value}")


def read_scope(raw: bytes) -> dict:
    from datetime import date

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
    if not isinstance(value, dict) or set(value) != {"schema", "as_of", "sources", "reference_reports"}:
        raise ValueError("unexpected annual extraction scope fields")
    if value["schema"] != "annual-source-bundle-scope-v1":
        raise ValueError("unsupported annual extraction scope")
    if not isinstance(value["as_of"], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value["as_of"]):
        raise ValueError("as_of must be an ISO date")
    date.fromisoformat(value["as_of"])
    if not isinstance(value["sources"], list) or not value["sources"]:
        raise ValueError("sources must be a nonempty array")
    keys, announcements = set(), set()
    for source in value["sources"]:
        if not isinstance(source, dict) or set(source) != SOURCE_KEYS:
            raise ValueError("unexpected source fields")
        if (not isinstance(source["security_id"], str)
                or not re.fullmatch(r"(?:sh|sz)\.[0-9]{6}", source["security_id"])
                or type(source["fiscal_year"]) is not int or source["fiscal_year"] < 1900
                or type(source["page_count"]) is not int or source["page_count"] <= 0
                or any(not isinstance(source[key], str) or not source[key].strip()
                       for key in SOURCE_KEYS - {"fiscal_year", "page_count"})):
            raise ValueError("invalid source identity/type")
        if (not re.fullmatch(r"[0-9a-f]{64}", source["pdf_sha256"])
                or not re.fullmatch(r"[0-9]+", source["announcement_id"])
                or not re.fullmatch(r"https://static\.cninfo\.com\.cn/finalpage/[0-9-]+/"
                                    + source["announcement_id"] + r"\.PDF", source["url"])):
            raise ValueError("source hash or official announcement URL identity mismatch")
        key = (source["security_id"], source["fiscal_year"], source["version"])
        if key in keys or source["announcement_id"] in announcements:
            raise ValueError("duplicate source/version/announcement identity")
        keys.add(key)
        announcements.add(source["announcement_id"])
    if not isinstance(value["reference_reports"], list):
        raise ValueError("reference_reports must be an array")
    paths = set()
    for ref in value["reference_reports"]:
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not isinstance(ref["path"], str) or not ref["path"]
                or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
                or ref["path"] in paths):
            raise ValueError("invalid/duplicate reference report")
        paths.add(ref["path"])
    return value


def verified_bytes(root: Path, relative: str, expected_hash: str) -> bytes:
    path = root / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
            or path.resolve() != path.absolute() or not path.resolve().is_relative_to(root.resolve())):
        raise ValueError("unsafe or linked source path")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError(f"fixed source/reference hash mismatch: {relative}")
    return raw


def build_bundle(raw_scope: bytes, *, root: Path = ROOT, cache: PDFCache | None = None) -> dict:
    root = root.resolve()
    scope = read_scope(raw_scope)
    rule_hash = hashlib.sha256((root / "RULE_SPEC.md").read_bytes()).hexdigest()
    if rule_hash != RULE_SHA256:
        raise ValueError("RULE_SPEC baseline drift")
    code_hashes = _code_hashes(root)
    if code_hashes != LOADED_CODE_SHA256:
        raise ValueError("annual extraction implementation changed during session; restart")
    reference_documents = []
    for ref in scope["reference_reports"]:
        raw = verified_bytes(root, ref["path"], ref["sha256"])
        report = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
        timing = report.get("timing_assumptions", {})
        direct_zero = type(report.get("pit_admitted_observation_count")) is int and report["pit_admitted_observation_count"] == 0
        limited_zero = (report.get("schema_version") == "limited_sample_diagnostic_v1"
                        and report.get("real_pit_strategy_run") is False
                        and report.get("production_reader_ready") is False
                        and report.get("official_selection") is False
                        and isinstance(timing, dict) and timing.get("policy") == "UNKNOWN_UNLESS_VERIFIED"
                        and "available_at" in timing and timing["available_at"] is None
                        and type(timing.get("admitted_pit_observation_count")) is int
                        and timing["admitted_pit_observation_count"] == 0)
        if report.get("diagnostic_only") is not True or not (direct_zero or limited_zero):
            raise ValueError("reference is not a frozen source-only diagnostic")
        reference_documents.extend(report.get("source_documents", []))
    cache = cache if cache is not None else PDFCache()
    bundles = []
    for source in sorted(scope["sources"], key=lambda item: (item["security_id"], item["fiscal_year"], item["version"])):
        raw = verified_bytes(root, source["pdf_path"], source["pdf_sha256"])
        pdf = cache.parse(raw, source["pdf_sha256"])
        if len(pdf.pages) != source["page_count"]:
            raise ValueError("fixed source physical page count mismatch")
        matched = [item for item in reference_documents if item["announcement_id"] == source["announcement_id"]]
        if any((item["sha256"], item["role"], item["path"], item["url"],
                item.get("physical_page_count", item.get("page_count"))) !=
               (source["pdf_sha256"], source["version"], source["pdf_path"], source["url"], source["page_count"])
               for item in matched):
            raise ValueError("source version/announcement disagrees with frozen references")
        bundle = parse_annual(pdf, source)
        bundle["version_identity_state"] = "MATCHED_FROZEN_REFERENCES" if matched else "DECLARED_ONLY_NOT_VERIFIED"
        bundles.append(bundle)
    result = {
        "schema": "annual-source-bundle-diagnostic-v1", "data_kind": "REAL_SOURCE_OBSERVATIONS_ONLY",
        "as_of": scope["as_of"], "diagnostic_only": True, "official_selection": False,
        "production_reader_ready": False, "real_pit_run_authorized": False,
        "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "diagnostic_available_at": None,
        "pit_admitted_observation_count": 0, "bundles": bundles,
        "rule_execution": "NOT_EXECUTED_SOURCE_EXTRACTION_ONLY",
        "screening_input_exported": False,
        "manifest": {"rule_version": "v1.3.2", "rule_sha256": rule_hash,
                     "scope_sha256": hashlib.sha256(raw_scope).hexdigest(),
                     "reference_reports": scope["reference_reports"],
                     "code_sha256": code_hashes,
                     "pdf_backend": {"name": "PyMuPDF", "version": pdf.backend_version},
                     "cache": "process_local_native_pdf_text_and_geometry_only_no_runtime_stats_in_identity"},
    }
    result["logical_content_hash"] = content_hash(result)
    return result


def markdown(report: dict) -> bytes:
    lines = ["# 年报整组提取 · 原文证据诊断", "",
             "不是真实 PIT 规则运行、官方 Top-N、真实选股或可发布回测；不构成投资建议。",
             "原文数值不自动成为历史可用输入。available_at 未证明，PIT 准入数量为 0。", "",
             f"logical_content_hash：`{report['logical_content_hash']}`。", ""]
    for bundle in report["bundles"]:
        source = bundle["source"]
        lines += [f"## {source['security_id']} · {source['fiscal_year']} · {source['version']}", "",
                  f"PDF SHA-256：`{source['pdf_sha256']}`。", "",
                  "| 原文依赖 | 本期观察（元） | 状态 | 物理页 |", "|---|---:|---|---|"]
        items = dict(bundle["fields"])
        items["lease_financing_component_NOT_FULL_LEASE"] = bundle["lease_financing_component"]
        for name in sorted(items):
            field = items[name]
            pages = sorted({row["binding"]["physical_page"] for row in field["candidates"]})
            lines.append(f"| {name} | {field['observed_value_cny'] or 'UNKNOWN'} | {field['state']} | {pages} |")
        opinion = bundle["audit_text_observation"]["raw_opinion_type"] or "UNKNOWN"
        lines += ["", f"审计类型原文：{opinion}；不据此判定更正后整份审计或审计硬门。",
                  f"合并资产负债表原文行候选：{len(bundle['balance_sheet_row_inventory'])} 行；",
                  "保留空白和全部行候选，但不宣称全部科目语义/完整性已认证。", "",
                  "保留缺口：完整 Lease_cash、精确 PIT、修订/撤回全集、跨年兼容性与更正后审计。", ""]
    lines += ["完整逐字段 PDF 哈希、页码、表头、原始单元格、坐标和未知状态见 JSON。",
              "依赖联接预览不能导出 GeneralFCFInputs；批量入口仍仅接受合成输入。", ""]
    return "\n".join(lines).encode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--render", action="store_true", help="render evidence pages inside a new output directory")
    args = parser.parse_args(argv)
    if args.check and args.render:
        parser.error("--render cannot modify an existing --check package")
    try:
        raw_scope = args.scope.read_bytes()
        cache = PDFCache()
        first = build_bundle(raw_scope, cache=cache)
        second = build_bundle(raw_scope, cache=cache)
        if canonical_bytes(first) != canonical_bytes(second):
            raise ValueError("cold/warm PDF cache content mismatch")
        artifacts = {"diagnostic-only.json": canonical_bytes(first) + b"\n",
                     "diagnostic-only.md": markdown(first)}
        if args.check:
            if any((args.output / name).read_bytes() != raw for name, raw in artifacts.items()):
                raise ValueError("existing extraction report content mismatch")
        else:
            args.output.mkdir(parents=True, exist_ok=False)
            for name, raw in artifacts.items():
                with (args.output / name).open("xb") as stream:
                    stream.write(raw)
            if args.render:
                import fitz
                for index, bundle in enumerate(first["bundles"]):
                    pages = {row["binding"]["physical_page"] for field in bundle["fields"].values()
                             for row in field["candidates"]}
                    pages.update(row["binding"]["physical_page"]
                                 for row in bundle["audit_text_observation"]["candidates"])
                    pages.update(row["binding"]["physical_page"]
                                 for row in bundle["lease_financing_component"]["candidates"])
                    for table in bundle["table_states"].values():
                        if "header" in table:
                            pages.add(table["header"]["physical_page"])
                            pages.add(table["header"].get("title_physical_page", table["header"]["physical_page"]))
                    pages.update(bundle["currency_evidence_pages"])
                    source = bundle["source"]
                    raw = verified_bytes(ROOT, source["pdf_path"], source["pdf_sha256"])
                    with fitz.open(stream=raw, filetype="pdf") as pdf:
                        for page in sorted(pages):
                            pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(
                                str(args.output / f"source-{index}-physical-page-{page}.png"))
        print(json.dumps({"logical_content_hash": first["logical_content_hash"],
                          "documents_parsed": cache.parsed_documents, "pdf_cache_hits": cache.cache_hits,
                          "pit_admitted": 0}))
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(2, f"annual source extraction stopped: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
