"""Independent 2021 original: source-window completion, never a PIT FCF window.

The 2021 layout has 15.6-point split payment labels and a blank 2020 lease
comparison. It is parsed independently, not with the later annual's template.
Earlier artifacts/tools are frozen. Only ordinary same-PDF source arithmetic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import capture_financial_2021_000637 as capture
from scripts.pilots import verify_attributable_equity_000637 as equity
from scripts.pilots import verify_financial_2022_000637 as previous
from scripts.pilots import verify_financial_2024_000637 as geometry
from scripts.pilots import verify_minority_equity_000637 as minority
from turtle_quant.core.types import calculation_context, to_decimal

INPUTS = "docs/data-pilots/2026-10-02-financial-2021-000637-inputs.json"
TOOL = "scripts/pilots/verify_financial_2021_000637.py"
OUTPUT = "docs/data-pilots/financial-2021-000637-2026-10-02"
HEADER = "茂名石化实华股份有限公司2021年年度报告全文"
UNKNOWN_FIELDS = previous.UNKNOWN_FIELDS
ANNUAL_PAGES = ([153, 154, 155, 156], [163, 164, 165, 166], [254], 178, 215, 277, 285)
EXPECTED = {"E": "1036150908.16", "N": "129012380.05", "OCF": "61218330.54",
            "Capex": "289600814.84", "lease_financing_component": "12134633.45"}
ANNUAL_HASH = "e7ebbcaedb6b3155166d95fb93be95ee33ec36ffaaf36d28d03d40e3b25eb12d"
NOTICE_HASH = "fa0c83f1642dbee200b5be6ff6fa3dce1c79d2188d8402b2fabf8e2933307d23"
NOTICE_INTERPRETATION = "PERFORMANCE_MEETING_ADDRESS_CORRECTION_NOT_ANNUAL_FINANCIAL_VERSION"
WINDOW = {"independently_bound_original_years": [2021, 2022, 2023, 2024, 2025],
          "coverage_kind": "ORIGINAL_SOURCE_DOCUMENTS_ONLY_NOT_PIT_OR_STANDARD_FCF",
          "five_year_standard_fcf_complete": False, "historical_pit_complete": False}


def dated_asset_headers(words):
    unit, first = minority._one(words, "单位：元"), minority._one(words, "流动资产：")
    band = [word for word in words if unit[3] < word[1] and word[3] < first[1]]
    project = minority._one(band, "项目")
    parts = [word for word in band if word[0] > project[2]
             and abs(geometry.centre(word) - geometry.centre(project)) <= 1]
    result = []
    for right, expected in ((False, "2021年12月31日"), (True, "2020年12月31日")):
        column = sorted([word for word in parts if (word[0] >= 380) == right], key=lambda w: w[0])
        if len(column) != 4 or "".join(word[4] for word in column) != expected:
            raise ValueError("dated 2021 balance sheet columns changed")
        result.append((column[0][0], column[0][1], column[-1][2], column[-1][3], expected))
    return tuple(result)


def split_payment_row(words, first_label, second_label, headers):
    first = minority._one(words, first_label)
    matches = [word for word in words if word[4] == second_label
               and abs(geometry.centre(word) - geometry.centre(first) - 15.6) <= 1
               and abs(word[0] - first[0] + 18) <= 1]
    if len(matches) != 1:
        raise ValueError("split payment label not adjacent in the fixed 2021 layout")
    second = matches[0]
    return geometry.row_cells(words, first_label, headers, (first[1] + second[3]) / 2)


def extract_tables(asset_words, cash_words):
    assets = geometry.section(asset_words, "1、合并资产负债表", "2、母公司资产负债表")
    headers = dated_asset_headers(assets)
    rows = {name: geometry.row_cells(assets, label, headers) for name, label in
            (("E", equity.E_LABEL), ("N", "少数股东权益"), ("total_equity", "所有者权益合计"))}
    cash = geometry.section(cash_words, "5、合并现金流量表", "6、母公司现金流量表")
    minority._one(cash, "单位：元")
    columns = geometry.column_headers(cash, ("2021", "2020"), annual=True)
    labels = ["一、经营活动产生的现金流量：", "经营活动现金流入小计", "经营活动现金流出小计",
              "经营活动产生的现金流量净额", "二、投资活动产生的现金流量：",
              "购建固定资产、无形资产和其", "他长期资产支付的现金",
              "投资活动产生的现金流量净额", "三、筹资活动产生的现金流量：", "支付其他与筹资活动有关的现"]
    markers = [minority._one(cash, label) for label in labels]
    if columns[0][3] >= markers[0][1] or any(a[3] >= b[1] for a, b in zip(markers, markers[1:])):
        raise ValueError("cashflow category or consolidated ordering changed")
    for name, label in (("inflow", labels[1]), ("outflow", labels[2]), ("OCF", labels[3])):
        rows[name] = geometry.row_cells(cash, label, columns)
    rows["Capex"] = split_payment_row(cash, labels[5], labels[6], columns)
    rows["financing_other_total"] = split_payment_row(cash, labels[-1], "金", columns)
    if any(value is not None and to_decimal(value) < 0 for value in rows["Capex"].values()):
        raise ValueError("Capex payment cannot be negative")
    return {"rows": rows, "checks": previous.table_checks(rows)}


def extract_lease_component(words, main_total):
    section = geometry.section(words, "（6）支付的其他与筹资活动有关的现金", "支付的其他与筹资活动有关的现金说明：")
    minority._one(section, "单位：元")
    columns = geometry.column_headers(section, ("本期发生额", "上期发生额"))
    payment = geometry.row_cells(section, "偿还租赁负债支付的金额", columns)
    total = geometry.row_cells(section, "合计", columns)
    checks = {}
    for column in payment:
        if payment[column] is not None and to_decimal(payment[column]) < 0:
            raise ValueError("lease payment cannot be negative")
        checks[column] = geometry.reconcile([payment[column], total[column], main_total[column]],
                                            lambda p, n, m: abs(p - n) + abs(n - m))
    return {**payment, "note_total": total, "checks": checks, "cashflow_category": "FINANCING",
            "observation_state": "EXPLICIT_COMPONENT_NOT_COMPLETE_LEASE_CASH",
            "prior_comparative_state": "BLANK_NOT_ZERO",
            "full_lease_cash_coverage": "UNKNOWN", "principal_interest_cash_bridge": "UNKNOWN",
            "full_lease_cash_not_already_deducted": None}


def source_arithmetic(observations):
    if set(observations) != {"E", "N", "OCF", "Capex"}:
        raise ValueError("ordinary source dependencies incomplete")
    e, n, ocf, capex = (observations[key] for key in ("E", "N", "OCF", "Capex"))
    alpha = equity.calculate_source_alpha(e, n)
    fields = {"E": "attributable_equity", "N": "minority_interest", "OCF": "operating_cash_flow", "Capex": "capex_cash_paid"}
    for key, item in observations.items():
        if (any(item.get(join) != e[join] or item.get(join) is None for join in equity.JOIN_KEYS)
                or item.get("period_start") != "2021-01-01" or item["period_end"] != "2021-12-31"
                or item["field"] != fields[key]):
            raise ValueError("same-version annual source identity or fields changed")
    if capex["observed_value"] is not None and to_decimal(capex["observed_value"]) < 0:
        raise ValueError("Capex payment cannot be negative")
    result = {"alpha_observed": alpha["alpha_observed"], "ocf_minus_capex_cny": None,
              "FCF_ordinary_source_arithmetic_cny": None, "status": "UNKNOWN"}
    if alpha["alpha_observed"] is None or any(item["observed_value"] is None for item in (ocf, capex)):
        return result
    with calculation_context():
        difference = to_decimal(ocf["observed_value"]) - to_decimal(capex["observed_value"])
        result.update(ocf_minus_capex_cny=format(difference, "f"),
                      FCF_ordinary_source_arithmetic_cny=format(difference * to_decimal(alpha["alpha_observed"]), "f"),
                      status="SOURCE_ARITHMETIC_ONLY_NOT_PIT")
    return result


def compare_sources(bundle, later_bundle):
    rows = {}
    for field in ("E", "N", "OCF", "Capex"):
        own = bundle["tables"]["rows"][field]["current_cny"]
        later = later_bundle["tables"]["rows"][field]["prior_comparative_cny"]
        check = geometry.reconcile([own, later], lambda a, b: a - b)
        rows[field] = {"independent_2021_source_cny": own, "2022_original_comparative_cny": later, "check": check}
    return rows


def fixed_scope(scope):
    required = {"schema_version": "financial_2021_000637_scope_v1", "security_id": "sz.000637",
                "issuer": "茂名石化实华股份有限公司", "as_of": "2026-09-30", "review_date": "2026-10-02",
                "period_start": "2021-01-01", "period_end": "2021-12-31", "statement_scope": "CONSOLIDATED", "unit": "CNY",
                "diagnostic_only": True, "official_selection": False, "timing_policy": "UNKNOWN_UNLESS_VERIFIED"}
    if any(type(scope.get(key)) is not type(value) or scope[key] != value for key, value in required.items()):
        raise ValueError("fixed 2021 diagnostic scope changed")
    annual = scope["annual"]
    if ((annual["role"], annual["announcement_id"]) != capture.ANNUAL[:2]
            or tuple(annual[key] for key in ("asset_pages", "cashflow_pages", "lease_note_pages", "currency_page",
                                           "consolidated_notes_page", "parent_notes_page", "page_count")) != ANNUAL_PAGES
            or annual["pdf_sha256"] != ANNUAL_HASH or annual["expected"] != EXPECTED):
        raise ValueError("annual identity, expected fields or physical pages changed")
    notice = scope["event_correction"]
    if (notice["announcement_id"] != capture.NOTICE[1] or notice["pdf_sha256"] != NOTICE_HASH or notice["page_count"] != 2
            or notice["evidence_pages"] != [1, 2] or notice["interpretation"] != NOTICE_INTERPRETATION):
        raise ValueError("event correction scope changed")


def build_review(root=ROOT, render_dir=None):
    import fitz

    root = Path(root).resolve()
    scope_raw = (root / INPUTS).read_bytes()
    scope = base._json(scope_raw)
    fixed_scope(scope)
    base.verified_bytes(root, "RULE_SPEC.md", geometry.RULE_HASH)
    old = scope["previous_2022_review"]
    old_report = base._json(base.verified_bytes(root, old["path"], old["sha256"]))
    previous.validate_review(old_report)
    if old_report["logical_content_hash"] != old["logical_content_hash"] or old_report != previous.build_review(root):
        raise ValueError("previous 2022 diagnostic or bound original evidence changed")
    audit = base._json(base.verified_bytes(root, scope["capture"]["path"], scope["capture"]["sha256"]))
    if (audit["schema_version"] != "financial_2021_000637_capture_v1" or audit["security_id"] != "sz.000637"
            or audit["target_period_end"] != "2021-12-31" or len(audit["resources"]) != 5
            or len(audit["documents"]) != 2 or len(audit["catalogues"]) != 3 or audit["exact_available_at_utc"] is not None
            or any(audit[key] is not False for key in ("complete_revision_chain_verified", "snapshot_published", "production_reader_ready", "research_eligible"))):
        raise ValueError("capture identity or authority changed")
    resources = {item["name"]: item for item in audit["resources"]}
    if len(resources) != 5:
        raise ValueError("duplicate raw resource identity")
    parsed = []
    for number, (query, item) in enumerate(zip(capture.QUERIES, audit["catalogues"]), 1):
        resource = resources[item["resource"]]
        raw = base.verified_bytes(root, resource["local_path"], resource["sha256"])
        if (item["resource"] != f"catalogue-{number}.json" or resource["method"] != "POST" or resource["url"] != capture.ENDPOINT
                or resource["request_data"] != {**capture.PAYLOAD, "searchkey": query} or item["searchkey"] != query
                or resource["bytes"] != len(raw) or item["completeness_scope"] != "FILTERED_CURRENT_RESPONSE_ONLY"
                or item["empty_result_proves_no_withdrawal"] is not False):
            raise ValueError("catalogue request or coverage binding changed")
        rows = capture.previous.parse_catalogue(raw)
        if type(item["reported_total"]) is not int or len(rows) != item["reported_total"] or list(rows) != item["announcement_ids"]:
            raise ValueError("catalogue audit disagrees with raw response")
        parsed.append(rows)
    found = capture.merge_catalogues(parsed)

    def document(recorded, target, plan, pages, header):
        resource = resources[recorded["resource"]]
        role, identifier, day, title = target
        url = f"https://static.cninfo.com.cn/finalpage/{day}/{identifier}.PDF"
        if (recorded["role"] != role or recorded["announcement_id"] != identifier or recorded["catalogue_title"] != title
                or recorded["catalogue_time_raw_ms"] != found[identifier]["announcementTime"] or recorded["exact_available_at_utc"] is not None
                or resource["method"] != "GET" or resource["url"] != url or resource["request_data"] is not None
                or resource["sha256"] != plan["pdf_sha256"]):
            raise ValueError("explicit PDF identity, URL or raw clock changed")
        raw = base.verified_bytes(root, resource["local_path"], resource["sha256"])
        if not raw.startswith(b"%PDF-") or len(raw) != resource["bytes"]:
            raise ValueError("raw PDF signature or size mismatch")
        doc = {"role": role, "announcement_id": identifier, "url": url, "path": resource["local_path"],
               "sha256": plan["pdf_sha256"], "page_count": plan["page_count"], "evidence_pages": sorted(pages),
               "catalogue_title": title, "catalogue_time_raw_ms": recorded["catalogue_time_raw_ms"], "exact_available_at_utc": None}
        texts, words = {}, {}
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            if len(pdf) != doc["page_count"]:
                raise ValueError("PDF page count mismatch")
            for page in pages:
                texts[page] = "".join(pdf[page - 1].get_text().split())
                words[page] = pdf[page - 1].get_text("words")
                if header is not None and (header not in texts[page] or not 595 <= pdf[page - 1].rect.width <= 596):
                    raise ValueError("annual issuer/year/page geometry changed")
            if render_dir is not None:
                output = Path(render_dir) / role
                output.mkdir(parents=True, exist_ok=False)
                for page in pages:
                    pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f"physical-{page}.png")
        return doc, texts, words

    def combined(words, pages):
        return [(*word[:1], word[1] + i * 1000, word[2], word[3] + i * 1000, *word[4:])
                for i, page in enumerate(pages) for word in words[page]]

    plan = scope["annual"]
    pages = sorted(set(plan["asset_pages"] + plan["cashflow_pages"] + plan["lease_note_pages"] +
                       [plan[key] for key in ("currency_page", "consolidated_notes_page", "parent_notes_page")]))
    annual_doc, texts, words = document(audit["documents"][0], capture.ANNUAL, plan, pages, HEADER)
    if ("本集团及境内子公司以人民币为记账本位币" not in texts[178]
            or "七、合并财务报表项目注释" not in texts[215] or "母公司财务报表主要项目注释" not in texts[277]):
        raise ValueError("currency or consolidated note boundary changed")
    tables = extract_tables(combined(words, plan["asset_pages"]), combined(words, plan["cashflow_pages"]))
    component = extract_lease_component(combined(words, plan["lease_note_pages"]), tables["rows"]["financing_other_total"])
    for name, value in EXPECTED.items():
        actual = component["current_cny"] if name == "lease_financing_component" else tables["rows"][name]["current_cny"]
        if actual != value:
            raise ValueError(f"source value disagrees with frozen scope: {name}")
    observations = {}
    for name, field in (("E", "attributable_equity"), ("N", "minority_interest"), ("OCF", "operating_cash_flow"), ("Capex", "capex_cash_paid")):
        field_pages = plan["asset_pages"] if name in ("E", "N") else plan["cashflow_pages"]
        observations[name] = {"field": field, "security_id": "sz.000637", "period_start": "2021-01-01", "period_end": "2021-12-31",
                              "statement_scope": "CONSOLIDATED", "unit": "CNY", "version": plan["role"], "document_sha256": annual_doc["sha256"],
                              "observed_value": tables["rows"][name]["current_cny"], "evidence_refs": [base._ref(annual_doc, page) for page in field_pages],
                              "diagnostic_available_at": None, "historical_pit_status": "UNKNOWN"}
    component["evidence_refs"] = [base._ref(annual_doc, page) for page in plan["lease_note_pages"]]
    bundle = {"version": plan["role"], "observations": observations, "tables": tables,
              "ordinary_source_arithmetic": source_arithmetic(observations), "lease_financing_component": component,
              "pit_and_standard_outputs": {key: None for key in UNKNOWN_FIELDS}}
    notice_doc, texts, _ = document(audit["documents"][1], capture.NOTICE, scope["event_correction"], [1, 2], None)
    if (any(value not in texts[1] for value in ("证券代码：000637", "茂名石化实华股份有限公司", "2022-039", "网络交流地址",
                                               "深证证券交易所互动易平台", "深圳证券交易所互动易平台"))
            or "除上述更正内容外，公告中其他内容不变" not in texts[2]):
        raise ValueError("event correction object or boundary changed")
    code_paths = sorted(set(old_report["manifest"]["code_hashes"]) | {TOOL, "scripts/pilots/capture_financial_2021_000637.py"})
    report = {"schema_version": "financial_2021_000637_diagnostic_v1", "title": "茂化实华 2021 年原文窗口扩展诊断",
              "security_id": "sz.000637", "as_of": "2026-09-30", "review_date": "2026-10-02", "period_start": "2021-01-01", "period_end": "2021-12-31",
              "diagnostic_only": True, "official_selection": False, "production_reader_ready": False,
              "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "diagnostic_available_at": None, "historical_pit_observations_admitted": 0,
              "complete_revision_chain_verified": False, "full_amended_audit_status": "UNKNOWN",
              "source_documents": [annual_doc], "version_bundles": [bundle], "original_source_window": base._json(base.canonical_bytes(WINDOW)),
              "comparative_corroboration": {"document": old_report["source_documents"][0], "interpretation": "CORROBORATION_ONLY_NOT_2021_SOURCE_OR_PIT",
                                            "rows": compare_sources(bundle, old_report["version_bundles"][0]), "used_to_replace_2021_source": False},
              "event_correction": {"document": notice_doc, "interpretation": NOTICE_INTERPRETATION,
                                   "used_as_annual_field_version": False, "audit_gate_conclusion": "UNKNOWN"},
              "catalogue_queries": audit["catalogues"], "current_catalogue_rows": [found[key] for key in sorted(found)],
              "remaining_gaps": ["complete_lease_cash_and_overlap", "verified_available_at", "latest_visible_version",
                                 "complete_revision_withdrawal_chain", "full_amended_audit_status", "cross_year_input_compatibility", "source_use_scope"],
              "not_claimed": ["不是官方 Top-N、真实选股、真实 PIT 规则运行、可发布回测或投资建议。",
                              "不生成排名、权重、订单、持仓、净值或 F1—F5，不改变生产状态。",
                              "五份年度原版固定不等于完整五年标准 FCF 或 PIT 输入。",
                              "2020 租赁比较栏空白不是零；业绩说明会地址更正不是财务科目版本。"],
              "manifest": {"rule_version": "v1.3.2", "rule_sha256": geometry.RULE_HASH,
                           "scope": {"path": INPUTS, "sha256": hashlib.sha256(scope_raw).hexdigest()}, "capture": scope["capture"],
                           "previous_2022_review": old, "raw_resources": audit["resources"],
                           "code_hashes": {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in code_paths}}}
    report["logical_content_hash"] = base.logical_content_hash(report)
    validate_review(report)
    return report


def validate_review(report):
    if (report["schema_version"] != "financial_2021_000637_diagnostic_v1" or report["security_id"] != "sz.000637"
            or (report["period_start"], report["period_end"], report["as_of"], report["review_date"]) != ("2021-01-01", "2021-12-31", "2026-09-30", "2026-10-02")
            or report["logical_content_hash"] != base.logical_content_hash(report) or report["diagnostic_only"] is not True
            or report["official_selection"] is not False or report["production_reader_ready"] is not False
            or report["diagnostic_available_at"] is not None or report["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED"
            or type(report["historical_pit_observations_admitted"]) is not int or report["historical_pit_observations_admitted"] != 0
            or report["complete_revision_chain_verified"] is not False or report["full_amended_audit_status"] != "UNKNOWN"
            or base.canonical_bytes(report["original_source_window"]) != base.canonical_bytes(WINDOW) or report["manifest"]["rule_version"] != "v1.3.2"
            or report["manifest"]["rule_sha256"] != geometry.RULE_HASH):
        raise ValueError("diagnostic identity, timing, window or authority changed")
    if len(report["source_documents"]) != 1 or len(report["version_bundles"]) != 1:
        raise ValueError("exactly one independently captured 2021 annual required")
    doc, bundle = report["source_documents"][0], report["version_bundles"][0]
    pages = sorted(set(ANNUAL_PAGES[0] + ANNUAL_PAGES[1] + ANNUAL_PAGES[2] + list(ANNUAL_PAGES[3:6])))
    previous._validate_doc(doc, capture.ANNUAL, 285, pages)
    if (doc["sha256"] != ANNUAL_HASH or bundle["version"] != capture.ANNUAL[0]
            or bundle["pit_and_standard_outputs"] != {key: None for key in UNKNOWN_FIELDS}
            or bundle["ordinary_source_arithmetic"] != source_arithmetic(bundle["observations"])
            or bundle["tables"]["checks"] != previous.table_checks(bundle["tables"]["rows"])):
        raise ValueError("source arithmetic or PIT boundary changed")
    for name, item in bundle["observations"].items():
        if (item["security_id"] != "sz.000637" or item["version"] != bundle["version"] or item["document_sha256"] != doc["sha256"]
                or item["diagnostic_available_at"] is not None or item["historical_pit_status"] != "UNKNOWN"
                or item["evidence_refs"] != [base._ref(doc, page) for page in ANNUAL_PAGES[0 if name in ("E", "N") else 1]]
                or item["observed_value"] != bundle["tables"]["rows"][name]["current_cny"] or item["observed_value"] != EXPECTED[name]):
            raise ValueError("field version, value or evidence changed")
    component = bundle["lease_financing_component"]
    if (set(component) != {"current_cny", "prior_comparative_cny", "note_total", "checks", "cashflow_category", "observation_state",
                          "prior_comparative_state", "full_lease_cash_coverage", "principal_interest_cash_bridge",
                          "full_lease_cash_not_already_deducted", "evidence_refs"}
            or component["cashflow_category"] != "FINANCING" or component["observation_state"] != "EXPLICIT_COMPONENT_NOT_COMPLETE_LEASE_CASH"
            or component["prior_comparative_state"] != "BLANK_NOT_ZERO" or component["prior_comparative_cny"] is not None
            or component["note_total"]["prior_comparative_cny"] is not None
            or bundle["tables"]["rows"]["financing_other_total"]["prior_comparative_cny"] is not None
            or component["current_cny"] != EXPECTED["lease_financing_component"]
            or component["full_lease_cash_coverage"] != "UNKNOWN" or component["principal_interest_cash_bridge"] != "UNKNOWN"
            or component["full_lease_cash_not_already_deducted"] is not None
            or component["evidence_refs"] != [base._ref(doc, page) for page in ANNUAL_PAGES[2]]):
        raise ValueError("partial lease cash promoted, blank filled or evidence changed")
    checks = {column: geometry.reconcile([component[column], component["note_total"][column], bundle["tables"]["rows"]["financing_other_total"][column]],
                                         lambda p, n, m: abs(p - n) + abs(n - m)) for column in ("current_cny", "prior_comparative_cny")}
    if checks != component["checks"]:
        raise ValueError("lease component reconciliation changed")
    notice = report["event_correction"]
    previous._validate_doc(notice["document"], capture.NOTICE, 2, [1, 2])
    if (notice["document"]["sha256"] != NOTICE_HASH or notice["interpretation"] != NOTICE_INTERPRETATION
            or notice["used_as_annual_field_version"] is not False or notice["audit_gate_conclusion"] != "UNKNOWN"):
        raise ValueError("event address correction promoted to financial version or audit proof")
    comparison = report["comparative_corroboration"]
    previous._validate_doc(comparison["document"], previous.capture.ANNUAL, 241,
                           sorted(set(previous.ANNUAL_PAGES[0] + previous.ANNUAL_PAGES[1] + previous.ANNUAL_PAGES[2] + list(previous.ANNUAL_PAGES[3:6]))))
    if (comparison["used_to_replace_2021_source"] is not False or comparison["interpretation"] != "CORROBORATION_ONLY_NOT_2021_SOURCE_OR_PIT"
            or comparison["document"]["sha256"] != "527871a9b13735822128d12df2ccf3d8b0c5a020ab5b35e2076ff319ce14d09a"
            or set(comparison["rows"]) != {"E", "N", "OCF", "Capex"}):
        raise ValueError("later comparative source replaced independent 2021 source")
    for name, row in comparison["rows"].items():
        if (row["independent_2021_source_cny"] != EXPECTED[name] or row["2022_original_comparative_cny"] != EXPECTED[name]
                or row["check"] != geometry.reconcile([row["independent_2021_source_cny"], row["2022_original_comparative_cny"]], lambda a, b: a - b)):
            raise ValueError("comparative corroboration binding changed")
    if (len(report["catalogue_queries"]) != 3 or any(query["searchkey"] != expected
            or query["completeness_scope"] != "FILTERED_CURRENT_RESPONSE_ONLY" or query["empty_result_proves_no_withdrawal"] is not False
            or type(query["reported_total"]) is not int or query["reported_total"] != len(query["announcement_ids"])
            for query, expected in zip(report["catalogue_queries"], capture.QUERIES))):
        raise ValueError("filtered catalogue promoted to historical completeness")
    forbidden = {"ranking", "rank", "top_n", "orders", "holdings", "nav", "target_weights", "F1", "F2", "F3", "F4", "F5"}

    def walk(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("forbidden strategy or five-year output")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(report)


def render_markdown(report):
    validate_review(report)
    bundle = report["version_bundles"][0]
    lines = ["# 茂化实华 2021 年限定原文诊断", "", "## 本报告不宣称", ""]
    lines += [f"- {line}" for line in report["not_claimed"]]
    lines += ["", "## 同版原文与普通口径算术", "", "| 项目 | 原版（元，alpha 无量纲） |", "|---|---:|"]
    for name in ("E", "N", "OCF", "Capex"):
        lines.append(f'| {name} | {bundle["observations"][name]["observed_value"]} |')
    for name in ("alpha_observed", "ocf_minus_capex_cny", "FCF_ordinary_source_arithmetic_cny"):
        lines.append(f'| {name} | {bundle["ordinary_source_arithmetic"][name]} |')
    lines += ["", "- E/N 来自 153—156 页合并资产负债表，列头 2021-12-31 / 2020-12-31；OCF/Capex 来自 163—166 页，列头 2021 / 2020 年度。",
              "- Capex 为两行购建长期资产支付科目，不用投资流出小计、不扣处置收款；支付科目的换行与 2022 模板不同，按实际 15.6 点间距核验。母公司表不混入。",
              "- 254 页明确筹资租赁偿还现金 12134633.45 元，与附注合计及主表相符；2020 比较栏三处为空白，保留 null，对账 UNKNOWN，不反推零。",
              "- 完整 Lease_cash、标准/保守 FCF 仍 UNKNOWN；不把现金部分、费用或租赁负债存量代替完整未重复扣减额。",
              "", "## 版本、时点与原文窗口", "",
              "- UNKNOWN_UNLESS_VERIFIED；单证券 sz.000637，as_of=2026-09-30；diagnostic_available_at=null，历史 PIT 准入 0。",
              "- 三次当前标题查询限定 2022-01-01 至 2026-10-02，返回 2/24/0 行；一个年报全文、一个摘要，单一全文命中和空撤回响应都不证明历史无其他版本。",
              "- 1212765280 更正的是业绩说明会网络交流地址：深证→深圳，不是年报字段版本或整份审计结论。",
              "- 2021 原文 E/N/OCF/Capex 与独立固定 2022 原版比较栏对平，只作交叉核对，比较栏不代替 2021 原文，也不证明历史最新版本。",
              "- 已独立绑定 2021—2025 五个年度原版；完整租赁现金、PIT、修订/撤回链、跨年输入兼容性及来源使用范围仍缺，不生成 F1—F5。",
              "", "## 原文证据", ""]
    for doc in [report["source_documents"][0], report["event_correction"]["document"], report["comparative_corroboration"]["document"]]:
        lines += [f'### {doc["role"]}', "", f'- 公告 `{doc["announcement_id"]}`：[官方 PDF]({doc["url"]})。',
                  f'- {doc["page_count"]} 页；SHA-256 `{doc["sha256"]}`；绑定物理页码 {doc["evidence_pages"]}。', ""]
    lines += ["## 可复现性与状态", "", f'- logical_content_hash：`{report["logical_content_hash"]}`。',
              "- canonical UTF-8 JSON、排序键、无新增运行时钟；保留固定抓取时钟作为输入。离线核验原始 bytes、证券/公告/PDF 身份、页码及前序证据，拒绝覆盖已有产物。",
              "- 旧工具、报告、规则、发布记录及生产快照不改写，九域与真实策略编排仍 not_ready。确定性不证明输入完整。",
              "- 遵守来源条款，不外发原始数据；公开可获取不自动授予共享/商业许可。Git 不备份被忽略的 storage 原文。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(OUTPUT))
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check and args.render_dir is not None:
        parser.error("--check does not write renders")
    report = build_review(render_dir=args.render_dir)
    artifacts = {"diagnostic-only.json": base.canonical_bytes(report) + b"\n", "diagnostic-only.md": render_markdown(report).encode("utf-8")}
    if args.check:
        for name, raw in artifacts.items():
            if (args.output_dir / name).read_bytes() != raw:
                raise ValueError(f"frozen 2021 diagnostic differs: {name}")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if any((args.output_dir / name).exists() for name in artifacts):
            raise FileExistsError("diagnostic artifact exists; refusing to overwrite")
        for name, raw in artifacts.items():
            with (args.output_dir / name).open("xb") as target:
                target.write(raw)
    print(json.dumps({"logical_content_hash": report["logical_content_hash"], "historical_pit_admitted": 0}))


if __name__ == "__main__":
    main()
