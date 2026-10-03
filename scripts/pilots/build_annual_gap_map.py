"""Offline uniform-code sample gap inventory, never market coverage or screening.

Re-run explicitly hashed existing scopes under frozen parser bytes. Engineering
priorities are proposed work order, not security rankings or hard-gate changes.
The synthetic note probes measure the existing binder; they do not extend it.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import build_bundle, read_scope, verified_bytes
from scripts.parsing.field_binder import cell
from scripts.parsing.generic_extractor import PDFCache, Page, Word
from scripts.pilots.capture_annual_holdout import verify_parser
from scripts.pilots.capture_financial_2024_000637 import strict_json
from scripts.screening.contracts import canonical_bytes, content_hash

TOOL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FAMILIES = (
    ("complex_note_reference", "复杂附注引用", 1, "先评估整单元格语法、原生行和非金额列边界；不认证引用目标。"),
    ("audit_type_unidentified", "审计类型原文未识别", 2, "先逐案定位叙述式证据；未识别不能统一归因于叙述式，也不等于审计失败。"),
    ("lease_component_unidentified", "租赁现金部分未识别", 3, "标签扩展只可能恢复已披露部分，不闭环完整租赁现金或去重。"),
    ("currency_unknown", "币种证据阻断", 4, "仍阻断主表；不把未知币种下未扫描的附注统计为没有附注缺口。"),
    ("column_edge_ambiguous", "目标金额列边界歧义", 5, "保留金额几何边界，不靠放宽容差填数。"),
)


def note_probes():
    """Synthetic geometry is explicit; known money is not a real issuer input."""
    result = []
    for tokens in (("7",), ("—",), ("七（1）",), ("七、1",), ("附注七",), ("七-1",),
                   ("7", "1"), ("-1",), ("+1",), ("1.2",), ("七（1",), ("1,2",)):
        notes = tuple(Word(text, (220 + i * 30, 100, 240 + i * 30, 110)) for i, text in enumerate(tokens))
        words = notes + (Word("100.00", (330, 100, 390, 110)), Word("90.00", (480, 100, 540, 110)))
        page = Page(1, 600, 800, 0, "synthetic", words)
        observed = cell(page, words, 105, 200, 450, 1, amount_left=300)
        result.append({"data_kind": "SYNTHETIC_BINDER_PROBE_NOT_ISSUER_DATA", "note_tokens": list(tokens),
                       "current_state": observed["current"]["state"],
                       "comparative_state": observed["comparative"]["state"],
                       "synthetic_current_value": observed["current"]["value_cny"],
                       "note_target_resolved": False, "note_semantics_certified": False})
    return result


def summarize(bundle, input_ref, report_hash):
    source = bundle["source"]
    blocked = []
    for row in bundle["balance_sheet_row_inventory"]:
        if "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE" not in (row["current"]["state"], row["comparative"]["state"]):
            continue
        binding = row["binding"]
        if binding["document_sha256"] != source["pdf_sha256"]:
            raise ValueError("row/source identity mismatch")
        blocked.append({"source_label": row["source_label"], "physical_page": binding["physical_page"],
                        "document_sha256": binding["document_sha256"], "evidence_ref": binding["evidence_ref"],
                        "label_box": binding["label_box"], "note": row["note_column_observation"],
                        "current_state": row["current"]["state"], "comparative_state": row["comparative"]["state"],
                        "note_target_resolved": False})
    fields = {key: {"state": value["state"], "observed": value["state"] == "OBSERVED_NUMERIC"
                    and value["observed_value_cny"] is not None} for key, value in sorted(bundle["fields"].items())}
    currency = bundle["currency"]
    return {"source": source, "scope_ref": input_ref, "regenerated_bundle_report_hash": report_hash,
            "currency": currency, "target_fields": fields,
            "target_observed_count": sum(value["observed"] for value in fields.values()),
            "note_inventory_scope": "ONLY_EXTRACTED_CONSOLIDATED_BALANCE_ROW_CANDIDATES" if currency
                                    else "NOT_EVALUABLE_CURRENCY_BLOCKED",
            "balance_row_candidate_count": len(bundle["balance_sheet_row_inventory"]),
            "complex_note_rows": blocked,
            "table_states": {key: value["state"] for key, value in bundle["table_states"].items()},
            "lease_component_identified": bundle["lease_financing_component"]["observed_value_cny"] is not None,
            "audit_raw_type_identified": bundle["audit_text_observation"]["raw_opinion_type"] is not None,
            "full_lease_known": False, "historical_available_at": None,
            "pit_admitted": False, "complete_statement_semantics_certified": False}


def family_summary(records):
    results = []
    for identifier, title, order, rationale in FAMILIES:
        hits = []
        for record in records:
            matches = {
                "complex_note_reference": bool(record["complex_note_rows"]),
                "audit_type_unidentified": not record["audit_raw_type_identified"],
                "lease_component_unidentified": record["currency"] is not None and not record["lease_component_identified"],
                "currency_unknown": record["currency"] is None,
                "column_edge_ambiguous": any(value["state"] == "COLUMN_EDGE_AMBIGUOUS"
                                             for value in record["target_fields"].values()),
            }
            if matches[identifier]:
                hits.append(record)
        results.append({"id": identifier, "title": title, "proposed_engineering_order": order,
                        "rationale": rationale, "affected_pdf_count": len(hits),
                        "affected_security_ids": sorted({r["source"]["security_id"] for r in hits}),
                        "affected_row_count": sum(len(r["complex_note_rows"]) for r in hits)
                                              if identifier == "complex_note_reference" else None,
                        "scope": "THIS_EXPLICIT_SAMPLE_ONLY_NOT_MARKET_PREVALENCE",
                        "cause_verified_by_count": False})
    return results


def build_map(raw_scope, *, root=ROOT):
    scope = strict_json(raw_scope)
    if (not isinstance(scope, dict) or set(scope) != {"schema", "as_of", "parser_commit", "parser_code_sha256", "inputs"}
            or scope["schema"] != "annual-gap-map-scope-v1" or not isinstance(scope["inputs"], list) or not scope["inputs"]):
        raise ValueError("invalid gap-map scope")
    verify_parser(scope, root)
    cache = PDFCache()
    scopes_seen, identities, records, report_manifests = set(), set(), [], []
    for ref in sorted(scope["inputs"], key=lambda item: item["path"]):
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"} or ref["path"] in scopes_seen):
            raise ValueError("invalid/duplicate input reference")
        scopes_seen.add(ref["path"])
        raw = verified_bytes(root, ref["path"], ref["sha256"])
        parsed = read_scope(raw)
        if parsed["as_of"] != scope["as_of"]:
            raise ValueError("mixed diagnostic as_of")
        report = build_bundle(raw, root=root, cache=cache)
        report_manifests.append(report["manifest"])
        for bundle in report["bundles"]:
            source = bundle["source"]
            identity = (source["security_id"], source["fiscal_year"], source["version"])
            if identity in identities:
                raise ValueError("duplicate issuer/year/version")
            identities.add(identity)
            records.append(summarize(bundle, ref, report["logical_content_hash"]))
    verify_parser(scope, root)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != TOOL_SHA256:
        raise ValueError("gap-map implementation changed during run")
    records.sort(key=lambda item: (item["source"]["security_id"], item["source"]["fiscal_year"], item["source"]["version"]))
    result = {"schema": "annual-gap-map-diagnostic-v1", "diagnostic_only": True, "as_of": scope["as_of"],
              "scope_sha256": hashlib.sha256(raw_scope).hexdigest(),
              "manifest": {"parser_commit": scope["parser_commit"], "parser_code_sha256": scope["parser_code_sha256"],
                           "tool_sha256": TOOL_SHA256,
                           "capture_guard_sha256": hashlib.sha256((root / "scripts/pilots/capture_annual_holdout.py").read_bytes()).hexdigest(),
                           "rule_sha256": report_manifests[0]["rule_sha256"],
                           "pdf_backend": report_manifests[0]["pdf_backend"]},
              "counts": {"issuers": len({r["source"]["security_id"] for r in records}), "PDF_versions": len(records)},
              "observations": records, "families": family_summary(records), "synthetic_note_probes": note_probes(),
              "limitations": ["选择样本不是随机市场抽样；不估计全市场比例或准确率。",
                              "统一当前代码重跑是回归盘点，不是新的独立盲跑。",
                              "附注仅统计已提取资产负债表行；币种阻断时不可评估，未扫描不等于无缺口。",
                              "审计／租赁未识别不证明未披露，不从计数推定版式原因。",
                              "工程工作顺序不是证券排名、规则变更或生产授权。"],
              "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
              "screening_input_exported": False, "real_pit_run_authorized": False,
              "production_reader_ready": False, "official_selection": False}
    result["logical_content_hash"] = content_hash(result)
    return result


def markdown(report):
    lines = ["# 年报缺口族：统一代码样本盘点", "", "仅工程诊断，不是企业硬门、证券排名或全市场覆盖证明。", "",
             f"logical_content_hash：`{report['logical_content_hash']}`。", "",
             f"范围：{report['counts']['issuers']} 家发行人，{report['counts']['PDF_versions']} 个 PDF 版本。", "",
             "## 工程优先级（建议，未执行修复）", "",
             "| 缺口信号 | PDF 数 | 发行人数 | 受阻资产负债表行 | 建议顺序 |",
             "|---|---:|---:|---:|---:|"]
    for family in report["families"]:
        rows = family["affected_row_count"] if family["affected_row_count"] is not None else "不适用"
        lines.append(f"| {family['title']} | {family['affected_pdf_count']} | {len(family['affected_security_ids'])} | {rows} | {family['proposed_engineering_order']} |")
    lines += ["", "## 逐版本结果（当前代码回归，不改写首次盲跑）", "",
              "| 证券／年度／声明版本 | 目标字段观察数 | 币种 | 复杂附注受阻行 |",
              "|---|---:|---|---:|"]
    for record in report["observations"]:
        source = record["source"]
        count = len(record["complex_note_rows"]) if record["currency"] else "不可评估"
        lines.append(f"| {source['security_id']}／{source['fiscal_year']}／{source['version']} | {record['target_observed_count']}/{len(record['target_fields'])} | {record['currency'] or 'UNKNOWN'} | {count} |")
    lines += ["", "## 现有附注守卫的合成探针（不是公司数据）", "",
              "| 原生词元 | 当前金额状态 | 引用目标已解析 |", "|---|---|---|"]
    for probe in report["synthetic_note_probes"]:
        lines.append(f"| {' / '.join(probe['note_tokens'])} | {probe['current_state']} | 否 |")
    lines += ["", "两个整数词元分别通过检查不证明附注唯一；本盘点未修改守卫、未接纳复杂引用。", ""]
    lines.extend("- " + text for text in report["limitations"])
    lines += ["", "完整租赁、可用时点、版本链等仍未闭环，PIT 准入 0，九域／真实策略编排 not_ready 不变。", ""]
    return "\n".join(lines).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build_map(args.scope.read_bytes())
    artifacts = {"diagnostic-only.json": canonical_bytes(result) + b"\n", "diagnostic-only.md": markdown(result)}
    if args.check:
        if any((args.output / name).read_bytes() != raw for name, raw in artifacts.items()):
            raise ValueError("gap-map byte identity mismatch")
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        for name, raw in artifacts.items():
            with (args.output / name).open("xb") as stream:
                stream.write(raw)
    print(result["logical_content_hash"])


if __name__ == "__main__":
    main()
