"""Extend one issuer's fixed source window to 2023, not PIT or production.

Reuse frozen 2024 low-level geometry/money helpers without editing them. 2023
balance-sheet columns contain dates, not 期末/期初 labels. Original and amended
cash notes differ: only the amended note explicitly identifies a lease payment.
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
from scripts.pilots import capture_financial_2023_000637 as capture
from scripts.pilots import verify_attributable_equity_000637 as equity
from scripts.pilots import verify_financial_2024_000637 as previous
from scripts.pilots import verify_minority_equity_000637 as minority
from turtle_quant.core.types import calculation_context, to_decimal

INPUTS = "docs/data-pilots/2026-10-02-financial-2023-000637-inputs.json"
TOOL = "scripts/pilots/verify_financial_2023_000637.py"
OUTPUT = "docs/data-pilots/financial-2023-000637-2026-10-02"
HEADER = "茂名石化实华股份有限公司2023年年度报告全文"
PAGE_BINDINGS = (
    ([132, 133, 134, 135], [140, 141], [227, 228], 156, 189, 249, 258,
     "NO_FINANCING_DETAIL_IN_FIXED_NOTE_SECTION"),
    ([134, 135, 136], [141, 142, 143], [247], 158, 206, 274, 283, "EXPLICIT_FINANCING_COMPONENT"),
)
UNKNOWN_FIELDS = previous.UNKNOWN_FIELDS
NOTICE_INTERPRETATION = "AUDITOR_APPOINTMENT_INTEGRITY_RECORD_DISCLOSURE_NOT_ANNUAL_FINANCIAL_FIELD_VERSION"


def dated_asset_headers(words):
    unit = minority._one(words, "单位：元")
    first = minority._one(words, "流动资产：")
    band = [word for word in words if unit[3] < word[1] and word[3] < first[1]]
    project = minority._one(band, "项目")
    parts = [word for word in band if word[0] > project[2]
             and abs(previous.centre(word) - previous.centre(project)) <= 1]
    columns = [[word for word in parts if word[0] < 380], [word for word in parts if word[0] >= 380]]
    headers = []
    for column, expected in zip(columns, ("2023年12月31日", "2023年1月1日")):
        column = sorted(column, key=lambda word: word[0])
        if len(column) != 4 or "".join(word[4] for word in column) != expected:
            raise ValueError("dated balance sheet current/opening columns changed")
        headers.append((column[0][0], column[0][1], column[-1][2], column[-1][3], expected))
    return tuple(headers)


def extract_tables(asset_words, cash_words):
    assets = previous.section(asset_words, "1、合并资产负债表", "2、母公司资产负债表")
    h = dated_asset_headers(assets)
    rows = {name: previous.row_cells(assets, label, h) for name, label in
            (("E", equity.E_LABEL), ("N", "少数股东权益"), ("total_equity", "所有者权益合计"))}
    cash = previous.section(cash_words, "5、合并现金流量表", "6、母公司现金流量表")
    minority._one(cash, "单位：元")
    c = previous.column_headers(cash, ("2023", "2022"), annual=True)
    labels = ["一、经营活动产生的现金流量：", "经营活动现金流入小计", "经营活动现金流出小计",
              "经营活动产生的现金流量净额", "二、投资活动产生的现金流量：",
              "购建固定资产、无形资产和其他长", "期资产支付的现金",
              "投资活动产生的现金流量净额", "三、筹资活动产生的现金流量：",
              "支付其他与筹资活动有关的现金"]
    markers = [minority._one(cash, label) for label in labels]
    if c[0][3] >= markers[0][1] or any(a[3] >= b[1] for a, b in zip(markers, markers[1:])):
        raise ValueError("cashflow category or consolidated row ordering changed")
    first, second = markers[5:7]
    if abs(previous.centre(second) - previous.centre(first) - 12) > 1 or abs(first[0] - second[0]) > 10:
        raise ValueError("split Capex payment row is not adjacent")
    for name, label in (("inflow", labels[1]), ("outflow", labels[2]), ("OCF", labels[3]),
                        ("financing_other_total", labels[-1])):
        rows[name] = previous.row_cells(cash, label, c)
    rows["Capex"] = previous.row_cells(cash, labels[5], c, (first[1] + second[3]) / 2)
    if any(value is not None and to_decimal(value) < 0 for value in rows["Capex"].values()):
        raise ValueError("Capex payment cannot be negative")
    return {"rows": rows, "checks": table_checks(rows)}


def table_checks(rows):
    return {column: {
        "equity": previous.reconcile([rows[name][column] for name in ("E", "N", "total_equity")],
                                     lambda e, n, total: e + n - total),
        "ocf": previous.reconcile([rows[name][column] for name in ("inflow", "outflow", "OCF")],
                                  lambda incoming, outgoing, net: incoming - outgoing - net),
    } for column in ("current_cny", "prior_comparative_cny")}


def extract_lease_component(note_words, main_total, mode):
    result = {"mode": mode, "current_cny": None, "prior_comparative_cny": None,
              "full_lease_cash_coverage": "UNKNOWN", "principal_interest_cash_bridge": "UNKNOWN",
              "full_lease_cash_not_already_deducted": None}
    if mode == PAGE_BINDINGS[0][-1]:
        section = previous.section(note_words, "61、现金流量表项目", "62、现金流量表补充资料")
        compact = "".join(word[4] for word in section)
        if ("与经营活动有关的现金" not in compact or "与投资活动有关的现金" not in compact
                or "与筹资活动有关的现金" in compact or "偿还租赁负债支付的金额" in compact):
            raise ValueError("original fixed note section boundary or missing-detail shape changed")
        result.update(cashflow_category="FINANCING_MAIN_TOTAL_NOT_ALLOCATED",
                      observation_state="NOT_IDENTIFIED_IN_FIXED_NOTE_SECTION", note_total=None,
                      reason="Main financing total is not a lease-specific observation; no cross-version fill")
        return result
    if mode != PAGE_BINDINGS[1][-1]:
        raise ValueError("unapproved lease note mode")
    heading = minority._one(note_words, "（3）与筹资活动有关的现金")
    start = minority._one(note_words, "支付的其他与筹资活动有关的现金")
    if heading[3] >= start[1]:
        raise ValueError("lease payment outside financing note")
    section = previous.section(note_words, start[4], "支付的其他与筹资活动有关的现金说明：")
    minority._one(section, "单位：元")
    columns = previous.column_headers(section, ("本期发生额", "上期发生额"))
    payment = previous.row_cells(section, "偿还租赁负债支付的金额", columns)
    total = previous.row_cells(section, "合计", columns)
    for column in payment:
        if payment[column] is not None and to_decimal(payment[column]) < 0:
            raise ValueError("lease cash payment cannot be negative")
        if total[column] != main_total[column] or (payment[column] is not None and payment[column] != total[column]):
            raise ValueError("single identified lease row does not match note/main financing total")
    result.update(**payment, cashflow_category="FINANCING", note_total=total,
                  observation_state="EXPLICIT_COMPONENT_NOT_COMPLETE_LEASE_CASH")
    return result


def source_arithmetic(observations):
    if set(observations) != {"E", "N", "OCF", "Capex"}:
        raise ValueError("ordinary source dependencies incomplete")
    e, n, ocf, capex = (observations[key] for key in ("E", "N", "OCF", "Capex"))
    alpha = equity.calculate_source_alpha(e, n)
    if any(item.get(key) != e[key] or item.get(key) is None for item in (ocf, capex) for key in equity.JOIN_KEYS):
        raise ValueError("cross-version/security/period/scope/unit/PDF source arithmetic")
    if (any(item.get("period_start") != "2023-01-01" or item["period_end"] != "2023-12-31" for item in observations.values())
            or ocf["field"] != "operating_cash_flow" or capex["field"] != "capex_cash_paid"):
        raise ValueError("source annual period or cashflow fields changed")
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


def fixed_scope(scope):
    required = {"schema_version": "financial_2023_000637_scope_v1", "security_id": "sz.000637",
                "issuer": "茂名石化实华股份有限公司", "as_of": "2026-09-30", "review_date": "2026-10-02",
                "period_start": "2023-01-01", "period_end": "2023-12-31", "statement_scope": "CONSOLIDATED",
                "unit": "CNY", "diagnostic_only": True, "official_selection": False,
                "timing_policy": "UNKNOWN_UNLESS_VERIFIED"}
    if any(type(scope.get(key)) is not type(value) or scope[key] != value for key, value in required.items()):
        raise ValueError("fixed 2023 diagnostic scope changed")
    if len(scope["documents"]) != 2:
        raise ValueError("two explicit annual versions required")
    for doc, target, pages in zip(scope["documents"], capture.TARGETS, PAGE_BINDINGS):
        if ((doc["role"], doc["announcement_id"]) != target[:2]
                or tuple(doc[key] for key in ("asset_pages", "cashflow_pages", "lease_note_pages", "currency_page",
                                             "consolidated_notes_page", "parent_notes_page", "page_count", "lease_note_mode")) != pages):
            raise ValueError("fixed annual identity or physical page bridge changed")
    notice = scope["earlier_correction_notice"]
    if (notice["announcement_id"] != capture.NOTICE[1] or notice["page_count"] != 17
            or notice["evidence_pages"] != [1, 2, 3] or notice["interpretation"] != NOTICE_INTERPRETATION):
        raise ValueError("correction notice is not a financial-field version")


def build_review(root=ROOT, render_dir=None):
    import fitz

    root = Path(root).resolve()
    scope_raw = (root / INPUTS).read_bytes()
    scope = base._json(scope_raw)
    fixed_scope(scope)
    base.verified_bytes(root, "RULE_SPEC.md", previous.RULE_HASH)
    old = scope["previous_2024_review"]
    old_report = base._json(base.verified_bytes(root, old["path"], old["sha256"]))
    previous.validate_review(old_report)
    if old_report["logical_content_hash"] != old["logical_content_hash"]:
        raise ValueError("previous frozen diagnostic identity changed")
    audit = base._json(base.verified_bytes(root, scope["capture"]["path"], scope["capture"]["sha256"]))
    if (audit["schema_version"] != "financial_2023_000637_capture_v1" or audit["security_id"] != "sz.000637"
            or audit["target_period_end"] != "2023-12-31" or len(audit["resources"]) != 6
            or len(audit["documents"]) != 3 or len(audit["catalogues"]) != 3
            or audit["exact_available_at_utc"] is not None
            or any(audit[key] is not False for key in ("complete_revision_chain_verified", "snapshot_published",
                                                      "production_reader_ready", "research_eligible"))):
        raise ValueError("capture scope or authority changed")
    resources = {item["name"]: item for item in audit["resources"]}
    if len(resources) != 6:
        raise ValueError("duplicate raw resource identity")
    parsed = []
    for number, (query, item) in enumerate(zip(capture.QUERIES, audit["catalogues"]), 1):
        resource = resources[item["resource"]]
        raw = base.verified_bytes(root, resource["local_path"], resource["sha256"])
        if (item["resource"] != f"catalogue-{number}.json" or resource["method"] != "POST"
                or resource["url"] != capture.ENDPOINT or resource["request_data"] != {**capture.PAYLOAD, "searchkey": query}
                or item["searchkey"] != query or resource["bytes"] != len(raw)
                or item["completeness_scope"] != "FILTERED_CURRENT_RESPONSE_ONLY"
                or item["empty_result_proves_no_withdrawal"] is not False):
            raise ValueError("catalogue request or coverage binding changed")
        rows = capture.previous.parse_catalogue(raw)
        if len(rows) != item["reported_total"] or list(rows) != item["announcement_ids"]:
            raise ValueError("catalogue audit disagrees with raw response")
        parsed.append(rows)
    found = capture.merge_catalogues(parsed)
    documents, bundles = [], []

    def document(recorded, target, plan, pages):
        resource = resources[recorded["resource"]]
        role, identifier, day, title = target
        url = f"https://static.cninfo.com.cn/finalpage/{day}/{identifier}.PDF"
        if (recorded["role"] != role or recorded["announcement_id"] != identifier or recorded["catalogue_title"] != title
                or recorded["catalogue_time_raw_ms"] != found[identifier]["announcementTime"]
                or recorded["exact_available_at_utc"] is not None or resource["method"] != "GET"
                or resource["url"] != url or resource["request_data"] is not None or resource["sha256"] != plan["pdf_sha256"]):
            raise ValueError("explicit PDF identity, URL or raw clock changed")
        raw = base.verified_bytes(root, resource["local_path"], resource["sha256"])
        if not raw.startswith(b"%PDF-") or len(raw) != resource["bytes"]:
            raise ValueError("raw PDF signature or size mismatch")
        return raw, {"role": role, "announcement_id": identifier, "url": url, "path": resource["local_path"],
                     "sha256": plan["pdf_sha256"], "page_count": plan["page_count"], "evidence_pages": sorted(pages),
                     "catalogue_title": title, "catalogue_time_raw_ms": recorded["catalogue_time_raw_ms"],
                     "exact_available_at_utc": None}

    for plan, target, recorded in zip(scope["documents"], capture.TARGETS, audit["documents"][:2]):
        pages = sorted(set(plan["asset_pages"] + plan["cashflow_pages"] + plan["lease_note_pages"] +
                           [plan[key] for key in ("currency_page", "consolidated_notes_page", "parent_notes_page")]))
        raw, doc = document(recorded, target, plan, pages)
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            if len(pdf) != plan["page_count"]:
                raise ValueError("annual page count mismatch")
            texts, words = {}, {}
            for page in pages:
                texts[page] = "".join(pdf[page - 1].get_text().split())
                words[page] = pdf[page - 1].get_text("words")
                if HEADER not in texts[page] or not 595 <= pdf[page - 1].rect.width <= 596:
                    raise ValueError("annual issuer, year or page geometry changed")
            if ("本集团以人民币为记账本位币" not in texts[plan["currency_page"]]
                    or "合并财务报表项目注释" not in texts[plan["consolidated_notes_page"]]
                    or "母公司财务报表主要项目注释" not in texts[plan["parent_notes_page"]]
                    or not all(plan["consolidated_notes_page"] < page < plan["parent_notes_page"] for page in plan["lease_note_pages"])):
                raise ValueError("currency or consolidated note boundary changed")

            def combined(numbers):
                return [(*word[:1], word[1] + index * 1000, word[2], word[3] + index * 1000, *word[4:])
                        for index, page in enumerate(numbers) for word in words[page]]

            tables = extract_tables(combined(plan["asset_pages"]), combined(plan["cashflow_pages"]))
            component = extract_lease_component(combined(plan["lease_note_pages"]),
                                                tables["rows"]["financing_other_total"], plan["lease_note_mode"])
            if render_dir is not None:
                output = Path(render_dir) / plan["role"]
                output.mkdir(parents=True, exist_ok=False)
                for page in pages:
                    pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f"physical-{page}.png")
        for field, expected in plan["expected"].items():
            actual = component["current_cny"] if field == "lease_financing_component" else tables["rows"][field]["current_cny"]
            if actual != expected:
                raise ValueError(f"source value disagrees with frozen scope: {plan['role']}/{field}")
        observations = {}
        for name, field in (("E", "attributable_equity"), ("N", "minority_interest"),
                            ("OCF", "operating_cash_flow"), ("Capex", "capex_cash_paid")):
            field_pages = plan["asset_pages"] if name in ("E", "N") else plan["cashflow_pages"]
            observations[name] = {"field": field, "security_id": "sz.000637", "period_start": "2023-01-01",
                                  "period_end": "2023-12-31", "statement_scope": "CONSOLIDATED", "unit": "CNY",
                                  "version": plan["role"], "document_sha256": doc["sha256"],
                                  "observed_value": tables["rows"][name]["current_cny"],
                                  "evidence_refs": [base._ref(doc, page) for page in field_pages],
                                  "diagnostic_available_at": None, "historical_pit_status": "UNKNOWN"}
        component["evidence_refs"] = [base._ref(doc, page) for page in plan["lease_note_pages"]]
        bundles.append({"version": plan["role"], "observations": observations, "tables": tables,
                        "ordinary_source_arithmetic": source_arithmetic(observations), "lease_financing_component": component,
                        "pit_and_standard_outputs": {key: None for key in UNKNOWN_FIELDS}})
        documents.append(doc)
    notice_plan = scope["earlier_correction_notice"]
    notice_raw, notice_doc = document(audit["documents"][2], capture.NOTICE, notice_plan, notice_plan["evidence_pages"])
    with fitz.open(stream=notice_raw, filetype="pdf") as pdf:
        if len(pdf) != notice_plan["page_count"]:
            raise ValueError("correction notice page count mismatch")
        texts = ["".join(pdf[page - 1].get_text().split()) for page in notice_plan["evidence_pages"]]
        if ("证券代码：000637" not in texts[0] or "茂名石化实华股份有限公司" not in texts[0]
                or "关于拟变更会计师事务所的公告" not in texts[0] or "关于拟续聘会计师事务所的公告" not in texts[0]
                or "项目质量控制复核人" not in texts[0] or "警示函措施" not in texts[2]
                or "除上述更正内容外，公告中其他内容不变" not in texts[2]):
            raise ValueError("earlier notice object or disclosure boundary changed")
        if render_dir is not None:
            output = Path(render_dir) / capture.NOTICE[0]
            output.mkdir(parents=True, exist_ok=False)
            for page in notice_plan["evidence_pages"]:
                pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f"physical-{page}.png")
    code_paths = sorted(set(old_report["manifest"]["code_hashes"]) |
                        {TOOL, "scripts/pilots/capture_financial_2023_000637.py"})
    report = {"schema_version": "financial_2023_000637_diagnostic_v1", "title": "茂化实华 2023 年原文窗口扩展诊断",
              "security_id": "sz.000637", "as_of": "2026-09-30", "review_date": "2026-10-02",
              "period_start": "2023-01-01", "period_end": "2023-12-31", "diagnostic_only": True,
              "official_selection": False, "production_reader_ready": False, "timing_policy": "UNKNOWN_UNLESS_VERIFIED",
              "diagnostic_available_at": None, "historical_pit_observations_admitted": 0,
              "complete_revision_chain_verified": False, "full_amended_audit_status": "UNKNOWN",
              "source_documents": documents, "version_bundles": bundles,
              "earlier_correction_notice": {"document": notice_doc, "interpretation": NOTICE_INTERPRETATION,
                                            "used_as_annual_field_version": False, "audit_gate_conclusion": "UNKNOWN"},
              "catalogue_queries": audit["catalogues"], "current_catalogue_rows": [found[key] for key in sorted(found)],
              "remaining_gaps": ["complete_lease_cash_and_overlap", "verified_available_at", "latest_visible_version",
                                 "complete_revision_withdrawal_chain", "full_amended_audit_status", "2021_2022_original_window"],
              "not_claimed": ["不是官方 Top-N、真实选股结果、真实 PIT 规则运行、可发布回测或投资建议。",
                              "不输出排名、权重、订单、持仓、净值或 F1—F5，不改变九域和真实策略编排状态。",
                              "目录时间/封面日期/抓取时刻不证明最早公众可用；不选择最新可见版本。",
                              "2022 比较栏不冒充原版，原版分项不由更正版或筹资总额补齐，不改写旧证据。"],
              "manifest": {"rule_version": "v1.3.2", "rule_sha256": previous.RULE_HASH,
                           "scope": {"path": INPUTS, "sha256": hashlib.sha256(scope_raw).hexdigest()},
                           "capture": scope["capture"], "previous_2024_review": old, "raw_resources": audit["resources"],
                           "code_hashes": {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in code_paths}}}
    report["logical_content_hash"] = base.logical_content_hash(report)
    validate_review(report)
    return report


def validate_review(report):
    if (report["schema_version"] != "financial_2023_000637_diagnostic_v1" or report["security_id"] != "sz.000637"
            or report["period_start"] != "2023-01-01" or report["period_end"] != "2023-12-31"
            or report["as_of"] != "2026-09-30" or report["review_date"] != "2026-10-02"
            or report["logical_content_hash"] != base.logical_content_hash(report) or report["diagnostic_only"] is not True
            or report["official_selection"] is not False or report["production_reader_ready"] is not False
            or report["diagnostic_available_at"] is not None or report["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED"
            or type(report["historical_pit_observations_admitted"]) is not int or report["historical_pit_observations_admitted"] != 0
            or report["complete_revision_chain_verified"] is not False or report["full_amended_audit_status"] != "UNKNOWN"
            or report["manifest"]["rule_version"] != "v1.3.2" or report["manifest"]["rule_sha256"] != previous.RULE_HASH):
        raise ValueError("diagnostic identity, timing or authority changed")
    if len(report["version_bundles"]) != 2 or len(report["source_documents"]) != 2:
        raise ValueError("exactly two annual versions required")
    for bundle, doc, target, pages in zip(report["version_bundles"], report["source_documents"], capture.TARGETS, PAGE_BINDINGS):
        evidence_pages = sorted(set(pages[0] + pages[1] + pages[2] + list(pages[3:6])))
        if (bundle["version"] != target[0] or doc["role"] != target[0] or doc["announcement_id"] != target[1]
                or doc["url"] != f"https://static.cninfo.com.cn/finalpage/{target[2]}/{target[1]}.PDF"
                or doc["catalogue_title"] != target[3] or doc["page_count"] != pages[6]
                or doc["evidence_pages"] != evidence_pages or type(doc["catalogue_time_raw_ms"]) is not int
                or doc["exact_available_at_utc"] is not None
                or bundle["pit_and_standard_outputs"] != {key: None for key in UNKNOWN_FIELDS}
                or bundle["ordinary_source_arithmetic"] != source_arithmetic(bundle["observations"])
                or bundle["tables"]["checks"] != table_checks(bundle["tables"]["rows"])):
            raise ValueError("source identity, arithmetic or PIT boundary changed")
        component = bundle["lease_financing_component"]
        keys = {"mode", "current_cny", "prior_comparative_cny", "full_lease_cash_coverage",
                "principal_interest_cash_bridge", "full_lease_cash_not_already_deducted",
                "cashflow_category", "observation_state", "note_total", "evidence_refs"}
        if target == capture.TARGETS[0]:
            keys.add("reason")
        if (set(component) != keys or component["mode"] != pages[-1] or component["full_lease_cash_coverage"] != "UNKNOWN"
                or component["principal_interest_cash_bridge"] != "UNKNOWN"
                or component["full_lease_cash_not_already_deducted"] is not None
                or component["evidence_refs"] != [base._ref(doc, page) for page in pages[2]]):
            raise ValueError("incomplete lease cash promoted or evidence changed")
        if target == capture.TARGETS[0]:
            if (component["current_cny"] is not None or component["prior_comparative_cny"] is not None
                    or component["note_total"] is not None or component["cashflow_category"] != "FINANCING_MAIN_TOTAL_NOT_ALLOCATED"
                    or component["observation_state"] != "NOT_IDENTIFIED_IN_FIXED_NOTE_SECTION"):
                raise ValueError("original missing lease detail was backfilled")
        else:
            if (component["cashflow_category"] != "FINANCING" or component["observation_state"] != "EXPLICIT_COMPONENT_NOT_COMPLETE_LEASE_CASH"
                    or component["note_total"] != bundle["tables"]["rows"]["financing_other_total"]):
                raise ValueError("lease financing evidence does not match main total")
            for column in ("current_cny", "prior_comparative_cny"):
                if component[column] is not None and (to_decimal(component[column]) < 0 or component[column] != component["note_total"][column]):
                    raise ValueError("lease cash payment inconsistent with source")
        for name, item in bundle["observations"].items():
            if (item["security_id"] != "sz.000637" or item["version"] != bundle["version"] or item["document_sha256"] != doc["sha256"]
                    or item["diagnostic_available_at"] is not None or item["historical_pit_status"] != "UNKNOWN"
                    or item["evidence_refs"] != [base._ref(doc, page) for page in pages[0 if name in ("E", "N") else 1]]
                    or item["observed_value"] != bundle["tables"]["rows"][name]["current_cny"]):
                raise ValueError("field version, evidence or source value changed")
    notice = report["earlier_correction_notice"]
    doc = notice["document"]
    if (notice["interpretation"] != NOTICE_INTERPRETATION or notice["used_as_annual_field_version"] is not False
            or notice["audit_gate_conclusion"] != "UNKNOWN" or doc["announcement_id"] != capture.NOTICE[1]
            or doc["role"] != capture.NOTICE[0] or doc["catalogue_title"] != capture.NOTICE[3]
            or doc["url"] != f"https://static.cninfo.com.cn/finalpage/{capture.NOTICE[2]}/{capture.NOTICE[1]}.PDF"
            or doc["page_count"] != 17 or doc["evidence_pages"] != [1, 2, 3]
            or type(doc["catalogue_time_raw_ms"]) is not int or doc["exact_available_at_utc"] is not None):
        raise ValueError("auditor appointment notice promoted to annual field/audit conclusion")
    if (len(report["catalogue_queries"]) != 3 or
            any(query["searchkey"] != expected or query["completeness_scope"] != "FILTERED_CURRENT_RESPONSE_ONLY"
                or query["empty_result_proves_no_withdrawal"] is not False
                or type(query["reported_total"]) is not int or query["reported_total"] != len(query["announcement_ids"])
                for query, expected in zip(report["catalogue_queries"], capture.QUERIES))):
        raise ValueError("filtered catalogue scope promoted to historical completeness")
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
    lines = [f'# {report["title"]}', "", "## 本报告不宣称", ""]
    lines += [f"- {item}" for item in report["not_claimed"]]
    lines += ["", "## 同版原文与算术（元）", "", "| 版本 | E | N | OCF | Capex | 普通口径原文算术 |",
              "|---|---:|---:|---:|---:|---:|"]
    for bundle in report["version_bundles"]:
        values = [bundle["observations"][name]["observed_value"] for name in ("E", "N", "OCF", "Capex")]
        lines.append("| " + " | ".join([bundle["version"], *values,
                                        bundle["ordinary_source_arithmetic"]["FCF_ordinary_source_arithmetic_cny"]]) + " |")
    lines += ["", "- 两版 E+N、OCF 流入−流出两列均对平。资产负债表列头明确为 2023-12-31/2023-01-01，现金流量表列头为 2023/2022 年度；不是 2024 页码/列名模板。",
              "- 同版 alpha 和普通口径仅原文算术（Decimal 28 位），不是历史 PIT 或标准 FCF。",
              "- 原版 227—228 页现金附注的固定章节没有筹资租赁明细。主表支付其他筹资现金 10104914.34 元不分配给租赁，原版租赁分项 UNKNOWN。",
              "- 更正版 247 页明确偿还租赁负债支付金额 10104914.34 元（2022 比较栏 14537724.60 元），附注合计与主表一致；不回填原版，也不等于完整 Lease_cash。",
              "- 全部租赁现金范围、本金/利息实际现金桥接与 OCF/Capex 去重未闭环，完整 Lease_cash、保守/标准 FCF、所有 PIT 项均 UNKNOWN。",
              "", "## 目录与时点", "", "- 三次固定标题查询，2024-01-01 至 2026-10-02，返回 6/23/0 行；仅证实当前过滤响应完整。",
              "- 年报结果包含摘要/半年报；只用两个显式全文 ID。空撤回结果不证明历史无撤回，当前目录/封面日期不证明当日已经是该 bytes，也不证明最早公开。",
              "- 额外固定更正公告 1222163844，正文 1—3 页更正会计师变更/续聘的诚信记录；附件为相关聘任公告，不用它建立财务科目版本或整份重审结论。",
              "- UNKNOWN_UNLESS_VERIFIED；as_of=2026-09-30；diagnostic_available_at=null；历史 PIT 准入数量 0。目录/抓取时钟只供审计。",
              "", "## 证据身份", ""]
    for doc in [*report["source_documents"], report["earlier_correction_notice"]["document"]]:
        lines += [f'### {doc["role"]}', "", f'- 公告 `{doc["announcement_id"]}`：[官方 PDF]({doc["url"]})。',
                  f'- {doc["page_count"]} 页；SHA-256 `{doc["sha256"]}`；绑定物理页码 {doc["evidence_pages"]}。', ""]
    lines += ["## 范围与可复现性", "", "- 已绑定原文窗口为 2023—2025 三年，2021—2022 原版依赖仍缺；2022 比较栏不补成独立原版。",
              "- 旧报告、规则、发布记录、生产快照与生产状态不变；未接入任何 Reader/premise/valuation，不输出 F1—F5。",
              "- 仅本地诊断，遵守来源条款；公开获取不自动授予共享/商用权限，不构成许可验收。",
              f'- 本证据包 logical_content_hash：`{report["logical_content_hash"]}`。',
              "- 离线重建；canonical UTF-8 JSON、排序键，无新增运行时钟；固定抓取审计时钟保留为输入身份，唯一排除自身顶层哈希字段。",
              "- 确定性不是完整性证明，Git 不备份 storage 原始证据。", ""]
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
    artifacts = {"diagnostic-only.json": base.canonical_bytes(report) + b"\n",
                 "diagnostic-only.md": render_markdown(report).encode("utf-8")}
    if args.check:
        for name, raw in artifacts.items():
            if (args.output_dir / name).read_bytes() != raw:
                raise ValueError(f"frozen 2023 diagnostic differs: {name}")
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
