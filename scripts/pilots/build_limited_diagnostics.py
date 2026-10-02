"""Offline, single-issuer diagnostics; never a production PIT adapter or strategy.

Observed source arithmetic and admissible historical rule inputs are separate.
This frozen batch chooses UNKNOWN for unverified earliest public availability.
Catalogue clocks, retrieval clocks, and next-day assumptions are not substituted.
Only ready pure policy/premise logic is exercised, with absent inputs as None.
No unready Reader, valuation with dummy inputs, selection, or backtest is called.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from turtle_quant.core.share_capital_policy import assess_share_capital_policy
from turtle_quant.core.types import calculation_context, to_decimal
from turtle_quant.premise.general_fcf import GeneralFCFInputs, evaluate_general_fcf


SCOPE_PATH = "docs/data-pilots/2026-10-02-limited-diagnostic-scope.json"
DEFAULT_OUTPUT = "docs/data-pilots/limited-diagnostics-2026-10-02"
SAMPLE_SECURITIES = {
    "shares-000858": "sz.000858",
    "buybacks-600519": "sh.600519",
    "cashflow-000637": "sz.000637",
    "financial-002570": "sz.002570",
}
TITLES = {
    "shares-000858": "五粮液 2025 股本",
    "buybacks-600519": "茅台首个减资回购计划",
    "cashflow-000637": "茂化实华 2025 现金流",
    "financial-002570": "贝因美 2022 核心财务科目",
}
CODE_PATHS = (
    "scripts/pilots/build_limited_diagnostics.py",
    "turtle_quant/core/share_capital_policy.py",
    "turtle_quant/core/result.py",
    "turtle_quant/core/types.py",
    "turtle_quant/premise/general_fcf.py",
)
DISCLAIMERS = (
    "这是单证券、单 as_of、限定输出范围的诊断，不是完整真实 PIT 策略运行。",
    "这不是官方 Top-N、可发布回测或真实选股结果，不生成排名、目标权重、订单、持仓或净值。",
    "UNKNOWN 未作为数值参与计算，未填零、未跨证券借用、未插值或前向填充。",
    "原文版本对照可以展示历史观察值；这些值不自动成为指定 as_of 的可用规则输入。",
    "本报告不构成投资建议，不对外发布原始数据或报告，不用于商业用途。",
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(raw: bytes):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError(f"nonfinite JSON number: {value}")))


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def logical_content_hash(report: dict) -> str:
    """Hash canonical content excluding only this hash's own top-level field."""
    return hashlib.sha256(canonical_bytes({
        key: value for key, value in report.items() if key != "logical_content_hash"
    })).hexdigest()


def _plain(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _relative(root: Path, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("evidence path escapes workspace")
    return resolved.relative_to(root.resolve()).as_posix()


def verified_bytes(root: Path, relative: str, expected: str) -> bytes:
    path = root / relative
    _relative(root, path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"source hash mismatch: {relative}")
    return raw


def _catalogues(root: Path, probe: dict):
    """Verify captured catalogue bytes; retain row clocks without certifying PIT."""
    if "catalogue" in probe:
        catalogue = probe["catalogue"]
        sources = [
            {"path": f'{catalogue["local_dir"]}/cninfo-catalogue-page-{n}.json',
             "sha256": digest}
            for n, digest in enumerate(catalogue["page_sha256_in_order"], 1)
        ]
    else:
        sources = [{"path": item["local_path"], "sha256": item["sha256"]}
                   for item in probe["catalogues"]]
    rows = {}
    for source in sources:
        response = _json(verified_bytes(root, source["path"], source["sha256"]))
        for row in response["announcements"]:
            if row["secCode"] != probe["security_id"].split(".")[1]:
                raise ValueError("catalogue security mismatch")
            key = row["adjunctUrl"]
            identity = {field: row[field] for field in (
                "secCode", "announcementId", "announcementTitle", "announcementTime")}
            if key in rows and rows[key]["identity"] != identity:
                raise ValueError("catalogue identity drift")
            rows[key] = {"identity": identity, "source": source}
    return rows, sources


def _document(root: Path, probe: dict, doc: dict, rows: dict, evidence_pages: list[int]):
    import fitz  # Optional offline pilot dependency, never used for OCR or interpretation.

    url = doc.get("source_url", doc.get("url"))
    match = re.fullmatch(r"https://static\.cninfo\.com\.cn/(finalpage/(\d{4}-\d{2}-\d{2})/(\d+)\.PDF)", url)
    if not match:
        raise ValueError("unexpected PDF source URL")
    row = rows[match[1]]
    if row["identity"]["announcementId"] != match[3]:
        raise ValueError("document ID mismatch")
    relative = doc.get("local_path", doc.get("path"))
    if relative is None:
        relative = f'{probe["catalogue"]["local_dir"]}/{doc["file"]}'
    relative = _relative(root, root / relative)
    raw = verified_bytes(root, relative, doc["sha256"])
    if not raw.startswith(b"%PDF-"):
        raise ValueError("source is not PDF bytes")
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        count = len(pdf)
    if any(type(page) is not int or not 1 <= page <= count for page in evidence_pages):
        raise ValueError("invalid physical evidence page")
    clock = row["identity"]["announcementTime"]
    if type(clock) is not int or clock < 0:
        raise ValueError("invalid catalogue clock")
    observed_clock = (datetime(1970, 1, 1, tzinfo=timezone.utc)
                      + timedelta(milliseconds=clock)).astimezone(timezone(timedelta(hours=8)))
    return {
        "role": doc.get("role", doc.get("id")), "path": relative, "url": url,
        "sha256": doc["sha256"], "announcement_id": match[3],
        "physical_page_count": count, "evidence_pages": sorted(set(evidence_pages)),
        "url_archive_date": match[2], "catalogue_title": row["identity"]["announcementTitle"],
        "catalogue_announcement_time_ms": clock,
        "catalogue_announcement_time_beijing": observed_clock.isoformat(),
        "catalogue_source": row["source"],
        "exact_available_at_utc": None, "diagnostic_available_at": None,
        "historical_availability_status": "UNKNOWN", "pit_admitted": False,
        "capture_request_started_at_utc": doc.get("request_started_at_utc"),
    }


def _ref(doc: dict, page: int) -> str:
    if page not in doc["evidence_pages"]:
        raise ValueError("field page not bound to document")
    return f'pdf:sha256:{doc["sha256"]}:physical-page:{page}'


def _observation(field, label, value, economic_date, version, refs):
    if not refs:
        raise ValueError("observation requires evidence refs")
    return {
        "field": field, "label": label, "observed_value": value,
        "economic_date": economic_date, "source_version": version,
        "source_state": "BLANK_NOT_ZERO" if value is None else "OBSERVED",
        "evidence_refs": refs, "pit_status": "UNKNOWN", "pit_value": None,
        "unknown_reason": "历史公众可用时点与所需覆盖未核实；未注入 PIT 规则输入。",
    }


def _gap(field, dependencies, reason):
    return {"field": field, "status": "UNKNOWN", "value": None,
            "missing_dependencies": dependencies, "reason": reason}


def _premise(as_of: str):
    """Do not create mandatory-dated annual observations from unverified clocks."""
    inputs = GeneralFCFInputs(
        as_of=date.fromisoformat(as_of), industry_profile=None,
        statements_comparable=None, latest_audit_unmodified=None,
        going_concern_uncertainty=None, latest_equity=None, annual_observations=(),
        cash=None, liquid_assets=None, interest_bearing_debt=None,
    )
    evaluation = evaluate_general_fcf(inputs)
    return {
        "execution_scope": "strict_unknown_propagation_only_not_complete_company_assessment",
        "admitted_inputs": _plain(asdict(inputs)),
        "admitted_real_numeric_observation_count": 0,
        "hard_gates": [_plain(asdict(item)) for item in evaluation.hard_gates],
        "quality_score": _plain(evaluation.quality.quality_score),
        "score_coverage": _plain(evaluation.quality.score_coverage),
        "valuation_execution": "NOT_EXECUTED_UNKNOWN_DEPENDENCIES",
        "reason": "历史可用时点未证实，且六个年末权益/五年 FCF/行业/审计等不完整；不借用虚拟日期或默认零调用估值。",
    }


def _shares(root, probe, rows, as_of):
    docs = [_document(root, probe, doc, rows, doc["evidence_pages"])
            for doc in probe["documents"]
            if doc["role"] in {"2024annual_opening_bridge", "2025h1_original", "2025annual"}]
    by_role = {doc["role"]: doc for doc in docs}
    annual = by_role["2025annual"]
    bridge = probe["observed_share_bridge"]
    observations = [
        _observation("issued_shares_opening", "2025 年期初发行股数", bridge["2025_opening"],
                     "2025-01-01", annual["role"], [_ref(annual, 42)]),
        _observation("issued_shares_closing", "2025 年期末发行股数", bridge["2025_closing"],
                     "2025-12-31", annual["role"], [_ref(annual, 42)]),
        _observation("reported_buyback_implementation", "年报列回购实施不适用（非库存股零证明）",
                     bridge["2025_annual_buyback_implementation"], "2025-12-31",
                     annual["role"], [_ref(annual, 46)]),
        _observation("treasury_shares", "库存股栏空白，不能读为零", None,
                     "2025-12-31", annual["role"], [_ref(annual, 53)]),
    ]
    result = assess_share_capital_policy(None, security_id=probe["security_id"],
                                       as_of=date.fromisoformat(as_of))
    return docs, observations, {
        "endpoint_difference_shares": str(int(bridge["2025_closing"]) - int(bridge["2025_opening"])),
        "difference_semantics": "观察端点之差；不是期间无事件、逐日股数或当前 S 的证明。",
        "daily_share_series": None, "treasury_shares": None,
        "policy_execution": _plain(asdict(result)),
        "policy_input": None,
        "policy_input_reason": "没有覆盖指定 as_of 且时点已核实的结构观察，不能由年报端点制造结构证据。",
    }, [
        _gap("S", ["event_complete_registration", "share_classes", "treasury_shares", "available_at"],
             "发行股数端点不是普通股经济权益对应的逐日 S；回购不适用不证明库存股零。"),
        _gap("MV", ["P_as_of", "S_as_of"], "不以 A 股价格乘未核实口径的发行股数。"),
    ]


def _buybacks(root, probe, rows, as_of):
    if probe["plan_id"] != "sh.600519:2024-09-21:capital-reduction":
        raise ValueError("buyback plan identity mismatch")
    roles = {"first_execution", *(item["evidence_role"] for item in probe["cumulative_checkpoints"])}
    docs = [_document(root, probe, doc, rows, doc["evidence_pages"])
            for doc in probe["documents"] if doc["role"] in roles]
    by_role = {doc["role"]: doc for doc in docs}
    first = probe["verified_execution_day"]
    observations = [_observation(
        "first_execution_amount_cny", "首日实际执行金额（非完整 B_buyback）", first["amount_cny"],
        first["executed_on"], first["evidence_role"], [_ref(by_role[first["evidence_role"]], 2)],
    )]
    previous_day, previous_value = first["executed_on"], to_decimal(first["amount_cny"])
    previous_shares = int(first["shares"])
    previous_ref = observations[0]["evidence_refs"][0]
    intervals = []
    for checkpoint in probe["cumulative_checkpoints"]:
        day, value = checkpoint["through"], to_decimal(checkpoint["amount_cny"])
        shares = int(checkpoint["shares"])
        if date.fromisoformat(day) <= date.fromisoformat(previous_day):
            raise ValueError("cumulative dates not increasing")
        delta = value - previous_value
        if delta < 0 or shares < previous_shares or delta != to_decimal(checkpoint["delta_amount_cny"]):
            raise ValueError("cumulative bridge mismatch")
        doc = by_role[checkpoint["evidence_role"]]
        ref = _ref(doc, 2)
        observations.append(_observation("cumulative_amount_cny", "截至该日累计金额", str(value),
                                         day, doc["role"], [ref]))
        intervals.append({
            "start_exclusive": previous_day, "end_inclusive": day,
            "difference_cny": str(delta), "difference_shares": str(shares - previous_shares),
            "evidence_refs": [previous_ref, ref], "daily_allocation_status": "UNKNOWN",
            "executed_on": None, "daily_amounts": None,
        })
        previous_day, previous_value, previous_shares, previous_ref = day, value, shares, ref
    return docs, observations, {
        "plan_id": probe["plan_id"], "first_execution_day": first["executed_on"],
        "first_execution_shares": first["shares"], "first_execution_amount_cny": first["amount_cny"],
        "intervals": intervals, "final_cumulative_amount_cny": str(previous_value),
        "unlocated_amount_after_first_day_cny": str(previous_value - to_decimal(first["amount_cny"])),
        "actual_last_execution_day": None, "verified_cancellation_effective_on": None,
        "reported_completion_on": probe["reported_plan_completion_on"],
        "first_amount_semantics": "已观察执行日与金额；未证明 PIT 可用、合格注销/完整窗口，不直接计入 B_buyback 或 GG。",
    }, [
        _gap("B_buyback", ["all_execution_days", "window_all_plans", "qualifying_cancellation", "available_at"],
             "累计差分不分配到月末/完成日，不平均分摊；单笔已知也不等于发行人完整窗口。"),
        _gap("GG", ["B_buyback", "D", "MV", "full_window_coverage"], "必要跨域输入未闭环。"),
    ]


def _cashflow(root, probe, rows, as_of):
    docs = [_document(root, probe, doc, rows, doc["pages"]) for doc in probe["documents"]]
    by_role = {doc["role"]: doc for doc in docs}
    observations, comparisons = [], []
    for item in probe["items"]:
        values = [item["original_value"], item["amended_value"], item["september_value"]]
        refs = []
        for role, value in zip(("original_annual", "amended_annual", "september_bundle"), values):
            ref = _ref(by_role[role], item["source_pages"][role])
            refs.append(ref)
            observations.append(_observation(item["id"], item["label"], value,
                                             probe["period_end"], role, [ref]))
        comparisons.append({"field": item["id"], "label": item["label"],
                            "original": values[0], "amended": values[1], "september": values[2],
                            "amendment_delta": str(to_decimal(values[1]) - to_decimal(values[0])),
                            "september_matches_original": values[2] == values[0], "evidence_refs": refs})
    by_field = {item["id"]: item for item in probe["items"]}
    subtotals = [{
        "version": role,
        "ocf_minus_capex_cny": str(to_decimal(by_field["operating_net"][key])
                                   - to_decimal(by_field["capex_cash_paid"][key])),
        "evidence_refs": [_ref(by_role[role], by_field[field]["source_pages"][role])
                          for field in ("operating_net", "capex_cash_paid")],
        "fcf_status": "UNKNOWN", "fcf_value": None,
    } for role, key in (("original_annual", "original_value"), ("amended_annual", "amended_value"))]
    return docs, observations, {
        "statement_scope": probe["statement_scope"], "unit": probe["unit"],
        "comparisons": comparisons, "ocf_minus_capex_subtotals_not_fcf": subtotals,
        "subtotal_semantics": "仅 OCF−capex 算术中间值，缺未重复扣除租赁现金、归属权益/少数股东 alpha 和 PIT；不是 FCF。",
        "latest_visible_version": None,
        "version_warning": "9 月选定行重现原值；不以归档晚覆盖 8 月更正，不宣称整份文件版本关系已证明。",
        "premise_execution": _premise(as_of),
    }, _financial_gaps("2025")


def _financial_gaps(year):
    return [
        _gap("FCF", ["OCF_pit", "capex_pit", "lease_cash", "attributable_equity", "minority_interest"],
             f"{year} 个案原文数值不等于完整归属 FCF 输入；不把租赁现金/少数股东权益缺失当零。"),
        _gap("premise.roe_5y", ["six_consecutive_equities", "five_parent_profits", "available_at"],
             "单报告期不能代替六个连续年末权益与五年净利润。"),
        _gap("absolute_valuation", ["five_annual_FCF", "TTM_FCF", "P", "S", "C", "A", "IB"],
             "未调用要求完整参数的估值函数，不用默认零制造可计算性。"),
        _gap("latest_visible_version", ["historical_availability", "complete_revisions_and_withdrawals"],
             "仅比较已固定文件，不选定声称截至 as_of 最新的有效财报。"),
    ]


def _financial(root, probe, rows, as_of):
    fields = {item["field"]: item for item in probe["field_definitions"]}
    annual_pages = sorted({item["evidence_page"] for item in fields.values()} | {70})
    roles = {item["role"] for item in probe["observed_versions"]}
    docs = [_document(root, probe, doc, rows, annual_pages if doc["role"] in roles else [3, 4])
            for doc in probe["documents"]
            if doc["role"] in roles or doc["role"] in {
                "first_correction_special_review", "second_correction_special_review"}]
    by_role = {doc["role"]: doc for doc in docs}
    observations = []
    versions = []
    for version in probe["observed_versions"]:
        doc = by_role[version["role"]]
        for field, value in version["fields"].items():
            definition = fields[field]
            observations.append(_observation(field, definition["source_label"], value,
                                             probe["period_end"], doc["role"],
                                             [_ref(doc, definition["evidence_page"])]))
        revenue, cost = to_decimal(version["fields"]["revenue"]), to_decimal(version["fields"]["operating_cost"])
        gross_profit = revenue - cost
        versions.append({
            "version": doc["role"], "revenue_cny": str(revenue), "operating_cost_cny": str(cost),
            "gross_profit_cny": str(gross_profit),
            "gross_margin_pct": None if revenue == 0 else str(gross_profit / revenue * 100),
            "evidence_refs": [_ref(doc, fields[field]["evidence_page"])
                              for field in ("revenue", "operating_cost")],
            "semantics": "所选版本的原文算术，不是历史可用盈利评分或未来增长判断。",
        })
    first, second, third = [item["fields"] for item in probe["observed_versions"]]
    reclassifications = []
    for group in (("investment_property", "fixed_assets", "intangible_assets"),
                  ("other_noncurrent_financial_assets", "other_noncurrent_assets")):
        deltas = [to_decimal(third[key]) - to_decimal(second[key]) for key in group]
        reclassifications.append({
            "fields": list(group), "second_correction_deltas_cny": [str(value) for value in deltas],
            "sum_cny": str(sum(deltas, Decimal("0"))),
            "evidence_refs": [_ref(by_role[role], fields[key]["evidence_page"])
                              for role in ("first_corrected_annual", "second_corrected_annual") for key in group],
        })
    return docs, observations, {
        "statement_scope": "CONSOLIDATED", "unit": "CNY", "version_arithmetic": versions,
        "first_revenue_delta_cny": str(to_decimal(second["revenue"]) - to_decimal(first["revenue"])),
        "first_cost_delta_cny": str(to_decimal(second["operating_cost"]) - to_decimal(first["operating_cost"])),
        "gross_profit_difference_cny": str(to_decimal(versions[1]["gross_profit_cny"])
                                            - to_decimal(versions[0]["gross_profit_cny"])),
        "reclassifications": reclassifications, "latest_visible_version": None,
        "amended_whole_statement_audit_status": "UNKNOWN",
        "second_special_report_period": "UNKNOWN_YEAR_SCOPE_CONFLICT",
        "audit_warning": "专项审核/鉴证不是整份重审；第二轮标题/对象为 2022—2023，用途与页眉出现 2024，不能静默统一。此缺口不阻止本报告原文对照。",
        "audit_evidence_refs": [_ref(by_role[role], page)
                                for role, page in (("original_annual", 70),
                                                   ("first_correction_special_review", 3),
                                                   ("second_correction_special_review", 3),
                                                   ("second_correction_special_review", 4))],
        "version_warning": "毛利差零不证明所有财报/FCF 输入不变；收入基数改变，算术毛利率也变。旧空白负债保留 null。",
        "premise_execution": _premise(as_of),
    }, _financial_gaps("2022")


BUILDERS = {"shares-000858": _shares, "buybacks-600519": _buybacks,
            "cashflow-000637": _cashflow, "financial-002570": _financial}


def build_reports(root: Path = ROOT) -> list[dict]:
    import fitz

    root = root.resolve()
    scope_raw = (root / SCOPE_PATH).read_bytes()
    scope = _json(scope_raw)
    as_of, review_date = date.fromisoformat(scope["as_of"]), date.fromisoformat(scope["review_date"])
    if as_of > review_date or scope["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED":
        raise ValueError("unsupported diagnostic timing policy")
    if (scope["diagnostic_only"] is not True or scope["official_selection"] is not False
            or scope["real_pit_strategy_run"] is not False):
        raise ValueError("diagnostic boundary flags invalid")
    if [(item["sample_id"], item["security_id"]) for item in scope["samples"]] != list(SAMPLE_SECURITIES.items()):
        raise ValueError("single-issuer scope identity mismatch")
    verified_bytes(root, "RULE_SPEC.md", scope["rule_sha256"])
    code = [{"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}
            for path in CODE_PATHS]
    reports = []
    for sample in scope["samples"]:
        probes = [_json(verified_bytes(root, item["path"], item["sha256"]))
                  for item in sample["source_inputs"]]
        if any(probe["security_id"] != sample["security_id"] for probe in probes):
            raise ValueError("cross-security evidence input")
        if any(probe["exact_available_at_utc"] is not None for probe in probes):
            raise ValueError("frozen UNKNOWN policy requires new scope for verified availability")
        if any(probe["production_reader_ready"] is not False for probe in probes):
            raise ValueError("pilot source readiness changed; scope review required")
        rows, catalogue_sources = _catalogues(root, probes[-1])
        with calculation_context():
            docs, observations, analysis, gaps = BUILDERS[sample["sample_id"]](root, probes[0], rows, scope["as_of"])
        report = {
            "schema_version": "limited_sample_diagnostic_v1", "sample_id": sample["sample_id"],
            "title": TITLES[sample["sample_id"]] + "：限定样本诊断（diagnostic_only=true）",
            "security_id": sample["security_id"], "as_of": scope["as_of"],
            "review_date": scope["review_date"], "economic_period": sample["economic_period"],
            "diagnostic_only": True, "official_selection": False,
            "real_pit_strategy_run": False, "production_reader_ready": False,
            "output_scope": sample["output_scope"], "not_claimed": list(DISCLAIMERS),
            "timing_assumptions": {
                "policy": scope["timing_policy"], "available_at": None,
                "as_of_semantics": scope["as_of_semantics"], "admitted_pit_observation_count": 0,
                "reason": "目录日期/时刻不等于最早公众可用；本次不采用当日或下一交易日可用假设。抓取晚于 as_of 不倒填。",
                "future_action": "若取得更明确的版本/可用时点证据，另冻输入范围再诊断；不回写本报告。",
            },
            "source_documents": docs, "source_observations": observations,
            "observed_arithmetic_not_pit_rule_outputs": analysis,
            "necessary_input_gaps": gaps,
            "usage_scope": {
                "mode": "local_source_review_only", "source_terms_compliance_required": True,
                "bulk_use_or_redistribution_permission_verified": False,
                "note": "公开可获取不等于任意授权；未宣称已有全市场、商业或分享许可。未发送询证。",
            },
            "manifest": {
                "kind": "limited_diagnostic_manifest_not_StrategyRunManifest",
                "scope": {"path": SCOPE_PATH, "sha256": hashlib.sha256(scope_raw).hexdigest()},
                "rule_version": scope["rule_version"],
                "rule_identity": {"path": "RULE_SPEC.md", "sha256": scope["rule_sha256"]},
                "source_inputs": sample["source_inputs"], "catalogue_sources": catalogue_sources,
                "capture_provenance": [
                    {"path": item["path"], "declared_probe_date": probe.get("probe_date"),
                     "capture_completed_at_utc": probe.get("capture_completed_at_utc"),
                     "note": "缺少精确抓取日志时保留 null；抓取日期不是历史 available_at。"}
                    for item, probe in zip(sample["source_inputs"], probes)
                ],
                "code_sources": code, "serialization": "canonical_utf8_json_sorted_keys_no_runtime_clock",
                "dependency_versions": {"python": sys.version.split()[0], "pymupdf": fitz.VersionBind},
                "hash_scope": "all_report_content_except_top_level_logical_content_hash",
            },
        }
        report["logical_content_hash"] = logical_content_hash(report)
        validate_report(report)
        reports.append(report)
    return reports


def validate_report(report: dict) -> None:
    """Fail closed on output authority, numeric UNKNOWNs, or report tampering."""
    if (report["diagnostic_only"] is not True or report["official_selection"] is not False
            or report["real_pit_strategy_run"] is not False
            or report["production_reader_ready"] is not False):
        raise ValueError("diagnostic output authority changed")
    if SAMPLE_SECURITIES.get(report["sample_id"]) != report["security_id"]:
        raise ValueError("report security identity mismatch")
    date.fromisoformat(report["as_of"])
    if logical_content_hash(report) != report["logical_content_hash"]:
        raise ValueError("report content hash mismatch")
    forbidden = {"ranking", "rank", "top_n", "target_weights", "orders", "holdings",
                 "nav", "net_value", "composite_score", "candidate", "tier"}

    def check_keys(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("forbidden selection or backtest output")
            for item in value.values():
                check_keys(item)
        elif isinstance(value, list):
            for item in value:
                check_keys(item)

    check_keys(report)
    for item in report["source_observations"]:
        if item["pit_status"] != "UNKNOWN" or item["pit_value"] is not None:
            raise ValueError("unverified observation admitted as PIT input")
    for gap in report["necessary_input_gaps"]:
        if gap["status"] != "UNKNOWN" or gap["value"] is not None:
            raise ValueError("UNKNOWN dependency replaced by numeric value")


def render_markdown(report: dict) -> str:
    lines = [f'# {report["title"]}', "", "## 本报告不宣称", ""]
    lines.extend(f"- {item}" for item in report["not_claimed"])
    lines += ["", "## 冻结范围", "",
              f'- 证券：`{report["security_id"]}`；`as_of={report["as_of"]}`（请求历史收盘截止）。',
              f'- 复核日：`{report["review_date"]}`；经济期间：`{" — ".join(report["economic_period"])}`。',
              f'- 输出范围：`{", ".join(report["output_scope"])}`。',
              '- `diagnostic_only=true`、`official_selection=false`；生产 Reader 与真实编排状态不变。',
              "", "## 时点假设", "",
              f'- 处理：`{report["timing_assumptions"]["policy"]}`；`available_at=null`。',
              f'- {report["timing_assumptions"]["reason"]}',
              '- 目录时刻逐文件列于末节，供复核，不作为已核实的最早公开时点。',
              '- 接纳到 PIT 规则中的真实数值观察为 **0**；原文对照数值仍完整展示。',
              "", "## 原文观察与必要输入", "",
              "| 字段 | 经济日期 | 版本 | 原文观察值 | 指定 as_of 输入 | 物理页证据 |",
              "|---|---|---|---|---|---|"]
    for item in report["source_observations"]:
        value = "空白（非零）" if item["observed_value"] is None else item["observed_value"]
        lines.append(f'| {item["label"]} | {item["economic_date"]} | `{item["source_version"]}` | {value} | UNKNOWN | `{"; ".join(item["evidence_refs"])}` |')
    lines += ["", "## 已知部分的算术 / 纯逻辑缺口传播", "",
              "以下算术只针对上述原文观察，不作为已证实的历史 PIT 结论。纯逻辑门控若全部 UNKNOWN，表示输入不满足，而非对公司质量的完整判断。", "",
              "```json", json.dumps(report["observed_arithmetic_not_pit_rule_outputs"],
                                    ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False), "```",
              "", "## UNKNOWN 与未执行项", "",
              "| 字段/规则 | 缺少的依赖 | 原因 |", "|---|---|---|"]
    for gap in report["necessary_input_gaps"]:
        lines.append(f'| `{gap["field"]}=UNKNOWN` | `{", ".join(gap["missing_dependencies"])}` | {gap["reason"]} |')
    lines += ["", "整份更正后审计、完整窗口、逐日登记/流水等缺口按对应规则保留；不将它们作为查看原文和版本差额的通用前置条件。", "",
              "## 证据与时点逐文件绑定", ""]
    for doc in report["source_documents"]:
        lines += [f'### {doc["role"]}（公告 {doc["announcement_id"]}）', "",
                  f'- 原始来源：[巨潮 PDF]({doc["url"]})；本地 bytes：`{doc["path"]}`。',
                  f'- SHA-256：`{doc["sha256"]}`；物理页码：`{doc["evidence_pages"]}` / 全部 {doc["physical_page_count"]} 页。',
                  f'- 目录 `announcementTime`：`{doc["catalogue_announcement_time_beijing"]}`（北京时间；原始毫秒 `{doc["catalogue_announcement_time_ms"]}`）。',
                  '- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。', ""]
    lines += ["## 本地使用与复现", "",
              report["usage_scope"]["note"], "",
              f'- 规则：`{report["manifest"]["rule_version"]}`；SHA-256：`{report["manifest"]["rule_identity"]["sha256"]}`。',
              f'- 完整输入清单、工具/纯逻辑代码哈希见同名 JSON 的 `manifest`。',
              f'- 逻辑内容 SHA-256：`{report["logical_content_hash"]}`（canonical JSON，排除自身哈希字段）。',
              '- 同一范围、输入、规则与代码得到相同内容哈希；不声称输入已完整、历史时点已证实或事实因确定性而可靠。', ""]
    return "\n".join(lines)


def write_reports(reports: list[dict], output: Path) -> None:
    """Write derived pilot artifacts to a new directory only; never overwrite."""
    for report in reports:
        validate_report(report)
    output.mkdir(parents=True, exist_ok=False)
    for report in reports:
        stem = report["sample_id"] + "-diagnostic-only"
        (output / f"{stem}.json").write_bytes(canonical_bytes(report) + b"\n")
        (output / f"{stem}.md").write_bytes(render_markdown(report).encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT,
                        help="new local output directory; existing directory is refused")
    parser.add_argument("--check", action="store_true", help="verify frozen reports without writing")
    args = parser.parse_args()
    reports = build_reports()
    output = Path(args.output_dir)
    if args.check:
        for report in reports:
            stem = report["sample_id"] + "-diagnostic-only"
            if (output / f"{stem}.json").read_bytes() != canonical_bytes(report) + b"\n":
                raise ValueError(f"frozen JSON report differs: {stem}")
            if (output / f"{stem}.md").read_bytes() != render_markdown(report).encode("utf-8"):
                raise ValueError(f"frozen markdown report differs: {stem}")
    else:
        write_reports(reports, output)
    print(json.dumps({"diagnostic_only": True, "official_selection": False,
                      "reports": [{"sample_id": item["sample_id"],
                                   "logical_content_hash": item["logical_content_hash"]} for item in reports]},
                     ensure_ascii=True))


if __name__ == "__main__":
    main()
