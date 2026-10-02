"""One 2022 annual source and a separately bound 2023 policy bridge, never PIT.

Do not alter earlier reports/tools. All 2022 ordinary arithmetic uses the 2022
PDF's own E/N, not subsequently adjusted comparison columns. Explicit financing
lease repayment remains a component, not complete lease cash. A shareholder
inquiry supplement is not a financial-field version or a shares-ready proof.
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
from scripts.pilots import capture_financial_2022_000637 as capture
from scripts.pilots import verify_attributable_equity_000637 as equity
from scripts.pilots import verify_financial_2023_000637 as previous
from scripts.pilots import verify_financial_2024_000637 as geometry
from scripts.pilots import verify_minority_equity_000637 as minority
from turtle_quant.core.types import calculation_context, to_decimal

INPUTS = "docs/data-pilots/2026-10-02-financial-2022-000637-inputs.json"
TOOL = "scripts/pilots/verify_financial_2022_000637.py"
OUTPUT = "docs/data-pilots/financial-2022-000637-2026-10-02"
HEADER = "茂名石化实华股份有限公司2022年年度报告全文"
UNKNOWN_FIELDS = previous.UNKNOWN_FIELDS
ANNUAL_PAGES = ([120, 121, 122], [127, 128, 129], [206], 144, 170, 234, 241)
POLICY_PAGES = [86, 87, 132, 133, 134, 135, 156]
SUPPLEMENT_INTERPRETATION = "CONTROLLING_SHAREHOLDER_PLEDGE_FREEZE_NOT_ANNUAL_FINANCIAL_FIELD_VERSION"
POLICY_INTERPRETATION = "ACCOUNTING_POLICY_ADJUSTMENT_SOURCE_BRIDGE_ONLY_NOT_PIT"


def dated_asset_headers(words):
    unit = minority._one(words, "单位：元")
    first = minority._one(words, "流动资产：")
    band = [word for word in words if unit[3] < word[1] and word[3] < first[1]]
    project = minority._one(band, "项目")
    parts = [word for word in band if word[0] > project[2] and abs(geometry.centre(word) - geometry.centre(project)) <= 1]
    headers = []
    for right, expected in ((False, "2022年12月31日"), (True, "2022年1月1日")):
        column = sorted([word for word in parts if (word[0] >= 380) == right], key=lambda word: word[0])
        if len(column) != 4 or "".join(word[4] for word in column) != expected:
            raise ValueError("dated 2022 balance sheet current/opening columns changed")
        headers.append((column[0][0], column[0][1], column[-1][2], column[-1][3], expected))
    return tuple(headers)


def table_checks(rows):
    return {column: {
        "equity": geometry.reconcile([rows[name][column] for name in ("E", "N", "total_equity")], lambda e, n, t: e + n - t),
        "ocf": geometry.reconcile([rows[name][column] for name in ("inflow", "outflow", "OCF")], lambda i, o, n: i - o - n),
    } for column in ("current_cny", "prior_comparative_cny")}


def extract_tables(asset_words, cash_words):
    assets = geometry.section(asset_words, "1、合并资产负债表", "2、母公司资产负债表")
    headers = dated_asset_headers(assets)
    rows = {name: geometry.row_cells(assets, label, headers) for name, label in
            (("E", equity.E_LABEL), ("N", "少数股东权益"), ("total_equity", "所有者权益合计"))}
    cash = geometry.section(cash_words, "5、合并现金流量表", "6、母公司现金流量表")
    minority._one(cash, "单位：元")
    columns = geometry.column_headers(cash, ("2022", "2021"), annual=True)
    labels = ["一、经营活动产生的现金流量：", "经营活动现金流入小计", "经营活动现金流出小计",
              "经营活动产生的现金流量净额", "二、投资活动产生的现金流量：",
              "购建固定资产、无形资产和其他长", "期资产支付的现金",
              "投资活动产生的现金流量净额", "三、筹资活动产生的现金流量：", "支付其他与筹资活动有关的现金"]
    markers = [minority._one(cash, label) for label in labels]
    if columns[0][3] >= markers[0][1] or any(a[3] >= b[1] for a, b in zip(markers, markers[1:])):
        raise ValueError("cashflow category or consolidated row ordering changed")
    first, second = markers[5:7]
    if abs(geometry.centre(second) - geometry.centre(first) - 12) > 1 or abs(first[0] - second[0]) > 10:
        raise ValueError("split Capex payment row is not adjacent")
    for name, label in (("inflow", labels[1]), ("outflow", labels[2]), ("OCF", labels[3]), ("financing_other_total", labels[-1])):
        rows[name] = geometry.row_cells(cash, label, columns)
    rows["Capex"] = geometry.row_cells(cash, labels[5], columns, (first[1] + second[3]) / 2)
    if any(value is not None and to_decimal(value) < 0 for value in rows["Capex"].values()):
        raise ValueError("Capex payment cannot be negative")
    return {"rows": rows, "checks": table_checks(rows)}


def extract_lease_component(words, main_total):
    marker = minority._one(words, "（5）")
    heading = minority._one(words, "支付的其他与筹资活动有关的现金")
    if marker[2] >= heading[0] or abs(geometry.centre(marker) - geometry.centre(heading)) > 1:
        raise ValueError("financing note heading is not bound to subsection 5")
    section = geometry.section(words, heading[4], "支付的其他与筹资活动有关的现金说明：")
    minority._one(section, "单位：元")
    columns = geometry.column_headers(section, ("本期发生额", "上期发生额"))
    payment = geometry.row_cells(section, "偿还租赁负债支付的金额", columns)
    total = geometry.row_cells(section, "合计", columns)
    for column in payment:
        if payment[column] is not None and to_decimal(payment[column]) < 0:
            raise ValueError("lease cash payment cannot be negative")
        if total[column] != main_total[column] or (payment[column] is not None and payment[column] != total[column]):
            raise ValueError("lease note payment does not match note/main financing total")
    return {**payment, "note_total": total, "cashflow_category": "FINANCING",
            "observation_state": "EXPLICIT_COMPONENT_NOT_COMPLETE_LEASE_CASH",
            "full_lease_cash_coverage": "UNKNOWN", "principal_interest_cash_bridge": "UNKNOWN",
            "full_lease_cash_not_already_deducted": None}


def source_arithmetic(observations):
    if set(observations) != {"E", "N", "OCF", "Capex"}:
        raise ValueError("ordinary source dependencies incomplete")
    e, n, ocf, capex = (observations[key] for key in ("E", "N", "OCF", "Capex"))
    alpha = equity.calculate_source_alpha(e, n)
    if any(item.get(key) != e[key] or item.get(key) is None for item in (ocf, capex) for key in equity.JOIN_KEYS):
        raise ValueError("cross-version/security/period/scope/unit/PDF source arithmetic")
    if (any(item.get("period_start") != "2022-01-01" or item["period_end"] != "2022-12-31" for item in observations.values())
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


def extract_policy_table(words):
    # The page has three tables. Bind only the dated 2022-12-31 balance sheet,
    # not the 2022-01-01 table or the adjacent consolidated income statement.
    headings = sorted([word for word in words if word[4] == "合并资产负债表"], key=lambda word: word[1])
    end = minority._one(words, "合并利润表")
    if len(headings) != 2 or headings[1][3] >= end[1]:
        raise ValueError("policy balance sheet scope changed")
    band = [word for word in words if headings[1][3] < word[1] and word[3] < end[1]]
    month = minority._one(band, "年12")
    caption = sorted([word for word in band if 180 < word[0] < 330 and abs(word[1] - month[1]) < 4], key=lambda w: w[0])
    if len(caption) != 4 or "".join(word[4] for word in caption) != "（于2022年12月31日）":
        raise ValueError("policy bridge statement date changed")
    heading = [word for word in headings if 0 < month[1] - word[3] < 20]
    if len(heading) != 1 or max(word[3] for word in caption) >= end[1]:
        raise ValueError("policy balance sheet scope changed")
    table = [word for word in band if max(word[3] for word in caption) < word[1]]
    headers = [minority._one(table, label) for label in ("调整前", "调整后", "影响金额")]
    if any(a[2] >= b[0] or abs(geometry.centre(a) - geometry.centre(b)) > 1 for a, b in zip(headers, headers[1:])):
        raise ValueError("policy before/after/impact columns changed")
    centres = [(word[0] + word[2]) / 2 for word in headers]
    cuts = [centres[0] - 45, (centres[0] + centres[1]) / 2, (centres[1] + centres[2]) / 2, 520]
    rows = {}
    for name, label in (("deferred_tax_asset", "递延所得税资产"), ("deferred_tax_liability", "递延所得税负债"),
                        ("surplus_reserve", "盈余公积"), ("retained_earnings", "未分配利润"), ("N", "少数股东权益")):
        anchor = minority._one(table, label)
        cells = [word for word in table if abs(geometry.centre(word) - geometry.centre(anchor)) <= 1
                 and cuts[0] <= (word[0] + word[2]) / 2 < cuts[-1]]
        row = {}
        for left, right, key in zip(cuts, cuts[1:], ("before_cny", "after_cny", "observed_impact_cny")):
            selected = [word for word in cells if left <= (word[0] + word[2]) / 2 < right]
            if len(selected) > 1:
                raise ValueError("duplicate policy money cell")
            row[key] = minority.parse_money_cell(selected[0][4]) if selected else None
        rows[name] = row
    return {"rows": rows, "checks": policy_checks(rows)}


def policy_checks(rows):
    return {name: geometry.reconcile([row[key] for key in ("after_cny", "before_cny", "observed_impact_cny")],
                                    lambda after, before, impact: after - before - impact) for name, row in rows.items()}


def policy_bridge_arithmetic(rows_2022, opening_2023, policy_rows):
    result = {}
    with calculation_context():
        for field, source_field in (("E", "retained_earnings"), ("N", "N")):
            before = rows_2022[field]["current_cny"]
            after = opening_2023[field]
            impact = policy_rows[source_field]["observed_impact_cny"]
            check = geometry.reconcile([after, before, impact], lambda a, b, i: a - b - i)
            result[field] = {"original_2022_cny": before, "later_2023_opening_cny": after,
                             "policy_observed_component_cny": impact,
                             "difference_cny": None if before is None or after is None else format(to_decimal(after) - to_decimal(before), "f"),
                             "check": check}
        n = policy_rows["N"]
        if n["before_cny"] != result["N"]["original_2022_cny"] or n["after_cny"] != result["N"]["later_2023_opening_cny"]:
            raise ValueError("policy minority row is not bound to source/comparison versions")
    return result


def fixed_scope(scope):
    required = {"schema_version": "financial_2022_000637_scope_v1", "security_id": "sz.000637",
                "issuer": "茂名石化实华股份有限公司", "as_of": "2026-09-30", "review_date": "2026-10-02",
                "period_start": "2022-01-01", "period_end": "2022-12-31", "statement_scope": "CONSOLIDATED", "unit": "CNY",
                "diagnostic_only": True, "official_selection": False, "timing_policy": "UNKNOWN_UNLESS_VERIFIED"}
    if any(type(scope.get(key)) is not type(value) or scope[key] != value for key, value in required.items()):
        raise ValueError("fixed 2022 diagnostic scope changed")
    annual = scope["annual"]
    if ((annual["role"], annual["announcement_id"]) != capture.ANNUAL[:2]
            or tuple(annual[key] for key in ("asset_pages", "cashflow_pages", "lease_note_pages", "currency_page",
                                           "consolidated_notes_page", "parent_notes_page", "page_count")) != ANNUAL_PAGES):
        raise ValueError("fixed annual identity or physical page bridge changed")
    supplement, policy = scope["inquiry_supplement"], scope["policy_bridge"]
    if (supplement["announcement_id"] != capture.SUPPLEMENT[1] or supplement["page_count"] != 2
            or supplement["evidence_pages"] != [1, 2] or supplement["interpretation"] != SUPPLEMENT_INTERPRETATION):
        raise ValueError("inquiry supplement is not an annual financial-field version")
    if (policy["source_2023_document_role"] != previous.capture.TARGETS[0][0] or policy["announcement_id"] != "1221364107"
            or policy["page_count"] != 258 or policy["evidence_pages"] != POLICY_PAGES
            or (policy["reason_page"], policy["table_page"], policy["currency_page"]) != (86, 87, 156)
            or policy["statement_date"] != "2022-12-31" or policy["interpretation"] != POLICY_INTERPRETATION):
        raise ValueError("later policy bridge scope changed")


def build_review(root=ROOT, render_dir=None):
    import fitz

    root = Path(root).resolve()
    scope_raw = (root / INPUTS).read_bytes()
    scope = base._json(scope_raw)
    fixed_scope(scope)
    base.verified_bytes(root, "RULE_SPEC.md", geometry.RULE_HASH)
    old = scope["previous_2023_review"]
    old_report = base._json(base.verified_bytes(root, old["path"], old["sha256"]))
    previous.validate_review(old_report)
    if old_report["logical_content_hash"] != old["logical_content_hash"]:
        raise ValueError("previous frozen diagnostic identity changed")
    audit = base._json(base.verified_bytes(root, scope["capture"]["path"], scope["capture"]["sha256"]))
    if (audit["schema_version"] != "financial_2022_000637_capture_v1" or audit["security_id"] != "sz.000637"
            or audit["target_period_end"] != "2022-12-31" or len(audit["resources"]) != 5
            or len(audit["documents"]) != 2 or len(audit["catalogues"]) != 3 or audit["exact_available_at_utc"] is not None
            or any(audit[key] is not False for key in ("complete_revision_chain_verified", "snapshot_published", "production_reader_ready", "research_eligible"))):
        raise ValueError("capture scope or authority changed")
    resources = {item["name"]: item for item in audit["resources"]}
    if len(resources) != 5:
        raise ValueError("duplicate raw resource identity")
    parsed = []
    for number, (query, item) in enumerate(zip(capture.QUERIES, audit["catalogues"]), 1):
        resource = resources[item["resource"]]
        raw = base.verified_bytes(root, resource["local_path"], resource["sha256"])
        if (item["resource"] != f"catalogue-{number}.json" or resource["method"] != "POST"
                or resource["url"] != capture.ENDPOINT or resource["request_data"] != {**capture.PAYLOAD, "searchkey": query}
                or item["searchkey"] != query or resource["bytes"] != len(raw)
                or item["completeness_scope"] != "FILTERED_CURRENT_RESPONSE_ONLY" or item["empty_result_proves_no_withdrawal"] is not False):
            raise ValueError("catalogue request or coverage binding changed")
        rows = capture.previous.parse_catalogue(raw)
        if len(rows) != item["reported_total"] or list(rows) != item["announcement_ids"]:
            raise ValueError("catalogue audit disagrees with raw response")
        parsed.append(rows)
    found = capture.merge_catalogues(parsed)

    def document(recorded, target, plan, pages):
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
        return raw, {"role": role, "announcement_id": identifier, "url": url, "path": resource["local_path"],
                     "sha256": plan["pdf_sha256"], "page_count": plan["page_count"], "evidence_pages": sorted(pages),
                     "catalogue_title": title, "catalogue_time_raw_ms": recorded["catalogue_time_raw_ms"], "exact_available_at_utc": None}

    def pdf_pages(raw, doc, header):
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            if len(pdf) != doc["page_count"]:
                raise ValueError("PDF page count mismatch")
            texts, words = {}, {}
            for page in doc["evidence_pages"]:
                texts[page] = "".join(pdf[page - 1].get_text().split())
                words[page] = pdf[page - 1].get_text("words")
                if header is not None and (header not in texts[page] or not 595 <= pdf[page - 1].rect.width <= 596):
                    raise ValueError("annual issuer, year or page geometry changed")
            if render_dir is not None:
                output = Path(render_dir) / doc["role"]
                output.mkdir(parents=True, exist_ok=False)
                for page in doc["evidence_pages"]:
                    pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f"physical-{page}.png")
        return texts, words

    def combined(words, pages):
        return [(*word[:1], word[1] + index * 1000, word[2], word[3] + index * 1000, *word[4:])
                for index, page in enumerate(pages) for word in words[page]]

    plan = scope["annual"]
    pages = sorted(set(plan["asset_pages"] + plan["cashflow_pages"] + plan["lease_note_pages"] +
                       [plan[key] for key in ("currency_page", "consolidated_notes_page", "parent_notes_page")]))
    raw, annual_doc = document(audit["documents"][0], capture.ANNUAL, plan, pages)
    texts, words = pdf_pages(raw, annual_doc, HEADER)
    if ("本集团及境内子公司以人民币为记账本位币" not in texts[plan["currency_page"]]
            or "七、合并财务报表项目注释" not in texts[plan["consolidated_notes_page"]]
            or "母公司财务报表主要项目注释" not in texts[plan["parent_notes_page"]]
            or not plan["consolidated_notes_page"] < plan["lease_note_pages"][0] < plan["parent_notes_page"]):
        raise ValueError("currency or consolidated note boundary changed")
    tables = extract_tables(combined(words, plan["asset_pages"]), combined(words, plan["cashflow_pages"]))
    component = extract_lease_component(combined(words, plan["lease_note_pages"]), tables["rows"]["financing_other_total"])
    for field, expected in plan["expected"].items():
        actual = component["current_cny"] if field == "lease_financing_component" else tables["rows"][field]["current_cny"]
        if actual != expected:
            raise ValueError(f"source value disagrees with frozen scope: {field}")
    observations = {}
    for name, field in (("E", "attributable_equity"), ("N", "minority_interest"), ("OCF", "operating_cash_flow"), ("Capex", "capex_cash_paid")):
        field_pages = plan["asset_pages"] if name in ("E", "N") else plan["cashflow_pages"]
        observations[name] = {"field": field, "security_id": "sz.000637", "period_start": "2022-01-01", "period_end": "2022-12-31",
                              "statement_scope": "CONSOLIDATED", "unit": "CNY", "version": plan["role"],
                              "document_sha256": annual_doc["sha256"], "observed_value": tables["rows"][name]["current_cny"],
                              "evidence_refs": [base._ref(annual_doc, page) for page in field_pages],
                              "diagnostic_available_at": None, "historical_pit_status": "UNKNOWN"}
    component["evidence_refs"] = [base._ref(annual_doc, page) for page in plan["lease_note_pages"]]
    bundle = {"version": plan["role"], "observations": observations, "tables": tables, "ordinary_source_arithmetic": source_arithmetic(observations),
              "lease_financing_component": component, "pit_and_standard_outputs": {key: None for key in UNKNOWN_FIELDS}}

    supplement_plan = scope["inquiry_supplement"]
    raw, supplement_doc = document(audit["documents"][1], capture.SUPPLEMENT, supplement_plan, supplement_plan["evidence_pages"])
    texts, _ = pdf_pages(raw, supplement_doc, None)
    if ("证券代码：000637" not in texts[1] or "茂名石化实华股份有限公司" not in texts[1]
            or "控股股东股权被质押、冻结情况" not in texts[1] or "2023-047" not in texts[1]
            or "除以上补充公告内容外" not in texts[2] or "没有变化" not in texts[2]):
        raise ValueError("inquiry supplement object or boundary changed")

    policy_plan = scope["policy_bridge"]
    original_2023 = old_report["source_documents"][0]
    if (original_2023["role"] != policy_plan["source_2023_document_role"] or original_2023["announcement_id"] != policy_plan["announcement_id"]
            or original_2023["sha256"] != policy_plan["pdf_sha256"] or original_2023["page_count"] != policy_plan["page_count"]):
        raise ValueError("policy bridge PDF differs from frozen 2023 source")
    policy_doc = {**original_2023, "role": "frozen_2023_original_for_policy_bridge", "evidence_pages": POLICY_PAGES}
    raw = base.verified_bytes(root, policy_doc["path"], policy_doc["sha256"])
    texts, words = pdf_pages(raw, policy_doc, previous.HEADER)
    if ("会计政策变更" not in texts[86] or "企业会计准则解释第16号" not in texts[86]
            or "本集团自2023年1月1日起适用该规定" not in texts[86]
            or "本集团以人民币为记账本位币" not in texts[156]):
        raise ValueError("policy adjustment reason or currency changed")
    policy_table = extract_policy_table(words[87])
    for name, expected in policy_plan["expected_impacts"].items():
        if policy_table["rows"][name]["observed_impact_cny"] != expected:
            raise ValueError("policy impact disagrees with fixed source scope")
    opening = {name: old_report["version_bundles"][0]["tables"]["rows"][name]["prior_comparative_cny"] for name in ("E", "N")}
    check_2023 = previous.extract_tables(combined(words, previous.PAGE_BINDINGS[0][0]),
                                      # Cashflow pages are independently bound by the frozen prior report.
                                      _cash_words_from_previous(root, original_2023))
    if any(check_2023["rows"][name]["prior_comparative_cny"] != value for name, value in opening.items()):
        raise ValueError("later opening comparison differs from frozen original 2023")
    bridge = {"document": policy_doc, "interpretation": POLICY_INTERPRETATION, "statement_date": "2022-12-31",
              "policy_name": "企业会计准则解释第16号", "tables": policy_table, "later_2023_opening": opening,
              "source_bridge_arithmetic": policy_bridge_arithmetic(tables["rows"], opening, policy_table["rows"]),
              "evidence_refs": [base._ref(policy_doc, page) for page in (86, 87)],
              "used_to_replace_2022_source": False, "diagnostic_available_at": None, "historical_pit_status": "UNKNOWN"}
    code_paths = sorted(set(old_report["manifest"]["code_hashes"]) | {TOOL, "scripts/pilots/capture_financial_2022_000637.py"})
    report = {"schema_version": "financial_2022_000637_diagnostic_v1", "title": "茂化实华 2022 年原文窗口扩展诊断",
              "security_id": "sz.000637", "as_of": "2026-09-30", "review_date": "2026-10-02", "period_start": "2022-01-01", "period_end": "2022-12-31",
              "diagnostic_only": True, "official_selection": False, "production_reader_ready": False,
              "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "diagnostic_available_at": None, "historical_pit_observations_admitted": 0,
              "complete_revision_chain_verified": False, "full_amended_audit_status": "UNKNOWN",
              "source_documents": [annual_doc], "version_bundles": [bundle], "policy_bridge": bridge,
              "inquiry_supplement": {"document": supplement_doc, "interpretation": SUPPLEMENT_INTERPRETATION,
                                     "used_as_annual_field_version": False, "audit_gate_conclusion": "UNKNOWN", "shares_reader_ready_proof": False},
              "catalogue_queries": audit["catalogues"], "current_catalogue_rows": [found[key] for key in sorted(found)],
              "remaining_gaps": ["complete_lease_cash_and_overlap", "verified_available_at", "latest_visible_version",
                                 "complete_revision_withdrawal_chain", "full_amended_audit_status", "2021_original_window"],
              "not_claimed": ["不是官方 Top-N、真实选股、真实 PIT 规则运行、可发布回测或投资建议。",
                              "不生成排名、权重、订单、持仓、净值或 F1—F5，不改变生产状态。",
                              "目录单一全文命中不证明历史无更正/无撤回；目录/抓取日不证明最早可用。",
                              "2023 政策调整仅跨年原文桥接，不回填 2022 原版，不替代同版 E/N，不选最新可见版。"],
              "manifest": {"rule_version": "v1.3.2", "rule_sha256": geometry.RULE_HASH,
                           "scope": {"path": INPUTS, "sha256": hashlib.sha256(scope_raw).hexdigest()}, "capture": scope["capture"],
                           "previous_2023_review": old, "raw_resources": audit["resources"],
                           "code_hashes": {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in code_paths}}}
    report["logical_content_hash"] = base.logical_content_hash(report)
    validate_review(report)
    return report


def _cash_words_from_previous(root, doc):
    import fitz
    with fitz.open(stream=base.verified_bytes(root, doc["path"], doc["sha256"]), filetype="pdf") as pdf:
        return [(*word[:1], word[1] + i * 1000, word[2], word[3] + i * 1000, *word[4:])
                for i, page in enumerate(previous.PAGE_BINDINGS[0][1]) for word in pdf[page - 1].get_text("words")]


def _validate_doc(doc, target, count, pages):
    if (doc["role"] != target[0] or doc["announcement_id"] != target[1] or doc["catalogue_title"] != target[3]
            or doc["url"] != f"https://static.cninfo.com.cn/finalpage/{target[2]}/{target[1]}.PDF"
            or type(doc["page_count"]) is not int or doc["page_count"] != count or doc["evidence_pages"] != sorted(pages)
            or type(doc["catalogue_time_raw_ms"]) is not int or doc["exact_available_at_utc"] is not None):
        raise ValueError("source document identity, pages or availability changed")


def validate_review(report):
    if (report["schema_version"] != "financial_2022_000637_diagnostic_v1" or report["security_id"] != "sz.000637"
            or (report["period_start"], report["period_end"], report["as_of"], report["review_date"]) != ("2022-01-01", "2022-12-31", "2026-09-30", "2026-10-02")
            or report["logical_content_hash"] != base.logical_content_hash(report) or report["diagnostic_only"] is not True
            or report["official_selection"] is not False or report["production_reader_ready"] is not False
            or report["diagnostic_available_at"] is not None or report["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED"
            or type(report["historical_pit_observations_admitted"]) is not int or report["historical_pit_observations_admitted"] != 0
            or report["complete_revision_chain_verified"] is not False or report["full_amended_audit_status"] != "UNKNOWN"
            or report["manifest"]["rule_version"] != "v1.3.2" or report["manifest"]["rule_sha256"] != geometry.RULE_HASH):
        raise ValueError("diagnostic identity, timing or authority changed")
    if len(report["version_bundles"]) != 1 or len(report["source_documents"]) != 1:
        raise ValueError("exactly one independently captured 2022 annual version required")
    doc, bundle = report["source_documents"][0], report["version_bundles"][0]
    pages = sorted(set(ANNUAL_PAGES[0] + ANNUAL_PAGES[1] + ANNUAL_PAGES[2] + list(ANNUAL_PAGES[3:6])))
    _validate_doc(doc, capture.ANNUAL, 241, pages)
    if (bundle["version"] != capture.ANNUAL[0] or bundle["pit_and_standard_outputs"] != {key: None for key in UNKNOWN_FIELDS}
            or bundle["ordinary_source_arithmetic"] != source_arithmetic(bundle["observations"])
            or bundle["tables"]["checks"] != table_checks(bundle["tables"]["rows"])):
        raise ValueError("source arithmetic or PIT boundary changed")
    for name, item in bundle["observations"].items():
        if (item["security_id"] != "sz.000637" or item["version"] != bundle["version"] or item["document_sha256"] != doc["sha256"]
                or item["diagnostic_available_at"] is not None or item["historical_pit_status"] != "UNKNOWN"
                or item["evidence_refs"] != [base._ref(doc, page) for page in ANNUAL_PAGES[0 if name in ("E", "N") else 1]]
                or item["observed_value"] != bundle["tables"]["rows"][name]["current_cny"]):
            raise ValueError("field version, source value or evidence changed")
    component = bundle["lease_financing_component"]
    if (set(component) != {"current_cny", "prior_comparative_cny", "note_total", "cashflow_category", "observation_state",
                          "full_lease_cash_coverage", "principal_interest_cash_bridge", "full_lease_cash_not_already_deducted", "evidence_refs"}
            or component["cashflow_category"] != "FINANCING" or component["observation_state"] != "EXPLICIT_COMPONENT_NOT_COMPLETE_LEASE_CASH"
            or component["full_lease_cash_coverage"] != "UNKNOWN" or component["principal_interest_cash_bridge"] != "UNKNOWN"
            or component["full_lease_cash_not_already_deducted"] is not None
            or component["note_total"] != bundle["tables"]["rows"]["financing_other_total"]
            or component["evidence_refs"] != [base._ref(doc, page) for page in ANNUAL_PAGES[2]]):
        raise ValueError("incomplete lease cash promoted or evidence changed")
    for column in ("current_cny", "prior_comparative_cny"):
        if component[column] is not None and (to_decimal(component[column]) < 0 or component[column] != component["note_total"][column]):
            raise ValueError("lease cash payment inconsistent with source")
    supplement = report["inquiry_supplement"]
    _validate_doc(supplement["document"], capture.SUPPLEMENT, 2, [1, 2])
    if (supplement["interpretation"] != SUPPLEMENT_INTERPRETATION or supplement["used_as_annual_field_version"] is not False
            or supplement["audit_gate_conclusion"] != "UNKNOWN" or supplement["shares_reader_ready_proof"] is not False):
        raise ValueError("shareholder supplement promoted to financial version/audit/shares proof")
    policy = report["policy_bridge"]
    policy_target = ("frozen_2023_original_for_policy_bridge", *previous.capture.TARGETS[0][1:])
    _validate_doc(policy["document"], policy_target, 258, POLICY_PAGES)
    policy_rows = policy["tables"]["rows"]
    if (policy["interpretation"] != POLICY_INTERPRETATION or policy["statement_date"] != "2022-12-31"
            or policy["policy_name"] != "企业会计准则解释第16号" or policy["used_to_replace_2022_source"] is not False
            or policy["diagnostic_available_at"] is not None or policy["historical_pit_status"] != "UNKNOWN"
            or set(policy_rows) != {"deferred_tax_asset", "deferred_tax_liability", "surplus_reserve", "retained_earnings", "N"}
            or set(policy["later_2023_opening"]) != {"E", "N"} or policy_rows["surplus_reserve"]["observed_impact_cny"] is not None
            or policy["evidence_refs"] != [base._ref(policy["document"], page) for page in (86, 87)]
            or policy["tables"]["checks"] != policy_checks(policy["tables"]["rows"])
            or policy["source_bridge_arithmetic"] != policy_bridge_arithmetic(bundle["tables"]["rows"], policy["later_2023_opening"], policy["tables"]["rows"])):
        raise ValueError("later accounting policy bridge changed or replaced original 2022")
    if (len(report["catalogue_queries"]) != 3 or any(query["searchkey"] != expected
            or query["completeness_scope"] != "FILTERED_CURRENT_RESPONSE_ONLY" or query["empty_result_proves_no_withdrawal"] is not False
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
    bundle = report["version_bundles"][0]
    lines = [f'# {report["title"]}', "", "## 本报告不宣称", ""]
    lines += [f"- {item}" for item in report["not_claimed"]]
    lines += ["", "## 独立 2022 原版（元）", "", "| 字段 | 原文数值 |", "|---|---:|"]
    lines += [f'| {name} | {bundle["observations"][name]["observed_value"]} |' for name in ("E", "N", "OCF", "Capex")]
    lines += [f'| alpha_observed（无量纲） | {bundle["ordinary_source_arithmetic"]["alpha_observed"]} |',
              f'| OCF−Capex | {bundle["ordinary_source_arithmetic"]["ocf_minus_capex_cny"]} |',
              f'| 普通口径原文算术 | {bundle["ordinary_source_arithmetic"]["FCF_ordinary_source_arithmetic_cny"]} |', "",
              "- 合并资产负债表物理 120—122 页，列头 2022-12-31/2022-01-01；合并现金流 127—129 页，列头 2022/2021 年度。母公司表在 122/129 页下方，不混入。",
              "- 现金附注 206 页筹资租赁偿还现金为 14537724.60 元，比较栏 12134633.45 元；与同版附注合计和主表两列一致。只是明确部分，完整 Lease_cash、保守/标准 FCF 仍 UNKNOWN。",
              "", "## 跨年政策调整原文桥接", "", "| 字段 | 2022 原版期末 | 2023 原版期初比较 | 差额 |", "|---|---:|---:|---:|"]
    for field, row in report["policy_bridge"]["source_bridge_arithmetic"].items():
        lines.append(f'| {field} | {row["original_2022_cny"]} | {row["later_2023_opening_cny"]} | {row["difference_cny"]} |')
    lines += ["", "- 固定 2023 原版物理 86—87 页明确解释第 16 号会计政策变更；未分配利润影响 1966829.87 元，少数股东权益影响 -104.66 元，与 E/N 差额对平。",
              "- 该页盈余公积影响栏空白，保留 null，不能因前后金额相同反推为显式零观察。桥接仅为原文比较，不回填 2022，也不证明历史最新/PIT 版本或完整五年输入兼容。",
              "", "## 目录、补充公告与时点", "",
              "- 三次标题查询限定 2023-01-01 至 2026-10-02，返回 3/23/0 行；当前过滤响应中仅一个独立 2022 全文，不证明历史无其他版本。摘要和年报问询补充不是完整年报。",
              "- 问询补充 1217202489 物理 1—2 页仅涉及控股股东质押/冻结及解决措施，不作年报财务科目版本、审计结论或股本域 ready 证明。",
              "- UNKNOWN_UNLESS_VERIFIED；as_of=2026-09-30；diagnostic_available_at=null；历史 PIT 准入 0。目录/封面/抓取时间不能倒填最早公众可用。",
              "- 已绑定 2022—2025 四年原文，2021 原版仍缺。全部租赁现金与去重、可用时点、完整修订链和更正后整份审计状态仍缺，不生成 F1—F5。",
              "", "## 证据身份", ""]
    for doc in [report["source_documents"][0], report["inquiry_supplement"]["document"], report["policy_bridge"]["document"]]:
        lines += [f'### {doc["role"]}', "", f'- 公告 `{doc["announcement_id"]}`：[官方 PDF]({doc["url"]})。',
                  f'- {doc["page_count"]} 页；SHA-256 `{doc["sha256"]}`；绑定物理页码 {doc["evidence_pages"]}。', ""]
    lines += ["## 可复现性与状态", "",
              "- canonical UTF-8 JSON、排序键，无新增运行时钟；保留固定抓取时钟作为输入身份，唯一排除自身顶层哈希字段。离线核验原始 bytes、公告身份、物理边界和旧诊断，不覆盖已有证据文件。",
              f'- 本包 logical_content_hash：`{report["logical_content_hash"]}`。',
              "- 旧证据、工具、规则、发布记录与生产快照不改写，九域及真实策略编排仍 not_ready。确定性不证明输入完整。",
              "- 仅本地诊断，遵守来源条款；公开可获取不自动授予共享/商用权利，不构成许可验收。Git 不备份 storage 原文。", ""]
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
                raise ValueError(f"frozen 2022 diagnostic differs: {name}")
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
