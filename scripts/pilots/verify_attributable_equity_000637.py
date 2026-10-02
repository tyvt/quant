"""Supplement fixed-document E, without changing frozen N/PIT diagnostics.

Reuse the original N verifier's money parsing and cross-page header checks.
Only same-security/period/scope/unit/version/PDF E and N may form source alpha.
This is neither a generic PDF adapter nor an authorised historical rule run.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import verify_minority_equity_000637 as minority
from turtle_quant.core.types import calculation_context, to_decimal


INPUTS = "docs/data-pilots/2026-10-02-attributable-equity-000637-inputs.json"
DEFAULT_OUTPUT = "docs/data-pilots/attributable-equity-000637-2026-10-02"
TOOL = "scripts/pilots/verify_attributable_equity_000637.py"
E_LABEL = "归属于母公司所有者权益合计"
JOIN_KEYS = ("security_id", "period_end", "statement_scope", "unit", "version", "document_sha256")
VERSIONS = (("original_2025_annual_report", "1225248741"),
            ("amended_2025_annual_report", "1225460240"))


def _row_cells(header_words: list, field_words: list, label: str) -> dict:
    if label not in (E_LABEL, "所有者权益合计"):
        raise ValueError("unsupported fixed-table corroboration row")
    target = minority._one(field_words, label)
    parent = minority._one(field_words, "2、母公司资产负债表")
    if target[3] >= parent[1]:
        raise ValueError("equity row is outside consolidated table")
    closing = minority._one(header_words, "期末余额")
    opening = minority._one(header_words, "期初余额")
    split = (closing[0] + closing[2] + opening[0] + opening[2]) / 4
    row_y = (target[1] + target[3]) / 2
    cells = [word for word in field_words
             if abs((word[1] + word[3]) / 2 - row_y) <= 1 and word[0] >= closing[0] - 45]
    columns = [[word for word in cells if (word[0] + word[2]) / 2 < split],
               [word for word in cells if (word[0] + word[2]) / 2 >= split]]
    if any(len(column) > 1 for column in columns):
        raise ValueError("ambiguous equity currency cell")
    values = [minority.parse_money_cell(column[0][4] if column else None) for column in columns]
    return {"closing_amount_cny": values[0], "opening_comparative_amount_cny": values[1],
            "closing_state": "UNKNOWN" if values[0] is None else "EXPLICIT_NUMERIC",
            "opening_comparative_state": "UNKNOWN" if values[1] is None else "EXPLICIT_NUMERIC"}


def extract_equity_bridge(header_text: str, header_words: list, continuation_text: str,
                          field_words: list) -> dict:
    # The unchanged N extractor first verifies issuer, period, unit, columns and continuation.
    n = minority.extract_row(header_text, header_words, continuation_text, field_words)
    e = _row_cells(header_words, field_words, E_LABEL)
    total = _row_cells(header_words, field_words, "所有者权益合计")
    checks = {}
    with calculation_context():
        for column in ("closing_amount_cny", "opening_comparative_amount_cny"):
            values = [item[column] for item in (e, n, total)]
            difference = (Decimal(values[2]) - Decimal(values[0]) - Decimal(values[1])
                          if all(value is not None for value in values) else None)
            if difference is not None and difference != 0:
                raise ValueError("same-column E + N differs from reported total equity")
            checks[column] = {"reported_total_equity_cny": total[column],
                              "difference_cny": format(difference, "f") if difference is not None else None,
                              "status": "UNKNOWN" if difference is None else "RECONCILED"}
    return {"E": e, "N": n, "total_equity_corroboration": checks,
            "column_basis": "cross_page_header_positions_not_linear_text_order",
            "parent_table_starts_below_target_rows": True}


def calculate_source_alpha(e: dict, n: dict) -> dict:
    if any(e.get(key) is None or e[key] != n.get(key) for key in JOIN_KEYS):
        raise ValueError("E/N security, period, scope, unit, version or PDF identity mismatch")
    if (e["statement_scope"] != "CONSOLIDATED" or e["unit"] != "CNY"
            or e.get("field") != "attributable_equity" or n.get("field") != "minority_interest"):
        raise ValueError("E/N source field or accounting basis mismatch")
    result = {"version": e["version"], "E_observed_cny": e["observed_value"],
              "N_observed_cny": n["observed_value"], "formula": "E / (E + max(N, 0))",
              "denominator_cny": None, "alpha_observed": None,
              "status": "UNKNOWN", "alpha_pit": None, "historical_pit_status": "UNKNOWN",
              "diagnostic_available_at": None,
              "alignment": {key: e[key] for key in JOIN_KEYS},
              "E_evidence_refs": e["evidence_refs"], "N_evidence_refs": n["evidence_refs"]}
    if e["observed_value"] is None or n["observed_value"] is None:
        result["unknown_reason"] = "missing source E or N is not zero"
        return result
    with calculation_context():
        equity, interest = to_decimal(e["observed_value"]), to_decimal(n["observed_value"])
        if equity <= 0:
            result["unknown_reason"] = "nonpositive source E cannot form the approved alpha proxy"
            return result
        denominator = equity + max(interest, Decimal("0"))
        alpha = equity / denominator
        if not 0 < alpha <= 1:
            raise ValueError("source alpha outside (0, 1]")
        result.update(denominator_cny=format(denominator, "f"), alpha_observed=format(alpha, "f"),
                      status="SOURCE_ARITHMETIC_ONLY_NOT_PIT")
    return result


def build_supplement(root: Path = ROOT, render_dir: Path | None = None) -> dict:
    import fitz

    root = root.resolve()
    raw_scope = (root / INPUTS).read_bytes()
    scope = base._json(raw_scope)
    required = {"schema_version": "attributable_equity_source_supplement_scope_v1",
                "security_id": "sz.000637", "issuer": "茂名石化实华股份有限公司",
                "target_field": "attributable_equity", "source_label": E_LABEL,
                "period_end": "2025-12-31", "statement_scope": "CONSOLIDATED", "unit": "CNY",
                "as_of": "2026-09-30", "timing_policy": "UNKNOWN_UNLESS_VERIFIED"}
    if (any(scope.get(key) != value for key, value in required.items())
            or scope["diagnostic_only"] is not True or scope["official_selection"] is not False
            or date.fromisoformat(scope["review_date"]) < date.fromisoformat(scope["as_of"])):
        raise ValueError("fixed E diagnostic scope mismatch")
    parent_ref = scope["parent_report"]
    parent = base._json(base.verified_bytes(root, parent_ref["path"], parent_ref["sha256"]))
    base.validate_report(parent)
    if (parent["logical_content_hash"] != parent_ref["logical_content_hash"]
            or parent["security_id"] != scope["security_id"] or parent["as_of"] != scope["as_of"]):
        raise ValueError("parent diagnostic identity mismatch")
    gap = next(item for item in parent["necessary_input_gaps"] if item["field"] == "FCF")
    if scope["target_field"] not in gap["missing_dependencies"]:
        raise ValueError("E is not an existing diagnostic dependency gap")
    n_ref = scope["minority_supplement"]
    n_raw = base.verified_bytes(root, n_ref["path"], n_ref["sha256"])
    n_report = base._json(n_raw)
    if (base.logical_content_hash(n_report) != n_ref["logical_content_hash"]
            or n_report["logical_content_hash"] != n_ref["logical_content_hash"]
            or n_report["manifest"]["parent_report"] != parent_ref):
        raise ValueError("frozen N supplement identity mismatch")
    if n_raw != base.canonical_bytes(minority.build_supplement(root)) + b"\n":
        raise ValueError("frozen N supplement does not reproduce from its source PDFs")
    if tuple((item["role"], item["announcement_id"]) for item in scope["documents"]) != VERSIONS:
        raise ValueError("frozen annual version identities changed")
    documents, observations, n_dependencies, arithmetic, render_inputs = [], [], [], [], []
    for target, doc, n_item in zip(scope["documents"], n_report["source_documents"], n_report["observations"]):
        if (doc["role"] != target["role"] or doc["announcement_id"] != target["announcement_id"]
                or doc["sha256"] != target["pdf_sha256"]
                or [target[key] for key in ("header_page", "continuation_page", "field_page")] != [93, 94, 95]):
            raise ValueError("fixed document identity or physical page bridge changed")
        raw = base.verified_bytes(root, doc["path"], doc["sha256"])
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            parsed = extract_equity_bridge(pdf[92].get_text(), pdf[92].get_text("words"),
                                           pdf[93].get_text(), pdf[94].get_text("words"))
        if (parsed["E"]["closing_amount_cny"] != target["expected_closing_E_cny"]
                or parsed["E"]["opening_comparative_amount_cny"] != target["expected_opening_comparative_E_cny"]):
            raise ValueError("frozen E observation disagrees with PDF cells")
        if (parsed["N"]["closing_amount_cny"] != n_item["observed_value"]
                or parsed["N"]["opening_comparative_amount_cny"] != n_item["opening_comparative_not_target_value"]):
            raise ValueError("same-PDF N row disagrees with frozen N supplement")
        e = {"field": "attributable_equity", "security_id": scope["security_id"],
             "period_end": scope["period_end"], "statement_scope": "CONSOLIDATED", "unit": "CNY",
             "version": doc["role"], "document_sha256": doc["sha256"],
             "observed_value": parsed["E"]["closing_amount_cny"],
             "opening_comparative_not_target_value": parsed["E"]["opening_comparative_amount_cny"],
             "source_observation_status": "VERIFIED_IN_THIS_FIXED_DOCUMENT",
             "extraction_checks": parsed, "evidence_refs": [base._ref(doc, page) for page in (93, 94, 95)],
             "historical_pit_status": "UNKNOWN", "pit_value": None}
        n = {**n_item, "document_sha256": doc["sha256"]}
        documents.append(doc)
        observations.append(e)
        n_dependencies.append(n)
        arithmetic.append(calculate_source_alpha(e, n))
        render_inputs.append((doc, raw))
    if render_dir is not None:
        render_dir.mkdir(parents=True, exist_ok=False)
        for doc, raw in render_inputs:
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                for page in (93, 95):
                    pdf[page - 1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(
                        str(render_dir / f'{doc["role"]}-physical-page-{page}.png'))
    report = {
        "schema_version": "attributable_equity_source_supplement_v1",
        "title": "茂化实华 2025 归母权益 E：原文补证与 alpha 算术（diagnostic_only=true）",
        "security_id": scope["security_id"], "as_of": scope["as_of"], "period_end": scope["period_end"],
        "review_date": scope["review_date"], "diagnostic_only": True, "official_selection": False,
        "real_pit_strategy_run": False, "production_reader_ready": False,
        "parent_report_unchanged": True, "minority_supplement_unchanged": True,
        "not_claimed": list(base.DISCLAIMERS), "timing_policy": "UNKNOWN_UNLESS_VERIFIED",
        "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
        "source_documents": documents, "observations": observations,
        "existing_N_dependencies": n_dependencies, "source_alpha_arithmetic_not_pit": arithmetic,
        "gap_resolution": {"target": "FCF.missing_dependencies.attributable_equity",
                           "source_observation_before": "NOT_BOUND_IN_PARENT_DIAGNOSTIC",
                           "source_observation_after": "KNOWN_FOR_TWO_FIXED_VERSIONS",
                           "amount_cny_per_version": observations[0]["observed_value"],
                           "version_difference_cny": "0.00", "historical_pit_after": "UNKNOWN",
                           "does_not_prove": "E/N 相同只证明目标原文观察一致，不证明其他科目、最新可见版本、审计、完整修订链或历史 PIT。"},
        "E_pit": None, "N_pit": None, "alpha_pit": None, "FCF": None,
        "remaining_unknowns": ["available_at", "latest_visible_version", "E_pit", "N_pit", "alpha_pit",
                               "OCF_pit", "capex_pit", "lease_cash_not_already_deducted",
                               "full_amended_audit_status", "complete_revision_chain", "five_year_FCF_and_six_equities"],
        "rule_execution": "NOT_EXECUTED_SOURCE_ALPHA_ARITHMETIC_ONLY",
        "visual_review": scope["visual_review"],
        "manifest": {"scope": {"path": INPUTS, "sha256": hashlib.sha256(raw_scope).hexdigest()},
                     "parent_report": parent_ref, "minority_supplement": n_ref,
                     "rule_identity": parent["manifest"]["rule_identity"],
                     "rule_version": parent["manifest"]["rule_version"],
                     "source_inputs": n_report["manifest"]["source_inputs"],
                     "catalogue_sources": n_report["manifest"]["catalogue_sources"],
                     "code_sources": [{"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}
                                      for path in (TOOL, minority.TOOL, "scripts/pilots/build_limited_diagnostics.py",
                                                   "turtle_quant/core/types.py")],
                     "dependencies": {"python": sys.version.split()[0], "pymupdf": fitz.VersionBind},
                     "arithmetic": "Decimal precision=28 ROUND_HALF_EVEN; source only, no PIT input",
                     "hash_scope": "canonical_utf8_sorted_keys_except_top_level_logical_content_hash"},
    }
    report["logical_content_hash"] = base.logical_content_hash(report)
    validate_supplement(report)
    return report


def validate_supplement(report: dict) -> None:
    if (report["diagnostic_only"] is not True or report["official_selection"] is not False
            or report["real_pit_strategy_run"] is not False or report["production_reader_ready"] is not False
            or report["diagnostic_available_at"] is not None or report["pit_admitted_observation_count"] != 0
            or report["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED"
            or report["parent_report_unchanged"] is not True or report["minority_supplement_unchanged"] is not True):
        raise ValueError("source supplement authority or timing changed")
    if (report["security_id"] != "sz.000637" or report["as_of"] != "2026-09-30"
            or report["period_end"] != "2025-12-31"):
        raise ValueError("fixed supplement security or period changed")
    if report["logical_content_hash"] != base.logical_content_hash(report):
        raise ValueError("source supplement content hash mismatch")
    if any(report[key] is not None for key in ("E_pit", "N_pit", "alpha_pit", "FCF")):
        raise ValueError("unverified source arithmetic promoted to PIT or FCF")
    if not (len(report["source_documents"]) == len(report["observations"]) == len(report["existing_N_dependencies"])
            == len(report["source_alpha_arithmetic_not_pit"]) == 2):
        raise ValueError("two fixed source versions required")
    if tuple((doc["role"], doc["announcement_id"]) for doc in report["source_documents"]) != VERSIONS:
        raise ValueError("fixed supplement source versions changed")
    for doc, e, n, arithmetic in zip(report["source_documents"], report["observations"], report["existing_N_dependencies"],
                                     report["source_alpha_arithmetic_not_pit"]):
        if any(e[key] != report[key] for key in ("security_id", "period_end")):
            raise ValueError("source observation security or period changed")
        if (e["version"] != doc["role"] or e["document_sha256"] != doc["sha256"]
                or e["evidence_refs"] != [base._ref(doc, page) for page in (93, 94, 95)]
                or n["evidence_refs"] != e["evidence_refs"]):
            raise ValueError("source observation PDF or physical page binding changed")
        if any(item["pit_value"] is not None or item["historical_pit_status"] != "UNKNOWN" for item in (e, n)):
            raise ValueError("source observation admitted as verified PIT input")
        if arithmetic != calculate_source_alpha(e, n):
            raise ValueError("source alpha arithmetic or same-version identity drift")
    forbidden = {"ranking", "rank", "top_n", "target_weights", "orders", "holdings", "nav", "tier"}

    def check_keys(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("forbidden selection or backtest output")
            for child in value.values():
                check_keys(child)
        elif isinstance(value, list):
            for child in value:
                check_keys(child)

    check_keys(report)


def render_markdown(report: dict) -> str:
    validate_supplement(report)
    lines = [f'# {report["title"]}', "", "## 本报告不宣称", ""]
    lines.extend(f"- {text}" for text in report["not_claimed"])
    lines += ["", "## 单一 UNKNOWN 与补证结果", "",
              '- 证券 `sz.000637`；`as_of=2026-09-30`；经济日期 `2025-12-31`；合并口径、人民币元。',
              '- 仅补原版/更正版的归母权益 E；N 复用既有冻结补证，不改写任何父报告或旧工具。', "",
              "| 固定版本 | E 原文（元） | 同版 N（元） | 原文 alpha（非 PIT） |",
              "|---|---:|---:|---:|"]
    for item in report["source_alpha_arithmetic_not_pit"]:
        lines.append(f'| {item["version"]} | {item["E_observed_cny"]} | {item["N_observed_cny"]} | {item["alpha_observed"]} |')
    lines += ["", '- `alpha_observed = E / (E + max(N, 0))`；28 位 Decimal 精度，仅原文算术，不是 alpha_pit。',
              '- 两版 E 期初比较值均为 `645132659.65`，不是目标期末值；总权益仅用于同列对平，不代替 E。',
              '- 期末 `504623362.49 + 94585884.15 = 599209246.64`；期初比较栏 `645132659.65 + 112947471.32 = 758080130.97`。',
              '- E、N 按证券、期间、合并范围、币种单位、版本及 PDF SHA-256 严格匹配，禁止跨版拼接。',
              '- 物理第 93 页核验表头，第 94 页核验连续性，第 95 页核验 E/N/总权益及其下方母公司表边界。',
              '- 1 点行对齐容差只用于两份固定 PDF；不宣称通用解析能力。缺格/空白保留 UNKNOWN，歧义硬失败。', "",
              "## 保留的时点与依赖缺口", "",
              '- `UNKNOWN_UNLESS_VERIFIED`；`diagnostic_available_at=null`；历史 PIT 观察准入数量仍为 0。',
              '- `E_pit/N_pit/alpha_pit/FCF=null`。目录日或抓取日不能倒填历史可用时点，不选最新可见版、不生成 F1–F5。',
              '- 未重复扣除租赁现金、完整修订链、整份更正后审计与五年窗口未闭环；不拿已知 alpha 凑完整 FCF。',
              '- 两版 E/N 一致，不证明两份财报全部一致；不调用前提/估值/未就绪 Reader，不解锁九域、Top-N 或回测。', "",
              "## 原文证据", ""]
    for doc in report["source_documents"]:
        lines += [f'### {doc["role"]}', "", f'- 公告 `{doc["announcement_id"]}`；[法定 PDF]({doc["url"]})。',
                  f'- 本地 bytes：`{doc["path"]}`；SHA-256：`{doc["sha256"]}`；字段物理第 95 页，表头/连续页 93/94。',
                  f'- 目录时间 `{doc["catalogue_announcement_time_beijing"]}`，不证明最早公众可见。', ""]
    lines += ["## 可复现身份", "",
              f'- 父诊断内容哈希：`{report["manifest"]["parent_report"]["logical_content_hash"]}`。',
              f'- 既有 N 补证内容哈希：`{report["manifest"]["minority_supplement"]["logical_content_hash"]}`。',
              f'- 本 E 补证内容哈希：`{report["logical_content_hash"]}`；完整输入/工具/规则身份见同名 JSON。',
              '- 仅用于遵守来源条款的本地复核；不对外发布原始数据或报告，不用于商业用途。', ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(DEFAULT_OUTPUT))
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check and args.render_dir is not None:
        parser.error("--check does not write renders")
    report = build_supplement(render_dir=args.render_dir)
    artifacts = {"diagnostic-only.json": base.canonical_bytes(report) + b"\n",
                 "diagnostic-only.md": render_markdown(report).encode("utf-8")}
    if args.check:
        for name, raw in artifacts.items():
            if (args.output_dir / name).read_bytes() != raw:
                raise ValueError(f"frozen E supplement differs: {name}")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for name, raw in artifacts.items():
            (args.output_dir / name).write_bytes(raw)
    print(json.dumps({"diagnostic_only": True, "closed_source_field": "attributable_equity",
                      "E_observed_cny": report["gap_resolution"]["amount_cny_per_version"],
                      "source_alpha": report["source_alpha_arithmetic_not_pit"][0]["alpha_observed"],
                      "historical_pit_status": "UNKNOWN", "logical_content_hash": report["logical_content_hash"]}))


if __name__ == "__main__":
    main()
