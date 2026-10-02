"""Offline 2024 source-window extension; never a historical PIT strategy run.

Two annual PDFs are parsed independently with fixed physical page boundaries.
2023 comparative cells are corroboration, not original 2023 publications.
Only ordinary source arithmetic is computed; partial lease cash stays partial.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import capture_financial_2024_000637 as capture
from scripts.pilots import verify_attributable_equity_000637 as equity
from scripts.pilots import verify_minority_equity_000637 as minority
from scripts.pilots import verify_lease_cash_000637 as lease
from turtle_quant.core.types import calculation_context, to_decimal

INPUTS = "docs/data-pilots/2026-10-02-financial-2024-000637-inputs.json"
TOOL = "scripts/pilots/verify_financial_2024_000637.py"
OUTPUT = "docs/data-pilots/financial-2024-000637-2026-10-02"
RULE_HASH = "db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812"
ISSUER_HEADER = "茂名石化实华股份有限公司2024年年度报告全文"
UNKNOWN_FIELDS = ("E_pit", "N_pit", "OCF_pit", "Capex_pit", "alpha_pit",
                  "FCF_ordinary_pit", "Lease_cash_not_already_deducted", "Lease_cash_pit",
                  "FCF_conservative", "FCF")
PAGE_BINDINGS = (
    ([113, 114, 115, 116], [121, 122], 208, 138, 169, 231, 240),
    ([115, 116, 117, 118], [123, 124, 125], 226, 141, 185, 251, 260),
)


def centre(word):
    return (word[1] + word[3]) / 2


def section(words, start_label, end_label):
    start, end = (minority._one(words, name) for name in (start_label, end_label))
    if start[3] >= end[1]:
        raise ValueError("consolidated section boundary reversed")
    return [word for word in words if start[3] < word[1] and word[3] < end[1]]


def column_headers(words, names, annual=False):
    current, prior = (minority._one(words, name) for name in names)
    if current[0] >= prior[0] or abs(centre(current) - centre(prior)) > 1:
        raise ValueError("current/prior column order or alignment drift")
    if annual:
        for header in (current, prior):
            matches = [word for word in words if word[4] == "年度"
                       and abs(centre(word) - centre(header)) <= 1
                       and 0 <= word[0] - header[2] <= 5]
            if len(matches) != 1:
                raise ValueError("year not bound to annual column")
    return current, prior


def row_cells(words, label, headers, row_y=None):
    target = minority._one(words, label)
    current, prior = headers
    if target[2] >= current[0] - 45:
        raise ValueError("source label overlaps amount columns")
    y = centre(target) if row_y is None else row_y
    split = (current[0] + current[2] + prior[0] + prior[2]) / 4
    cells = [word for word in words if abs(centre(word) - y) <= 1
             and word[0] >= current[0] - 45]
    columns = [[word for word in cells if (word[0] + word[2]) / 2 < split],
               [word for word in cells if (word[0] + word[2]) / 2 >= split]]
    if any(len(column) > 1 for column in columns):
        raise ValueError("ambiguous source currency cell")
    result = {}
    for name, column in zip(("current_cny", "prior_comparative_cny"), columns):
        if column and not 230 <= column[0][0] < column[0][2] <= 540:
            raise ValueError("source amount outside fixed page column")
        result[name] = minority.parse_money_cell(column[0][4] if column else None)
    return result


def reconcile(values, formula):
    if any(value is None for value in values):
        return {"difference_cny": None, "status": "UNKNOWN"}
    with calculation_context():
        difference = formula(*map(to_decimal, values))
    if difference != 0:
        raise ValueError("source subtotal does not reconcile")
    return {"difference_cny": format(difference, "f"), "status": "RECONCILED"}


def check_tables(rows):
    checks = {}
    for column in ("current_cny", "prior_comparative_cny"):
        checks[column] = {
            "equity": reconcile([rows[name][column] for name in ("E", "N", "total_equity")],
                                lambda e, n, total: e + n - total),
            "ocf": reconcile([rows[name][column] for name in ("inflow", "outflow", "OCF")],
                              lambda incoming, outgoing, net: incoming - outgoing - net),
            "financing": reconcile([rows[name][column] for name in
                                    ("lease_financing_component", "related_borrowing_payment", "financing_note_total")],
                                    lambda cash, borrowing, total: cash + borrowing - total),
        }
        if rows["financing_note_total"][column] != rows["financing_other_total"][column]:
            raise ValueError("financing note total differs from consolidated cashflow")
    return checks


def extract_tables(asset_words, cash_words, note_words):
    assets = section(asset_words, "1、合并资产负债表", "2、母公司资产负债表")
    minority._one(assets, "单位：元")
    h = column_headers(assets, ("期末余额", "期初余额"))
    rows = {name: row_cells(assets, label, h) for name, label in (
        ("E", equity.E_LABEL), ("N", "少数股东权益"), ("total_equity", "所有者权益合计"))}
    cash = section(cash_words, "5、合并现金流量表", "6、母公司现金流量表")
    minority._one(cash, "单位：元")
    c = column_headers(cash, ("2024", "2023"), annual=True)
    # A cross-page ordering check separates operating/investing/financing rows.
    labels = ["一、经营活动产生的现金流量：", "经营活动现金流入小计", "经营活动现金流出小计",
              "经营活动产生的现金流量净额", "二、投资活动产生的现金流量：",
              "购建固定资产、无形资产和其他长", "期资产支付的现金",
              "投资活动产生的现金流量净额", "三、筹资活动产生的现金流量：",
              "支付其他与筹资活动有关的现金"]
    markers = [minority._one(cash, label) for label in labels]
    if not c[0][3] < markers[0][1] or any(left[3] >= right[1] for left, right in zip(markers, markers[1:])):
        raise ValueError("cashflow field outside approved consolidated category")
    first, second = markers[5:7]
    if abs(centre(second) - centre(first) - 12) > 1 or abs(first[0] - second[0]) > 10:
        raise ValueError("Capex payment label is not an adjacent two-line row")
    for name, label in (("inflow", labels[1]), ("outflow", labels[2]), ("OCF", labels[3]),
                        ("financing_other_total", labels[-1])):
        rows[name] = row_cells(cash, label, c)
    rows["Capex"] = row_cells(cash, labels[5], c, (first[1] + second[3]) / 2)
    note = section(note_words, "支付的其他与筹资活动有关的现金", "支付的其他与筹资活动有关的现金说明：")
    # The note is explicitly under the financing subsection (not investing).
    compact = "".join(word[4] for word in sorted(note_words, key=lambda w: (w[1], w[0])))
    if "与筹资活动有关的现金" not in compact:
        raise ValueError("lease payment financing note heading missing")
    financing_heading = minority._one(note_words, "与筹资活动有关的现金") if any(
        w[4] == "与筹资活动有关的现金" for w in note_words
    ) else minority._one(note_words, "（3）与筹资活动有关的现金")
    if financing_heading[3] >= minority._one(note_words, "支付的其他与筹资活动有关的现金")[1]:
        raise ValueError("lease note is outside financing section")
    minority._one(note, "单位：元")
    n = column_headers(note, ("本期发生额", "上期发生额"))
    rows["lease_financing_component"] = row_cells(note, "偿还租赁负债支付的金额", n)
    rows["related_borrowing_payment"] = row_cells(note, "归还关联方资金拆借款", n)
    rows["financing_note_total"] = row_cells(note, "合计", n)
    for name in ("Capex", "lease_financing_component", "related_borrowing_payment", "financing_note_total"):
        if any(value is not None and to_decimal(value) < 0 for value in rows[name].values()):
            raise ValueError("cash payment cannot be negative")
    return {"rows": rows, "checks": check_tables(rows)}


def source_arithmetic(observations):
    if set(observations) != {"E", "N", "OCF", "Capex"}:
        raise ValueError("ordinary source dependencies incomplete")
    e, n, ocf, capex = (observations[name] for name in ("E", "N", "OCF", "Capex"))
    alpha = equity.calculate_source_alpha(e, n)
    for item in (ocf, capex):
        if (any(item.get(key) != e[key] or item.get(key) is None for key in equity.JOIN_KEYS)
                or item.get("period_start") != "2024-01-01" or item["period_end"] != "2024-12-31"):
            raise ValueError("cashflow/equity source identities or annual period differ")
    if ocf["field"] != "operating_cash_flow" or capex["field"] != "capex_cash_paid":
        raise ValueError("source cashflow field identity mismatch")
    result = {"alpha_observed": alpha["alpha_observed"], "ocf_minus_capex_cny": None,
              "FCF_ordinary_source_arithmetic_cny": None, "status": "UNKNOWN"}
    if capex["observed_value"] is not None and to_decimal(capex["observed_value"]) < 0:
        raise ValueError("Capex cannot be negative")
    if any(x["observed_value"] is None for x in (ocf, capex)) or alpha["alpha_observed"] is None:
        return result
    with calculation_context():
        difference = to_decimal(ocf["observed_value"]) - to_decimal(capex["observed_value"])
        result.update(ocf_minus_capex_cny=format(difference, "f"),
                      FCF_ordinary_source_arithmetic_cny=format(difference * to_decimal(alpha["alpha_observed"]), "f"),
                      status="SOURCE_ARITHMETIC_ONLY_NOT_PIT")
    return result


def fixed_scope(scope):
    required = {"schema_version": "financial_2024_000637_scope_v1", "security_id": "sz.000637",
                "issuer": "茂名石化实华股份有限公司", "as_of": "2026-09-30", "review_date": "2026-10-02",
                "period_start": "2024-01-01", "period_end": "2024-12-31", "statement_scope": "CONSOLIDATED",
                "unit": "CNY", "diagnostic_only": True, "official_selection": False,
                "timing_policy": "UNKNOWN_UNLESS_VERIFIED"}
    if any(type(scope.get(key)) is not type(value) or scope[key] != value for key, value in required.items()):
        raise ValueError("fixed 2024 diagnostic scope changed")
    docs = scope.get("documents", [])
    if len(docs) != 2:
        raise ValueError("exactly two approved annual documents required")
    for doc, target, pages in zip(docs, capture.TARGETS, PAGE_BINDINGS):
        if ((doc["role"], doc["announcement_id"]) != target[:2]
                or tuple(doc[key] for key in ("asset_pages", "cashflow_pages", "lease_note_page", "currency_page",
                                             "consolidated_notes_page", "parent_notes_page", "page_count")) != pages):
            raise ValueError("fixed document identity or physical page boundary changed")


def build_review(root=ROOT, render_dir=None):
    import fitz

    root = Path(root).resolve()
    scope_raw = (root / INPUTS).read_bytes()
    scope = base._json(scope_raw)
    fixed_scope(scope)
    base.verified_bytes(root, "RULE_SPEC.md", RULE_HASH)
    old = scope["previous_2025_lease_review"]
    old_report = base._json(base.verified_bytes(root, old["path"], old["sha256"]))
    lease.validate_review(old_report)
    if old_report["logical_content_hash"] != old["logical_content_hash"]:
        raise ValueError("previous immutable diagnostic identity changed")
    audit = base._json(base.verified_bytes(root, scope["capture"]["path"], scope["capture"]["sha256"]))
    if (audit["schema_version"] != "financial_2024_000637_capture_v1" or audit["security_id"] != scope["security_id"]
            or audit["target_period_end"] != scope["period_end"] or len(audit["resources"]) != 5
            or len(audit["catalogues"]) != 3 or len(audit["documents"]) != 2
            or any(audit[key] is not False for key in ("complete_revision_chain_verified", "snapshot_published",
                                                      "production_reader_ready", "research_eligible"))
            or audit["exact_available_at_utc"] is not None):
        raise ValueError("capture identity or authority boundary changed")
    resources = {row["name"]: row for row in audit["resources"]}
    if len(resources) != 5:
        raise ValueError("duplicate raw resource identity")
    parsed = []
    for number, (query, item) in enumerate(zip(capture.QUERIES, audit["catalogues"]), 1):
        resource = resources[item["resource"]]
        raw = base.verified_bytes(root, resource["local_path"], resource["sha256"])
        if (item["resource"] != f"catalogue-{number}.json" or resource["method"] != "POST"
                or resource["url"] != capture.ENDPOINT or item["searchkey"] != query
                or resource["request_data"] != {**capture.PAYLOAD, "searchkey": query}
                or len(raw) != resource["bytes"] or item["completeness_scope"] != "FILTERED_CURRENT_RESPONSE_ONLY"
                or item["empty_result_proves_no_withdrawal"] is not False):
            raise ValueError("bounded catalogue request binding changed")
        rows = capture.parse_catalogue(raw)
        if len(rows) != item["reported_total"] or list(rows) != item["announcement_ids"]:
            raise ValueError("raw catalogue inventory differs from audit")
        parsed.append(rows)
    found = capture.merge_catalogues(parsed)
    documents, bundles = [], []
    for doc, target, recorded in zip(scope["documents"], capture.TARGETS, audit["documents"]):
        role, identifier, day, title = target
        resource = resources[recorded["resource"]]
        url = f"https://static.cninfo.com.cn/finalpage/{day}/{identifier}.PDF"
        if (resource["method"] != "GET" or resource["url"] != url or resource["request_data"] is not None
                or resource["sha256"] != doc["pdf_sha256"] or recorded["role"] != role
                or recorded["announcement_id"] != identifier or recorded["catalogue_title"] != title
                or recorded["catalogue_time_raw_ms"] != found[identifier]["announcementTime"]
                or recorded["exact_available_at_utc"] is not None):
            raise ValueError("annual document identity, URL or raw clock mismatch")
        raw = base.verified_bytes(root, resource["local_path"], resource["sha256"])
        if len(raw) != resource["bytes"] or not raw.startswith(b"%PDF-"):
            raise ValueError("raw annual PDF size or signature mismatch")
        pages = sorted(set(doc["asset_pages"] + doc["cashflow_pages"] + [doc[key] for key in
                           ("lease_note_page", "currency_page", "consolidated_notes_page", "parent_notes_page")]))
        source = {"role": role, "announcement_id": identifier, "path": resource["local_path"], "url": url,
                  "sha256": doc["pdf_sha256"], "page_count": doc["page_count"], "evidence_pages": pages,
                  "catalogue_title": title, "catalogue_time_raw_ms": recorded["catalogue_time_raw_ms"],
                  "exact_available_at_utc": None}
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            if len(pdf) != doc["page_count"]:
                raise ValueError("annual PDF page count differs")
            texts, words = {}, {}
            for page in pages:
                texts[page] = "".join(pdf[page - 1].get_text().split())
                words[page] = pdf[page - 1].get_text("words")
                if ISSUER_HEADER not in texts[page] or not 595 <= pdf[page - 1].rect.width <= 596:
                    raise ValueError("issuer, report year or page geometry drift")
            if ("2024年12月31日" not in texts[doc["asset_pages"][0]]
                    or "本集团以人民币为记账本位币" not in texts[doc["currency_page"]]
                    or "合并财务报表项目注释" not in texts[doc["consolidated_notes_page"]]
                    or "母公司财务报表主要项目注释" not in texts[doc["parent_notes_page"]]
                    or not doc["consolidated_notes_page"] < doc["lease_note_page"] < doc["parent_notes_page"]):
                raise ValueError("year, currency or consolidated notes boundary not established")

            def combined(page_numbers):
                return [(*word[:1], word[1] + number * 1000, word[2], word[3] + number * 1000, *word[4:])
                        for number, page in enumerate(page_numbers) for word in words[page]]

            tables = extract_tables(combined(doc["asset_pages"]), combined(doc["cashflow_pages"]),
                                    words[doc["lease_note_page"]])
            if render_dir is not None:
                out = Path(render_dir) / role
                out.mkdir(parents=True, exist_ok=False)
                for page in pages:
                    pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(out / f"physical-{page}.png")
        for field, expected in doc["expected"].items():
            if tables["rows"][field]["current_cny"] != expected:
                raise ValueError(f"fixed source value changed: {role}/{field}")
        observations = {}
        field_names = {"E": "attributable_equity", "N": "minority_interest", "OCF": "operating_cash_flow",
                       "Capex": "capex_cash_paid"}
        for name, field in field_names.items():
            field_pages = doc["asset_pages"] if name in ("E", "N") else doc["cashflow_pages"]
            observations[name] = {"field": field, "security_id": scope["security_id"],
                                  "period_start": scope["period_start"], "period_end": scope["period_end"],
                                  "statement_scope": "CONSOLIDATED", "unit": "CNY", "version": role,
                                  "document_sha256": doc["pdf_sha256"],
                                  "observed_value": tables["rows"][name]["current_cny"],
                                  "evidence_refs": [base._ref(source, page) for page in field_pages],
                                  "diagnostic_available_at": None, "historical_pit_status": "UNKNOWN"}
        bundles.append({"version": role, "observations": observations, "tables": tables,
                        "ordinary_source_arithmetic": source_arithmetic(observations),
                        "lease_financing_component": {"observed_cny": tables["rows"]["lease_financing_component"]["current_cny"],
                                                      "cashflow_category": "FINANCING",
                                                      "evidence_refs": [base._ref(source, doc["lease_note_page"])],
                                                      "full_lease_cash_coverage": "UNKNOWN",
                                                      "principal_interest_cash_bridge": "UNKNOWN"},
                        "pit_and_standard_outputs": {field: None for field in UNKNOWN_FIELDS}})
        documents.append(source)
    code_paths = (TOOL, "scripts/pilots/capture_financial_2024_000637.py",
                  "scripts/pilots/build_limited_diagnostics.py", "scripts/pilots/verify_attributable_equity_000637.py",
                  "scripts/pilots/verify_minority_equity_000637.py", "scripts/pilots/verify_lease_cash_000637.py",
                  "turtle_quant/core/types.py")
    report = {"schema_version": "financial_2024_000637_diagnostic_v1", "title": "茂化实华 2024 年原文窗口扩展诊断",
              "security_id": scope["security_id"], "as_of": scope["as_of"], "period_end": scope["period_end"],
              "period_start": scope["period_start"], "review_date": scope["review_date"],
              "diagnostic_only": True, "official_selection": False, "production_reader_ready": False,
              "timing_policy": scope["timing_policy"], "diagnostic_available_at": None,
              "historical_pit_observations_admitted": 0, "complete_revision_chain_verified": False,
              "full_amended_audit_status": "UNKNOWN", "source_documents": documents, "version_bundles": bundles,
              "catalogue_queries": audit["catalogues"], "current_catalogue_rows": [found[key] for key in sorted(found)],
              "remaining_gaps": ["complete_lease_cash_and_overlap", "verified_available_at", "latest_visible_version",
                                 "complete_revision_withdrawal_chain", "full_amended_audit_status", "2021_2023_original_window"],
              "not_claimed": ["不是官方 Top-N、真实选股结果、真实 PIT 策略运行、可发布回测或投资建议。",
                              "不输出排名、权重、订单、持仓或净值；不接入未就绪 Reader，不改变任何 ready 状态。",
                              "不把目录日、抓取日或保守延后假设当作已核实 available_at。",
                              "2023 比较栏不是 2023 原版证据；2024 观察不回填 2025 截断比较栏，也不改写旧报告。"],
              "manifest": {"rule_version": "v1.3.2", "rule_sha256": RULE_HASH,
                           "scope": {"path": INPUTS, "sha256": hashlib.sha256(scope_raw).hexdigest()},
                           "capture": scope["capture"], "previous_2025_lease_review": old,
                           "raw_resources": audit["resources"], "code_hashes": {
                               path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in code_paths}}}
    report["logical_content_hash"] = base.logical_content_hash(report)
    validate_review(report)
    return report


def validate_review(report):
    if (report["schema_version"] != "financial_2024_000637_diagnostic_v1"
            or report["security_id"] != "sz.000637" or report["as_of"] != "2026-09-30"
            or report["period_start"] != "2024-01-01" or report["period_end"] != "2024-12-31"
            or report["review_date"] != "2026-10-02"
            or report["manifest"]["rule_version"] != "v1.3.2" or report["manifest"]["rule_sha256"] != RULE_HASH
            or report["logical_content_hash"] != base.logical_content_hash(report)
            or report["diagnostic_only"] is not True or report["official_selection"] is not False
            or report["production_reader_ready"] is not False or report["diagnostic_available_at"] is not None
            or type(report["historical_pit_observations_admitted"]) is not int
            or report["historical_pit_observations_admitted"] != 0
            or report["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED"
            or report["complete_revision_chain_verified"] is not False
            or report["full_amended_audit_status"] != "UNKNOWN"):
        raise ValueError("diagnostic identity, timing or authority boundary changed")
    if len(report["version_bundles"]) != 2 or len(report["source_documents"]) != 2:
        raise ValueError("two version bundles required")
    for bundle, target, doc, pages in zip(report["version_bundles"], capture.TARGETS,
                                        report["source_documents"], PAGE_BINDINGS):
        if (bundle["version"] != target[0] or bundle["pit_and_standard_outputs"] != {key: None for key in UNKNOWN_FIELDS}
                or doc["role"] != target[0] or doc["announcement_id"] != target[1]
                or doc["url"] != f"https://static.cninfo.com.cn/finalpage/{target[2]}/{target[1]}.PDF"
                or doc["exact_available_at_utc"] is not None
                or bundle["lease_financing_component"]["cashflow_category"] != "FINANCING"
                or bundle["lease_financing_component"]["full_lease_cash_coverage"] != "UNKNOWN"
                or bundle["lease_financing_component"]["principal_interest_cash_bridge"] != "UNKNOWN"
                or bundle["ordinary_source_arithmetic"] != source_arithmetic(bundle["observations"])):
            raise ValueError("partial cash or source arithmetic promoted to complete PIT")
        if (bundle["tables"]["checks"] != check_tables(bundle["tables"]["rows"])
                or bundle["lease_financing_component"]["observed_cny"] != bundle["tables"]["rows"]["lease_financing_component"]["current_cny"]
                or bundle["lease_financing_component"]["evidence_refs"] != [base._ref(doc, pages[2])]):
            raise ValueError("source cash or subtotal evidence differs")
        for name, item in bundle["observations"].items():
            expected_refs = [base._ref(doc, page) for page in pages[0 if name in ("E", "N") else 1]]
            if (item["diagnostic_available_at"] is not None or item["historical_pit_status"] != "UNKNOWN"
                    or item["security_id"] != report["security_id"] or item["period_start"] != report["period_start"]
                    or item["period_end"] != report["period_end"] or item["document_sha256"] != doc["sha256"]
                    or item["version"] != bundle["version"] or item["evidence_refs"] != expected_refs
                    or item["observed_value"] != bundle["tables"]["rows"][name]["current_cny"]):
                raise ValueError("raw observation promoted to PIT")
    forbidden = {"ranking", "rank", "top_n", "target_weights", "orders", "holdings", "nav", "F1", "F2", "F3", "F4", "F5"}

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
    lines += ["", "## 同版原文数值（元）", "",
              "| 版本 | E | N | OCF | Capex | 普通口径原文算术 |",
              "|---|---:|---:|---:|---:|---:|"]
    for bundle in report["version_bundles"]:
        values = [bundle["observations"][key]["observed_value"] for key in ("E", "N", "OCF", "Capex")]
        lines.append("| " + " | ".join([bundle["version"], *values,
                                           bundle["ordinary_source_arithmetic"]["FCF_ordinary_source_arithmetic_cny"]]) + " |")
    lines += ["", "- E+N、经营现金流入−流出两列均对平；筹资附注本期对平。比较栏归还关联方借款为空白，保留 null，分项加总检查 UNKNOWN；附注列示合计与主表比较栏相同，不反推空白为零。",
              "- 同版 alpha 原文算术使用 Decimal 28 位；普通口径 `(OCF-Capex)*alpha` 仅作诊断，不是标准 FCF。",
              "- 两版筹资分类租赁偿还现金均为 `14834290.95` 元；`14834290.95+70252000.00=85086290.95`，与主表对平。",
              "- 该部分不是完整 Lease_cash。本金/利息实际现金桥接、全部租赁现金范围及 OCF/Capex 去重未闭环，完整 Lease_cash、保守 FCF、所有 PIT 项均 UNKNOWN。",
              "", "## 目录与时点", "",
              "- 三次固定标题查询（2024 年年度报告/更正/撤回），日期范围 2025-01-01 至 2026-10-02，分别返回 6/22/0 行；只证明所存当前过滤响应完整。",
              "- 年报标题查询包含半年报及摘要；只有两个显式全文 ID 作为字段来源。空撤回结果不证明历史无撤回，关键词目录不证明完整版本/替换关系。",
              "- 公告目录原始毫秒时间、请求与接收时刻保留于原始抓取清单；这些时刻都不是最早公众可用时刻证明。",
              "- `UNKNOWN_UNLESS_VERIFIED`；`as_of=2026-09-30`；`diagnostic_available_at=null`；历史 PIT 准入数量 0。10 月抓取不倒填 9 月历史。",
              "- 不选择最新可见版，不将旧审计报告重复出现解释为更正后整份重审。",
              "", "## 源身份与物理页码", ""]
    for doc in report["source_documents"]:
        lines += [f'### {doc["role"]}', "", f'- 公告 `{doc["announcement_id"]}`：[官方 PDF]({doc["url"]})。',
                  f'- SHA-256：`{doc["sha256"]}`；{doc["page_count"]} 页。',
                  f'- 物理页码：{doc["evidence_pages"]}。每项字段绑定合并表头、续页和母公司边界；租赁附注在合并/母公司附注边界内。', ""]
    lines += ["## 不变的边界", "", "- 2025 父诊断及全部补证不改写；未把 2024 原文反填 2025 被截断比较栏。",
              "- 已固定原文窗口扩展至 2024、2025 两年，2021—2023 尚未绑定原版证据；不生成 F1—F5。",
              "- RULE_SPEC v1.3.2、历史发布记录、生产快照、九域 not_ready 和真实策略编排状态不变。",
              "- 仅本地诊断，遵守来源条款；公开获取不自动等于批量落库、共享或商用许可，不构成来源许可验收。",
              "", "## 可复现性", "", f'- 本证据包：`{report["logical_content_hash"]}`。',
              "- 离线重建，canonical UTF-8 JSON 排序键，无新增运行时钟；固定抓取审计时间作为输入身份保留。唯一排除自身顶层 logical_content_hash 字段。",
              "- 确定性不证明输入完整；Git 不备份被忽略的原始 PDF。", ""]
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
                raise ValueError(f"frozen 2024 diagnostic differs: {name}")
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
