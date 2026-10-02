"""Verify two fixed consolidated cashflow tables and same-PDF source arithmetic.

The parent already records OCF/Capex. This supplement independently binds their
cells to frozen same-version E/N, not to historical PIT, Readers or full FCF.
Geometry tolerances apply only to these two explicit PDFs, not a generic adapter.
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
from scripts.pilots import verify_attributable_equity_000637 as equity
from scripts.pilots import verify_minority_equity_000637 as minority
from turtle_quant.core.types import calculation_context, to_decimal

INPUTS = "docs/data-pilots/2026-10-02-ocf-capex-000637-inputs.json"
TOOL = "scripts/pilots/verify_ocf_capex_000637.py"
DEFAULT_OUTPUT = "docs/data-pilots/ocf-capex-000637-2026-10-02"
OCF_LABEL = "经营活动产生的现金流量净额"
CAPEX_PARTS = ("购建固定资产、无形资产和其他长", "期资产支付的现金")
FIELDS = ("operating_cash_flow", "capex_cash_paid")
PARENT_ROLES = {"original_2025_annual_report": "original_annual",
                "amended_2025_annual_report": "amended_annual"}
PIT_FIELDS = ("OCF_pit", "Capex_pit", "E_pit", "N_pit", "alpha_pit", "FCF_ordinary_pit",
              "Lease_cash_not_already_deducted", "FCF_conservative", "FCF")


def _centre_y(word: tuple) -> float:
    return (word[1] + word[3]) / 2


def _cells(words: list, row_y: float, current: tuple, prior: tuple) -> dict:
    split = (current[0] + current[2] + prior[0] + prior[2]) / 4
    cells = [word for word in words if abs(_centre_y(word) - row_y) <= 1
             and word[0] >= current[0] - 45]
    columns = [[word for word in cells if (word[0] + word[2]) / 2 < split],
               [word for word in cells if (word[0] + word[2]) / 2 >= split]]
    if any(len(column) > 1 for column in columns):
        raise ValueError("ambiguous cashflow currency cell")
    amounts = [minority.parse_money_cell(column[0][4] if column else None) for column in columns]
    return {"current_amount_cny": amounts[0], "prior_comparative_amount_cny": amounts[1],
            "current_state": "UNKNOWN" if amounts[0] is None else "EXPLICIT_NUMERIC",
            "prior_comparative_state": "UNKNOWN" if amounts[1] is None else "EXPLICIT_NUMERIC"}


def extract_cashflow_bridge(text: str, words: list, continuation: str, continuation_words: list) -> dict:
    compact = "".join(text.split())
    continued = "".join(continuation.split())
    if ("茂名石化实华股份有限公司2025年年度报告全文" not in compact
            or "单位：元" not in compact or "单位：万元" in compact
            or "母公司现金流量表" in compact
            or "茂名石化实华股份有限公司2025年年度报告全文" not in continued):
        raise ValueError("fixed issuer, scope, annual period or unit header mismatch")
    table = minority._one(words, "5、合并现金流量表")
    current, prior = (minority._one(words, year) for year in ("2025", "2024"))
    annual = [word for word in words if word[4] == "年度"]
    if (current[0] >= prior[0] or abs(_centre_y(current) - _centre_y(prior)) > 1
            or len(annual) != 2
            or any(len([word for word in annual if abs(_centre_y(word) - _centre_y(year)) <= 1
                        and 0 <= word[0] - year[2] <= 5]) != 1 for year in (current, prior))):
        raise ValueError("annual column order or year/年度 alignment mismatch")
    operating = minority._one(words, "一、经营活动产生的现金流量：")
    investing = minority._one(words, "二、投资活动产生的现金流量：")
    investment_end = minority._one(words, "投资活动产生的现金流量净额")
    ocf = minority._one(words, OCF_LABEL)
    inflow = minority._one(words, "经营活动现金流入小计")
    outflow = minority._one(words, "经营活动现金流出小计")
    first, second = (minority._one(words, label) for label in CAPEX_PARTS)
    if not (table[3] < current[1] < operating[1] < inflow[1] < outflow[1] < ocf[1]
            < investing[1] < first[1] < second[1] < investment_end[1]):
        raise ValueError("cashflow row outside its consolidated section")
    if (abs(_centre_y(second) - _centre_y(first) - 12) > 1
            or abs(first[0] - second[0]) > 10 or max(first[2], second[2]) >= current[0] - 45):
        raise ValueError("split capex label is not an adjacent two-line payment row")
    parent = minority._one(continuation_words, "6、母公司现金流量表")
    # The same page also repeats financing inside the later parent-company table.
    consolidated_continuation = [word for word in continuation_words if word[3] < parent[1]]
    financing = minority._one(consolidated_continuation, "三、筹资活动产生的现金流量：")
    if financing[3] >= parent[1]:
        raise ValueError("cashflow continuation ends before consolidated financing section")
    parsed = {"operating_cash_flow": _cells(words, _centre_y(ocf), current, prior),
              "capex_cash_paid": _cells(words, (first[1] + second[3]) / 2, current, prior)}
    incoming = _cells(words, _centre_y(inflow), current, prior)
    outgoing = _cells(words, _centre_y(outflow), current, prior)
    checks = {}
    with calculation_context():
        for column in ("current_amount_cny", "prior_comparative_amount_cny"):
            values = [row[column] for row in (incoming, outgoing, parsed["operating_cash_flow"])]
            difference = (Decimal(values[0]) - Decimal(values[1]) - Decimal(values[2])
                          if all(value is not None for value in values) else None)
            if difference is not None and difference != 0:
                raise ValueError("same-column OCF differs from inflow minus outflow")
            capex = parsed["capex_cash_paid"][column]
            if capex is not None and Decimal(capex) < 0:
                raise ValueError("capex payment row must be nonnegative")
            checks[column] = {"operating_inflow_cny": incoming[column],
                              "operating_outflow_cny": outgoing[column],
                              "difference_cny": format(difference, "f") if difference is not None else None,
                              "status": "UNKNOWN" if difference is None else "RECONCILED"}
    return {**parsed, "ocf_subtotal_corroboration": checks,
            "column_basis": "2025_2024_annual_header_geometry_not_linear_word_order",
            "capex_label": "".join(CAPEX_PARTS), "capex_is_gross_payment_not_net_or_total": True,
            "parent_cashflow_table_starts_on_next_page": True}


def calculate_source_ordinary(ocf: dict, capex: dict, e: dict, n: dict) -> dict:
    alpha = equity.calculate_source_alpha(e, n)
    if any(item.get(key) is None or item[key] != e[key]
           for item in (ocf, capex) for key in equity.JOIN_KEYS):
        raise ValueError("cashflow/E/N security, period, scope, unit, version or PDF identity mismatch")
    if (ocf.get("field") != FIELDS[0] or capex.get("field") != FIELDS[1]
            or ocf.get("period_start") != "2025-01-01" or capex.get("period_start") != "2025-01-01"
            or e["period_end"] != "2025-12-31"):
        raise ValueError("cashflow fields or full-year period mismatch")
    result = {"version": e["version"], "alignment": alpha["alignment"],
              "OCF_observed_cny": ocf["observed_value"], "Capex_observed_cny": capex["observed_value"],
              "alpha_observed": alpha["alpha_observed"], "ocf_minus_capex_cny": None,
              "formula": "(OCF - Capex) * alpha", "FCF_ordinary_source_arithmetic_cny": None,
              "status": "UNKNOWN", "FCF_ordinary_pit": None, "FCF_conservative": None,
              "Lease_cash_not_already_deducted": None,
              "historical_pit_status": "UNKNOWN", "diagnostic_available_at": None,
              "evidence_refs": sorted(set(ref for item in (ocf, capex, e, n) for ref in item["evidence_refs"]))}
    # Validate known cashflow values even if some other dependency is missing.
    cash = [None if item["observed_value"] is None else to_decimal(item["observed_value"])
            for item in (ocf, capex)]
    if cash[1] is not None and cash[1] < 0:
        raise ValueError("capex payment must be nonnegative")
    if any(value is None for value in cash) or alpha["alpha_observed"] is None:
        result["unknown_reason"] = "missing ordinary source dependency is not zero"
        return result
    with calculation_context():
        subtotal = cash[0] - cash[1]
        result.update(ocf_minus_capex_cny=format(subtotal, "f"),
                      FCF_ordinary_source_arithmetic_cny=format(subtotal * Decimal(alpha["alpha_observed"]), "f"),
                      status="SOURCE_ARITHMETIC_ONLY_NOT_PIT")
    return result


def build_supplement(root: Path = ROOT, render_dir: Path | None = None) -> dict:
    import fitz

    root = root.resolve()
    raw_scope = (root / INPUTS).read_bytes()
    scope = base._json(raw_scope)
    required = {"schema_version": "ocf_capex_source_supplement_scope_v1", "security_id": "sz.000637",
                "issuer": "茂名石化实华股份有限公司", "as_of": "2026-09-30",
                "period_start": "2025-01-01", "period_end": "2025-12-31",
                "statement_scope": "CONSOLIDATED", "unit": "CNY", "target_fields": list(FIELDS),
                "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "review_date": "2026-10-02"}
    if (any(scope.get(key) != value for key, value in required.items())
            or scope["diagnostic_only"] is not True or scope["official_selection"] is not False
            or date.fromisoformat(scope["review_date"]) < date.fromisoformat(scope["as_of"])):
        raise ValueError("fixed OCF/Capex diagnostic scope mismatch")
    parent_ref, e_ref = scope["parent_report"], scope["equity_supplement"]
    parent = base._json(base.verified_bytes(root, parent_ref["path"], parent_ref["sha256"]))
    base.validate_report(parent)
    e_raw = base.verified_bytes(root, e_ref["path"], e_ref["sha256"])
    e_report = base._json(e_raw)
    equity.validate_supplement(e_report)
    if (parent["logical_content_hash"] != parent_ref["logical_content_hash"]
            or e_report["logical_content_hash"] != e_ref["logical_content_hash"]
            or e_report["manifest"]["parent_report"] != parent_ref
            or parent["security_id"] != scope["security_id"] or parent["as_of"] != scope["as_of"]):
        raise ValueError("frozen parent or E supplement identity mismatch")
    if e_raw != base.canonical_bytes(equity.build_supplement(root)) + b"\n":
        raise ValueError("frozen E/N supplement does not reproduce from source PDFs")
    if tuple((doc["role"], doc["announcement_id"]) for doc in scope["documents"]) != equity.VERSIONS:
        raise ValueError("fixed annual versions changed")
    bundles, documents, renders = [], [], []
    for target, source, e, n in zip(scope["documents"], e_report["source_documents"],
                                   e_report["observations"], e_report["existing_N_dependencies"]):
        if (target["role"] != source["role"] or target["announcement_id"] != source["announcement_id"]
                or target["pdf_sha256"] != source["sha256"]
                or (target["field_page"], target["continuation_page"]) != (101, 102)):
            raise ValueError("fixed PDF identity or physical cashflow pages changed")
        source = {**source, "evidence_pages": [93, 94, 95, 101, 102], "cashflow_pages": [101, 102],
                  "equity_dependency_pages": [93, 94, 95]}
        raw = base.verified_bytes(root, source["path"], source["sha256"])
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            parsed = extract_cashflow_bridge(pdf[100].get_text(), pdf[100].get_text("words"),
                                            pdf[101].get_text(), pdf[101].get_text("words"))
        observations = []
        for field in FIELDS:
            row = parsed[field]
            if (row["current_amount_cny"] != target[f"expected_{field}_cny"]
                    or row["prior_comparative_amount_cny"] != target[f"expected_comparative_{field}_cny"]):
                raise ValueError("frozen source amount disagrees with PDF column cells")
            parent_field = "operating_net" if field == FIELDS[0] else field
            prior = [item for item in parent["source_observations"] if item["field"] == parent_field
                     and item["source_version"] == PARENT_ROLES[source["role"]]]
            if (len(prior) != 1 or prior[0]["observed_value"] != row["current_amount_cny"]
                    or prior[0]["economic_date"] != scope["period_end"]
                    or prior[0]["evidence_refs"] != [base._ref(source, 101)]):
                raise ValueError("unchanged parent source field or PDF/page binding mismatch")
            observations.append({**{key: e[key] for key in equity.JOIN_KEYS}, "field": field,
                                 "period_start": scope["period_start"],
                                 "source_label": OCF_LABEL if field == FIELDS[0] else "".join(CAPEX_PARTS),
                                 "observed_value": row["current_amount_cny"],
                                 "prior_comparative_not_target_value": row["prior_comparative_amount_cny"],
                                 "source_observation_status": "VERIFIED_IN_THIS_FIXED_DOCUMENT",
                                 "evidence_refs": [base._ref(source, 101)],
                                 "historical_pit_status": "UNKNOWN", "pit_value": None})
        bundles.append({"version": source["role"], "OCF": observations[0], "Capex": observations[1],
                        "existing_E": e, "existing_N": n, "extraction_checks": parsed,
                        "source_arithmetic_not_pit": calculate_source_ordinary(*observations, e, n)})
        documents.append(source)
        renders.append((source, raw))
    if render_dir is not None:
        render_dir.mkdir(parents=True, exist_ok=False)
        for doc, raw in renders:
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                for page in (101, 102):
                    pdf[page - 1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(
                        str(render_dir / f'{doc["role"]}-physical-page-{page}.png'))
    report = {
        "schema_version": "ocf_capex_source_supplement_v1",
        "title": "茂化实华 2025 OCF/Capex：同版原文核验与普通口径算术（diagnostic_only=true）",
        **{key: scope[key] for key in ("security_id", "as_of", "period_start", "period_end", "review_date")},
        "diagnostic_only": True, "official_selection": False, "real_pit_strategy_run": False,
        "production_reader_ready": False, "parent_and_equity_supplements_unchanged": True,
        "not_claimed": list(base.DISCLAIMERS), "timing_policy": "UNKNOWN_UNLESS_VERIFIED",
        "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
        "source_documents": documents, "version_bundles": bundles, **dict.fromkeys(PIT_FIELDS),
        "gap_resolution": {"source_before": "OCF_CAPEX_ALREADY_RECORDED_IN_PARENT",
                           "source_after": "INDEPENDENT_PDF_CELL_CHECK_AND_SAME_VERSION_E_N_BINDING",
                           "historical_pit_after": "UNKNOWN", "new_historical_pit_inputs": 0},
        "remaining_unknowns": ["available_at", "latest_visible_version", "OCF_pit", "Capex_pit",
                               "E_pit", "N_pit", "alpha_pit", "lease_cash_not_already_deducted",
                               "complete_revision_chain", "full_amended_audit_status", "five_year_FCF_window"],
        "rule_execution": "NOT_EXECUTED_SOURCE_ORDINARY_ARITHMETIC_ONLY",
        "visual_review": scope["visual_review"],
        "manifest": {"scope": {"path": INPUTS, "sha256": hashlib.sha256(raw_scope).hexdigest()},
                     "parent_report": parent_ref, "equity_supplement": e_ref,
                     "minority_supplement": e_report["manifest"]["minority_supplement"],
                     "rule_identity": parent["manifest"]["rule_identity"],
                     "rule_version": parent["manifest"]["rule_version"],
                     "catalogue_sources": e_report["manifest"]["catalogue_sources"],
                     "source_inputs": e_report["manifest"]["source_inputs"],
                     "code_sources": [{"path": TOOL, "sha256": hashlib.sha256((root / TOOL).read_bytes()).hexdigest()},
                                      *e_report["manifest"]["code_sources"]],
                     "dependencies": {"python": sys.version.split()[0], "pymupdf": fitz.VersionBind},
                     "arithmetic": "Decimal precision=28 ROUND_HALF_EVEN; source-only ordinary FCF, not F1..F5",
                     "hash_scope": "canonical_utf8_sorted_keys_except_top_level_logical_content_hash"}}
    report["logical_content_hash"] = base.logical_content_hash(report)
    validate_supplement(report)
    return report


def validate_supplement(report: dict) -> None:
    if (report["diagnostic_only"] is not True or report["official_selection"] is not False
            or report["real_pit_strategy_run"] is not False or report["production_reader_ready"] is not False
            or report["parent_and_equity_supplements_unchanged"] is not True
            or report["diagnostic_available_at"] is not None or report["pit_admitted_observation_count"] != 0
            or report["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED"
            or any(report[key] is not None for key in PIT_FIELDS)):
        raise ValueError("source supplement authority, lease or PIT boundary changed")
    if (report["security_id"] != "sz.000637" or report["as_of"] != "2026-09-30"
            or report["period_start"] != "2025-01-01" or report["period_end"] != "2025-12-31"
            or report["logical_content_hash"] != base.logical_content_hash(report)):
        raise ValueError("fixed supplement scope or hash mismatch")
    if (len(report["source_documents"]) != 2 or len(report["version_bundles"]) != 2
            or tuple((doc["role"], doc["announcement_id"]) for doc in report["source_documents"]) != equity.VERSIONS):
        raise ValueError("two fixed annual versions required")
    for doc, bundle in zip(report["source_documents"], report["version_bundles"]):
        if (bundle["version"] != doc["role"] or doc["evidence_pages"] != [93, 94, 95, 101, 102]
                or doc["cashflow_pages"] != [101, 102] or doc["equity_dependency_pages"] != [93, 94, 95]
                or doc["exact_available_at_utc"] is not None or doc["diagnostic_available_at"] is not None
                or doc["pit_admitted"] is not False or doc["historical_availability_status"] != "UNKNOWN"):
            raise ValueError("source document version, pages or availability changed")
        for name, pages in (("OCF", (101,)), ("Capex", (101,)), ("existing_E", (93, 94, 95)),
                            ("existing_N", (93, 94, 95))):
            item = bundle[name]
            if (item["version"] != doc["role"] or item["document_sha256"] != doc["sha256"]
                    or item["security_id"] != report["security_id"] or item["period_end"] != report["period_end"]
                    or item["evidence_refs"] != [base._ref(doc, page) for page in pages]
                    or item["pit_value"] is not None or item["historical_pit_status"] != "UNKNOWN"):
                raise ValueError("observation PDF/page binding or PIT status changed")
        for name, field in zip(("OCF", "Capex"), FIELDS):
            item, row = bundle[name], bundle["extraction_checks"][field]
            if (item["observed_value"] != row["current_amount_cny"]
                    or item["prior_comparative_not_target_value"] != row["prior_comparative_amount_cny"]):
                raise ValueError("observation differs from parsed annual column")
        with calculation_context():
            for column, check in bundle["extraction_checks"]["ocf_subtotal_corroboration"].items():
                values = [check["operating_inflow_cny"], check["operating_outflow_cny"],
                          bundle["extraction_checks"][FIELDS[0]][column]]
                difference = (to_decimal(values[0]) - to_decimal(values[1]) - to_decimal(values[2])
                              if all(value is not None for value in values) else None)
                if (check["status"] != ("UNKNOWN" if difference is None else "RECONCILED")
                        or check["difference_cny"] != (None if difference is None else format(difference, "f"))
                        or difference not in (None, Decimal("0"))):
                    raise ValueError("OCF corroboration drift")
        if bundle["source_arithmetic_not_pit"] != calculate_source_ordinary(
                bundle["OCF"], bundle["Capex"], bundle["existing_E"], bundle["existing_N"]):
            raise ValueError("ordinary source arithmetic or identity drift")
    forbidden = {"ranking", "rank", "top_n", "target_weights", "orders", "holdings", "nav", "tier", "F1", "F2", "F3", "F4", "F5"}

    def check_keys(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("forbidden official or backtest output")
            for child in value.values():
                check_keys(child)
        elif isinstance(value, list):
            for child in value:
                check_keys(child)

    check_keys(report)


def render_markdown(report: dict) -> str:
    validate_supplement(report)
    lines = [f'# {report["title"]}', "", "## 本报告不宣称", ""]
    lines.extend(f"- {item}" for item in report["not_claimed"])
    lines += ["", "## 限定补证结果", "",
              '- `sz.000637`；`as_of=2026-09-30`；2025 完整年度；合并口径、人民币元。',
              '- 父报告已有 OCF/Capex 原文观察；本次独立核验表格单元格并绑定同版 E/N，未新增已核实历史 PIT 输入。', "",
              "| 固定版本 | OCF（元） | Capex（元） | OCF−Capex（元） | 普通口径原文算术（元，非 PIT） |",
              "|---|---:|---:|---:|---:|"]
    for bundle in report["version_bundles"]:
        item = bundle["source_arithmetic_not_pit"]
        lines.append(f'| {bundle["version"]} | {item["OCF_observed_cny"]} | {item["Capex_observed_cny"]} | '
                     f'{item["ocf_minus_capex_cny"]} | {item["FCF_ordinary_source_arithmetic_cny"]} |')
    lines += ["", '- `FCF_ordinary_source_arithmetic = (OCF - Capex) * alpha_observed`；28 位 Decimal、ROUND_HALF_EVEN；负值不截断。',
              '- 两版 alpha 均为 `0.8421488241705548591131801230`，复用已冻结同版 E/N；不跨发行人、期间、口径、单位、版本或 PDF 拼接。',
              '- 物理第 101 页核验合并现金流量表、2025/2024 年度列、元单位、OCF 与两行 Capex 支付科目；第 102 页核验筹资续表及下方母公司表边界。',
              '- OCF 与同列经营流入小计−流出小计对平。Capex 取购建长期资产支付行，不取投资流出合计、不扣处置资产收款。',
              '- 2024 比较栏不是本次目标：原版 OCF `9077909.18`，更正版 `-185115131.48`；Capex 两版均 `79764639.75`。', "",
              "## 时点假设与保留缺口", "",
              '- `UNKNOWN_UNLESS_VERIFIED`；`diagnostic_available_at=null`；历史 PIT 准入观察数量为 0。目录日期、抓取日或保守延后均未被当作已核实可用时点。',
              '- `OCF_pit/Capex_pit/E_pit/N_pit/alpha_pit/FCF_ordinary_pit` 全部 UNKNOWN；不选择声称最新可见的版本，也不用 9 月原版重现覆盖 8 月更正。',
              '- 未重复扣减的现金租赁支出仍 UNKNOWN；没有填零，也没有用租赁负债余额代替。`FCF_conservative/FCF/F1..F5` 未生成。',
              '- 普通口径只是诊断算术，不能替代 GENERAL_FCF 标准项；完整修订链、更正后整份审计状态与五年窗口未闭环。',
              '- 不调用 premise/valuation/未就绪 Reader，不生成排名、权重、订单、持仓、净值；生产状态、父报告及 N/E 补证均不变。', "",
              "## 原文证据", ""]
    for doc in report["source_documents"]:
        lines += [f'### {doc["role"]}', "", f'- 公告 `{doc["announcement_id"]}`：[法定 PDF]({doc["url"]})。',
                  f'- 本地 bytes：`{doc["path"]}`；SHA-256：`{doc["sha256"]}`；物理页 101/102（E/N 依赖页 93/94/95）。',
                  f'- 目录时间 `{doc["catalogue_announcement_time_beijing"]}`，不证明最早公众可见。', ""]
    lines += ["## 可复现身份", "",
              f'- 父诊断：`{report["manifest"]["parent_report"]["logical_content_hash"]}`。',
              f'- E/alpha 补证：`{report["manifest"]["equity_supplement"]["logical_content_hash"]}`。',
              f'- N 补证：`{report["manifest"]["minority_supplement"]["logical_content_hash"]}`。',
              f'- 本补证：`{report["logical_content_hash"]}`；输入、规则、代码、来源与 UNKNOWN 均纳入 canonical JSON 身份。',
              '- 离线重建；源 PDF 是证据，渲染只作目视检查。仅作遵守来源条款的本地复核，不对外发布或用于商业用途。', ""]
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
                raise ValueError(f"frozen OCF/Capex supplement differs: {name}")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for name, raw in artifacts.items():
            (args.output_dir / name).write_bytes(raw)
    print(json.dumps({"diagnostic_only": True, "historical_pit_status": "UNKNOWN",
                      "logical_content_hash": report["logical_content_hash"]}))


if __name__ == "__main__":
    main()
