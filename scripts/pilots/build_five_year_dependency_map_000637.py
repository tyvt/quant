"""Index frozen per-version source dependencies, without selecting PIT versions.

Offline only: reproduce six frozen supplements before projecting eight annual
versions. Arithmetic is per PDF, never an annual_fcf_newest_to_oldest input.
Lease components cannot be shared across versions. No new timing assumption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import verify_financial_2021_000637 as y2021
from scripts.pilots import verify_financial_2022_000637 as y2022
from scripts.pilots import verify_financial_2023_000637 as y2023
from scripts.pilots import verify_financial_2024_000637 as y2024
from scripts.pilots import verify_ocf_capex_000637 as cash2025
from scripts.pilots import verify_lease_cash_000637 as lease2025
from turtle_quant.core.types import calculation_context, to_decimal

INPUTS = "docs/data-pilots/000637-five-year-dependency-map-inputs.json"
TOOL = "scripts/pilots/build_five_year_dependency_map_000637.py"
OUTPUT_STEM = "docs/data-pilots/000637-five-year-dependency-map"
FIELDS = ("E", "N", "OCF", "Capex")
BUILDERS = {"2021": y2021.build_review, "2022": y2022.build_review,
            "2023": y2023.build_review, "2024": y2024.build_review,
            "2025_cashflow": cash2025.build_supplement, "2025_lease": lease2025.build_review}
EXPECTED_VERSIONS = {"original_2021_annual_report": "1212743936", "original_2022_annual_report": "1216687772",
                     "original_2023_annual_report": "1221364107", "amended_2023_annual_report": "1225460225",
                     "original_2024_annual_report": "1223369814", "amended_2024_annual_report": "1225460241",
                     "original_2025_annual_report": "1225248741", "amended_2025_annual_report": "1225460240"}
UNKNOWN = ("Lease_cash_not_already_deducted", "available_at", "latest_visible_version", "complete_revision_chain",
           "full_amended_audit_status", "cross_year_comparability", "source_use_scope")


def load_sources(root=ROOT, reproduce=False):
    root = Path(root).resolve()
    scope_raw = (root / INPUTS).read_bytes()
    scope = base._json(scope_raw)
    if (scope["schema_version"] != "five_year_dependency_map_scope_v1" or scope["security_id"] != "sz.000637"
            or scope["as_of"] != "2026-09-30" or scope["review_date"] != "2026-10-02"
            or scope["years"] != [2021, 2022, 2023, 2024, 2025] or scope["diagnostic_only"] is not True
            or scope["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED" or set(scope["sources"]) != set(BUILDERS)):
        raise ValueError("fixed index scope changed")
    probe = scope["next_probe"]
    expected_probe = {"status": "SELECTED_NOT_EXECUTED", "security_id": "sz.000637", "version": "original_2021_annual_report",
                 "announcement_id": "1212743936", "dependency": "verified_available_at", "maximum_official_read_requests": 4,
                 "assumption_authorized": False, "stopping_condition": "VERIFIABLE_AVAILABILITY_EVIDENCE_OR_BOUNDED_INSUFFICIENT_EVIDENCE"}
    if base.canonical_bytes(probe) != base.canonical_bytes(expected_probe):
        raise ValueError("next probe or timing assumption changed")
    reports = {}
    for name in sorted(BUILDERS):
        reference = scope["sources"][name]
        raw = base.verified_bytes(root, reference["path"], reference["sha256"])
        report = base._json(raw)
        if (report["logical_content_hash"] != reference["logical_content_hash"]
                or report["logical_content_hash"] != base.logical_content_hash(report)
                or report["security_id"] != "sz.000637" or report["as_of"] != scope["as_of"]
                or report["diagnostic_available_at"] is not None or report["timing_policy"] != scope["timing_policy"]
                or report["diagnostic_only"] is not True or report["official_selection"] is not False
                or report["production_reader_ready"] is not False):
            raise ValueError("frozen source identity, timing or authority changed")
        if reproduce and base.canonical_bytes(report) != base.canonical_bytes(BUILDERS[name](root)):
            raise ValueError(f"frozen source cannot be reproduced: {name}")
        reports[name] = report
    base.verified_bytes(root, "RULE_SPEC.md", y2024.RULE_HASH)
    return scope_raw, scope, reports


def ordinary_arithmetic(fields):
    with calculation_context():
        e, n, ocf, capex = (to_decimal(fields[key]["observed_value"]) for key in FIELDS)
        if e <= 0 or capex < 0:
            raise ValueError("invalid equity or Capex source value")
        alpha = e / (e + max(n, to_decimal("0")))
        difference = ocf - capex
        return {"alpha_observed": format(alpha, "f"), "ocf_minus_capex_cny": format(difference, "f"),
                "FCF_ordinary_source_arithmetic_cny": format(difference * alpha, "f"), "status": "SOURCE_ARITHMETIC_ONLY_NOT_PIT"}


def normalized_row(year, report, bundle, lease_report=None):
    version = bundle["version"]
    matches = [doc for doc in report["source_documents"] if doc["role"] == version]
    if len(matches) != 1 or EXPECTED_VERSIONS.get(version) != matches[0]["announcement_id"]:
        raise ValueError("duplicate/missing annual source or wrong announcement identity")
    doc = dict(matches[0])
    if doc.get("exact_available_at_utc") is not None:
        raise ValueError("document availability cannot be promoted in this index")
    if year == 2025:
        observations = {name: bundle[{"E": "existing_E", "N": "existing_N"}.get(name, name)] for name in FIELDS}
        components = [b for b in lease_report["version_bundles"] if b["version"] == version]
        lease_docs = [d for d in lease_report["source_documents"] if d["role"] == version]
        if (len(components) != 1 or len(lease_docs) != 1 or components[0]["document_sha256"] != doc["sha256"]
                or lease_docs[0]["sha256"] != doc["sha256"] or lease_docs[0]["announcement_id"] != doc["announcement_id"]):
            raise ValueError("cashflow and lease versions/PDFs do not match")
        component = components[0]["financing_cash_component"]
        lease_value = component["cash_payment"]["current_amount"]
        lease_state = "EXPLICIT_COMPONENT_NOT_COMPLETE_LEASE_CASH"
        doc["evidence_pages"] = sorted(set(doc["evidence_pages"] + lease_docs[0]["evidence_pages"]))
        original_arithmetic = bundle["source_arithmetic_not_pit"]
        prior = {name: observations[name].get("opening_comparative_not_target_value", observations[name].get("prior_comparative_not_target_value")) for name in FIELDS}
    else:
        observations = bundle["observations"]
        component = bundle["lease_financing_component"]
        lease_value = component.get("observed_cny", component.get("current_cny"))
        lease_state = component.get("observation_state", "EXPLICIT_COMPONENT_NOT_COMPLETE_LEASE_CASH")
        original_arithmetic = bundle["ordinary_source_arithmetic"]
        prior = {name: bundle["tables"]["rows"][name]["prior_comparative_cny"] for name in FIELDS}
    fields = {}
    field_names = {"E": "attributable_equity", "N": "minority_interest", "OCF": "operating_cash_flow", "Capex": "capex_cash_paid"}
    for name in FIELDS:
        item = observations[name]
        if (item["security_id"] != "sz.000637" or item["period_end"] != f"{year}-12-31" or item["version"] != version
                or item["document_sha256"] != doc["sha256"] or item["statement_scope"] != "CONSOLIDATED"
                or item["unit"] != "CNY" or item["field"] != field_names[name] or item["historical_pit_status"] != "UNKNOWN"
                or item.get("diagnostic_available_at") is not None or item.get("pit_value") is not None):
            raise ValueError("cross-version/year/security/unit/PDF field projection")
        fields[name] = {"observed_value": item["observed_value"], "source_state": "SOURCE_VALUE_BOUND_NOT_PIT",
                        "evidence_refs": item["evidence_refs"]}
    arithmetic = ordinary_arithmetic(fields)
    if any(original_arithmetic[key] != value for key, value in arithmetic.items()):
        raise ValueError("projected arithmetic differs from frozen same-PDF arithmetic")
    if component["full_lease_cash_coverage"] != "UNKNOWN":
        raise ValueError("incomplete lease cash promoted")
    lease_refs = component["evidence_refs"]
    for ref in [ref for field in fields.values() for ref in field["evidence_refs"]] + lease_refs:
        match = re.fullmatch(rf"pdf:sha256:{doc['sha256']}:physical-page:([0-9]+)", ref)
        if not match or int(match[1]) not in doc["evidence_pages"]:
            raise ValueError("field or lease evidence not bound to the same PDF/pages")
    return {"year": year, "version": version, "period_end": f"{year}-12-31", "statement_scope": "CONSOLIDATED", "unit": "CNY",
            "document": {key: doc[key] for key in ("role", "announcement_id", "url", "sha256", "path", "evidence_pages")},
            "fields": fields, "ordinary_source_arithmetic": arithmetic, "prior_comparative_not_source": prior,
            "lease_component": {"observed_cny": lease_value, "observation_state": lease_state, "evidence_refs": lease_refs},
            "unknown_dependencies": {key: None for key in UNKNOWN}, "pit_admitted": False, "selected_for_run": False,
            "source_report_hash": report["logical_content_hash"]}


def project(reports):
    rows = []
    for year in range(2021, 2026):
        report = reports[str(year)] if year < 2025 else reports["2025_cashflow"]
        for bundle in report["version_bundles"]:
            rows.append(normalized_row(year, report, bundle, reports["2025_lease"] if year == 2025 else None))
    rows.sort(key=lambda row: (row["year"], 0 if row["version"].startswith("original") else 1))
    if len(rows) != 8 or {r["version"] for r in rows} != set(EXPECTED_VERSIONS):
        raise ValueError("exactly five originals and three amendments required")
    comparisons = []
    with calculation_context():
        for earlier in rows:
            for later in rows:
                if later["year"] != earlier["year"] + 1:
                    continue
                differences = {name: format(to_decimal(later["prior_comparative_not_source"][name]) -
                                            to_decimal(earlier["fields"][name]["observed_value"]), "f") for name in FIELDS}
                comparisons.append({"earlier_version": earlier["version"], "later_version": later["version"],
                                    "later_comparative_minus_earlier_source_cny": differences,
                                    "all_four_source_values_equal": all(to_decimal(v) == 0 for v in differences.values()),
                                    "full_comparability": "UNKNOWN", "used_to_replace_earlier_source": False})
        revision_differences = []
        for year in (2023, 2024, 2025):
            old, new = [r for r in rows if r["year"] == year]
            revision_differences.append({"year": year, "original_version": old["version"], "amended_version": new["version"],
                                         "amended_minus_original_cny": {name: format(to_decimal(new["fields"][name]["observed_value"]) -
                                                                                     to_decimal(old["fields"][name]["observed_value"]), "f") for name in FIELDS},
                                         "latest_visible_version": None})
    return {"version_rows": rows, "adjacent_year_comparisons": comparisons, "revision_differences": revision_differences,
            "policy_bridge_reference": {"source_report_hash": reports["2022"]["logical_content_hash"],
                                        "details": reports["2022"]["policy_bridge"], "not_used_to_backfill": True}}


def code_hashes(root, reports):
    paths = {TOOL, "scripts/pilots/build_limited_diagnostics.py", "turtle_quant/core/types.py"}
    for report in reports.values():
        old_hashes = {**report["manifest"].get("code_hashes", {}),
                      **{item["path"]: item["sha256"] for item in report["manifest"].get("code_sources", [])}}
        for path, sha in old_hashes.items():
            base.verified_bytes(root, path, sha)
        paths.update(old_hashes)
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in sorted(paths)}


def build_map(root=ROOT):
    root = Path(root).resolve()
    scope_raw, scope, reports = load_sources(root, reproduce=True)
    projection = project(reports)
    result = {"schema_version": "five_year_dependency_map_v1", "security_id": scope["security_id"], "as_of": scope["as_of"],
              "review_date": scope["review_date"], "years": scope["years"], "diagnostic_only": True,
              "official_selection": False, "production_reader_ready": False, "timing_policy": scope["timing_policy"],
              "diagnostic_available_at": None, "historical_pit_observations_admitted": 0, "chosen_version_by_year": None,
              "complete_standard_fcf_window": False, "next_probe": scope["next_probe"], **projection,
              "manifest": {"rule_version": "v1.3.2", "rule_sha256": y2024.RULE_HASH,
                           "scope": {"path": INPUTS, "sha256": hashlib.sha256(scope_raw).hexdigest()}, "source_reports": scope["sources"],
                           "code_hashes": code_hashes(root, reports)}}
    result["logical_content_hash"] = base.logical_content_hash(result)
    validate_map(result, root)
    return result


def validate_map(result, root=ROOT):
    root = Path(root).resolve()
    scope_raw, scope, reports = load_sources(root)
    required_keys = {"schema_version", "security_id", "as_of", "review_date", "years", "diagnostic_only", "official_selection",
                     "production_reader_ready", "timing_policy", "diagnostic_available_at", "historical_pit_observations_admitted",
                     "chosen_version_by_year", "complete_standard_fcf_window", "next_probe", "version_rows", "adjacent_year_comparisons",
                     "revision_differences", "policy_bridge_reference", "manifest", "logical_content_hash"}
    if (result["schema_version"] != "five_year_dependency_map_v1" or result["security_id"] != scope["security_id"]
            or set(result) != required_keys
            or result["as_of"] != scope["as_of"] or result["review_date"] != scope["review_date"] or result["years"] != scope["years"]
            or result["diagnostic_only"] is not True or result["official_selection"] is not False or result["production_reader_ready"] is not False
            or result["diagnostic_available_at"] is not None or result["timing_policy"] != scope["timing_policy"]
            or type(result["historical_pit_observations_admitted"]) is not int or result["historical_pit_observations_admitted"] != 0
            or result["complete_standard_fcf_window"] is not False or result["chosen_version_by_year"] is not None
            or base.canonical_bytes(result["next_probe"]) != base.canonical_bytes(scope["next_probe"])
            or result["logical_content_hash"] != base.logical_content_hash(result)):
        raise ValueError("index identity, timing assumption, version selection or authority changed")
    for key, expected in project(reports).items():
        if base.canonical_bytes(result[key]) != base.canonical_bytes(expected):
            raise ValueError(f"frozen field/version dependency projection changed: {key}")
    expected_manifest = {"rule_version": "v1.3.2", "rule_sha256": y2024.RULE_HASH,
                         "scope": {"path": INPUTS, "sha256": hashlib.sha256(scope_raw).hexdigest()},
                         "source_reports": scope["sources"], "code_hashes": code_hashes(root, reports)}
    if base.canonical_bytes(result["manifest"]) != base.canonical_bytes(expected_manifest):
        raise ValueError("index source or rule identities changed")
    forbidden = {"rank", "ranking", "top_n", "orders", "holdings", "nav", "target_weights", "F1", "F2", "F3", "F4", "F5", "annual_fcf_newest_to_oldest"}

    def walk(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("index cannot produce strategy or standard five-year outputs")
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(result)


def render_markdown(result, root=ROOT):
    validate_map(result, root)
    lines = ["# 茂化实华五年逐字段、逐版本依赖清单", "", "单证券 sz.000637；as_of=2026-09-30；整理日期 2026-10-02。仅索引已冻结证据，不改写旧报告。", "",
             "## 本清单不宣称", "", "- 不是官方 Top-N、真实选股、完整真实 PIT 规则运行、回测绩效或投资建议。",
             "- 不选最新可见版，不生成 F1—F5、排名、权重、订单、持仓或净值，不改变任何域的 ready 状态。",
             "- 五个年度原版已绑定，不等于完整五年标准 FCF。UNKNOWN_UNLESS_VERIFIED；available_at=null，历史 PIT 准入 0。",
             "", "## 五年依赖概览", "", "| 依赖 | 2021 | 2022 | 2023 | 2024 | 2025 |", "|---|---|---|---|---|---|"]
    for field in (*FIELDS, "alpha / FCF_ordinary 原文算术"):
        lines.append(f"| {field} | 原版已知 | 原版已知 | 原/更版各自已知 | 原/更版各自已知 | 原/更版各自已知 |")
    lines += ["| 租赁现金分项 | 部分已知 | 部分已知 | 原版未识别；更版部分已知 | 两版部分已知 | 两版部分已知 |",
              "| 完整 Lease_cash | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |",
              "| available_at / 最新可见版本 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |",
              "| 完整版本链 / 来源适用范围 | 未闭环 | 未闭环 | 未闭环 | 未闭环 | 未闭环 |",
              "| 标准 FCF / PIT / 跨年可比性 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |", "",
              "## 同版数值与租赁分项（元）", "", "以下八行是八个版本的观察，不是选定的五年策略输入；字段物理页引用见同名 JSON。", "",
              "| 年度 | 版本 | 公告 ID | E | N | OCF | Capex | 已识别租赁部分 |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for row in result["version_rows"]:
        values = [row["fields"][name]["observed_value"] for name in FIELDS]
        lease_value = row["lease_component"]["observed_cny"]
        lines.append(f'| {row["year"]} | {"原版" if row["version"].startswith("original") else "更正版"} | {row["document"]["announcement_id"]} | '
                     + " | ".join(values) + f' | {"UNKNOWN（未识别）" if lease_value is None else lease_value} |')
    lines += ["", "2023 原版租赁未识别不填零、不由更正版或主表总额回填；2021 的 2020 空白比较栏与 2025 的源版面截断也不改写。全部已识别金额仅是现金部分，未证明完整范围与去重。",
              "", "## 原文普通口径算术（不是标准 FCF）", "", "| 年度 | 版本 | alpha_observed | (OCF−Capex)×alpha（元） |", "|---|---|---:|---:|"]
    for row in result["version_rows"]:
        arithmetic = row["ordinary_source_arithmetic"]
        lines.append(f'| {row["year"]} | {"原版" if row["version"].startswith("original") else "更正版"} | {arithmetic["alpha_observed"]} | {arithmetic["FCF_ordinary_source_arithmetic_cny"]} |')
    lines += ["", "## 修订与跨年兼容性", "", "2023—2025 更正版 OCF 相对原版的差额："]
    for change in result["revision_differences"]:
        lines.append(f'- {change["year"]}：{change["amended_minus_original_cny"]["OCF"]} 元；E/N/Capex 相同不证明整份输入相同。')
    lines += ["", "下表差额为下一年比较栏减上年独立原文，遍历既有版本组合，不为运行选版；金额相等也不证明合并范围、会计政策、租赁与全部科目可比。所有组合的完整可比性仍 UNKNOWN。", "",
              "| 上年版本 → 下年版本 | E 差额 | N 差额 | OCF 差额 | Capex 差额 |", "|---|---:|---:|---:|---:|"]
    def short(version):
        return version.split("_")[1] + ("原" if version.startswith("original") else "更")
    for comparison in result["adjacent_year_comparisons"]:
        lines.append(f'| {short(comparison["earlier_version"])} → {short(comparison["later_version"])} | '
                     + " | ".join(comparison["later_comparative_minus_earlier_source_cny"][name] for name in FIELDS) + " |")
    lines += ["", "2022→2023 的 E/N 差异已有前序解释第 16 号原文桥接：E +1966829.87 元、N −104.66 元。只索引旧桥接，不回填 2022、不静默统一历史版本或宣称五年兼容。",
              "", "## 证据与冻结父包", ""]
    for row in result["version_rows"]:
        doc = row["document"]
        lines += [f'- `{row["version"]}`：公告 `{doc["announcement_id"]}`，[官方 PDF]({doc["url"]})；SHA-256 `{doc["sha256"]}`。']
    lines += [""]
    for name, ref in sorted(result["manifest"]["source_reports"].items()):
        relative = ref["path"].removeprefix("docs/data-pilots/")
        lines.append(f'- [{name} 冻结证据包]({relative})：文件 SHA-256 `{ref["sha256"]}`；logical `{ref["logical_content_hash"]}`。')
    lines += ["", "## 下一项 UNKNOWN：2021 原版 available_at", "",
              "目标限定为公告 1212743936、PDF e7ebbcae… 的最早公众可用证据；状态 SELECTED_NOT_EXECUTED。最多四次官方公开读取；身份/版本匹配且证据明确时记录能证明的范围，否则以限定不足结论停止，不继续无边界搜索。",
              "目录 midnight、PDF 封面日、抓取日或延后一个交易日均不自动成为已核实 PIT。若只有日级日期而无可用时刻证明，available_at 继续 UNKNOWN；日级假设需另冻新诊断范围并经确认，本清单不批准或执行该假设。",
              "不发送询证函、不联络发行人、不切换付费来源、不发布快照或解锁运行。暂不围绕 Lease_cash 做无边界搜索。",
              "", "## 可复现性", "", f'- logical_content_hash：`{result["logical_content_hash"]}`。',
              "- 离线重建六个冻结父包再作投影；同版 PDF/物理页/期间/币种/版本严格匹配，保留每个版本的 UNKNOWN。canonical UTF-8 JSON、排序键，无运行时钟；唯一排除自身顶层哈希字段。",
              "- `python -X utf8 scripts/pilots/build_five_year_dependency_map_000637.py --check` 核验本清单；旧报告/规则/生产快照不改写。",
              "- 本地 Git 不备份被忽略的 storage 原文；复现需要原有固定证据及相容环境，遵守来源条款，不作许可验收。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-stem", type=Path, default=Path(OUTPUT_STEM))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build_map()
    artifacts = {args.output_stem.with_suffix(".json"): base.canonical_bytes(result) + b"\n",
                 args.output_stem.with_suffix(".md"): render_markdown(result).encode("utf-8")}
    if args.check:
        for path, raw in artifacts.items():
            if path.read_bytes() != raw: raise ValueError(f"frozen dependency map differs: {path}")
    else:
        if any(path.exists() for path in artifacts): raise FileExistsError("dependency map exists; refusing to overwrite")
        args.output_stem.parent.mkdir(parents=True, exist_ok=True)
        for path, raw in artifacts.items():
            with path.open("xb") as target: target.write(raw)
    print(json.dumps({"logical_content_hash": result["logical_content_hash"], "versions": len(result["version_rows"]),
                      "historical_pit_admitted": 0}))


if __name__ == "__main__":
    main()
