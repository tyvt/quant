"""Inspect fixed lease cash evidence without filling the unresolved full input.

Only two explicit PDFs and one annual diagnostic scope are supported. An
identified financing payment is not a complete non-double-counted lease total.
Expense, contract summaries and liability stocks cannot become missing cash.
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
from scripts.pilots import verify_attributable_equity_000637 as equity
from scripts.pilots import verify_minority_equity_000637 as minority
from scripts.pilots import verify_ocf_capex_000637 as cashflow
from turtle_quant.core.types import calculation_context, to_decimal

INPUTS = "docs/data-pilots/2026-10-02-lease-cash-000637-inputs.json"
TOOL = "scripts/pilots/verify_lease_cash_000637.py"
DEFAULT_OUTPUT = "docs/data-pilots/lease-cash-000637-2026-10-02"
PAYMENT = "偿还租赁负债支付的金额"
NOTE_PAYMENT = "支付的其他与筹资活动有关的现金"
MAIN_PAYMENT = "支付其他与筹资活动有关的现金"
VARIABLE = "计入当期损益的未纳入租赁负债计量的可变租赁付款额"
SHORT = "短期租赁费用"
PAGES = {"contract_summary": 74, "cashflow_header": 101, "consolidated_financing_cashflow": 102,
         "functional_currency": 117, "lease_policy": [139, 140], "consolidated_notes_start": 143,
         "liability_balance_not_cash": 172, "cashflow_note_header": 182,
         "cashflow_note_payment": 183, "lessee_expenses": 185, "parent_notes_start": 200}
REMAINING = ["complete_consolidated_lease_cash_coverage", "principal_vs_interest_cash_bridge",
             "expense_to_actual_cash_bridge", "OCF_Capex_overlap_for_all_remaining_components",
             "available_at", "latest_visible_version", "complete_revision_chain", "full_amended_audit_status",
             "five_year_FCF_window"]


def _region(words: list, start: tuple, end: tuple) -> list:
    return [word for word in words if start[3] < word[1] and word[3] < end[1]]


def _two_cells(words: list, label: tuple, current: tuple, prior: tuple) -> dict:
    if current[0] >= prior[0] or abs(cashflow._centre_y(current) - cashflow._centre_y(prior)) > 2:
        raise ValueError("current/prior note columns misaligned")
    split = (current[0] + current[2] + prior[0] + prior[2]) / 4
    cells = [word for word in words if abs(cashflow._centre_y(word) - cashflow._centre_y(label)) <= 2
             and word[0] >= current[0] - 45 and word != label]
    columns = [[word for word in cells if (word[0] + word[2]) / 2 < split],
               [word for word in cells if (word[0] + word[2]) / 2 >= split]]
    if any(len(column) > 1 for column in columns):
        raise ValueError("ambiguous lease source currency cell")
    values = [minority.parse_money_cell(column[0][4] if column else None) for column in columns]
    return {"current_amount": values[0], "prior_comparative_amount": values[1],
            "current_state": "UNKNOWN" if values[0] is None else "EXPLICIT_NUMERIC",
            "prior_comparative_state": "UNKNOWN" if values[1] is None else "EXPLICIT_NUMERIC"}


def extract_financing_payment(note_words: list, header_words: list, main_words: list) -> dict:
    start = minority._one(note_words, NOTE_PAYMENT)
    end = minority._one(note_words, NOTE_PAYMENT + "说明：")
    table = _region(note_words, start, end)
    minority._one(table, "单位：元")
    current, prior = (minority._one(table, label) for label in ("本期发生额", "上期发生额"))
    payment = minority._one(table, PAYMENT)
    borrowing = minority._one(table, "归还关联方资金拆借款")
    total = minority._one(table, "合计")
    section = minority._one(note_words, "（3）与筹资活动有关的现金")
    if not section[3] < start[1] < current[1] < payment[1] < borrowing[1] < total[1] < end[1]:
        raise ValueError("lease payment outside financing note table")
    rows = [_two_cells(table, label, current, prior) for label in (payment, borrowing, total)]
    parent = minority._one(main_words, "6、母公司现金流量表")
    main = [word for word in main_words if word[3] < parent[1]]
    financing = minority._one(main, "三、筹资活动产生的现金流量：")
    main_label = minority._one(main, MAIN_PAYMENT)
    if financing[3] >= main_label[1]:
        raise ValueError("main financing row outside consolidated section")
    main_row = _two_cells(main, main_label, minority._one(header_words, "2025"),
                          minority._one(header_words, "2024"))
    checks = {}
    with calculation_context():
        for key in ("current_amount", "prior_comparative_amount"):
            values = [row[key] for row in rows]
            if any(value is not None and to_decimal(value) < 0 for value in values):
                raise ValueError("financing payment cannot be negative")
            difference = (Decimal(values[2]) - Decimal(values[0]) - Decimal(values[1])
                          if all(value is not None for value in values) else None)
            if difference is not None and difference != 0:
                raise ValueError("financing lease plus borrowing does not reconcile to note total")
            if rows[2][key] != main_row[key]:
                raise ValueError("financing note total differs from consolidated cashflow row")
            checks[key] = {"lease_payment": rows[0][key], "related_borrowing_payment": rows[1][key],
                           "note_total": rows[2][key], "main_statement_total": main_row[key],
                           "difference": None if difference is None else format(difference, "f"),
                           "status": "UNKNOWN" if difference is None else "RECONCILED"}
    return {"cash_payment": rows[0], "reconciliation": checks, "cashflow_category": "FINANCING",
            "outside_OCF_and_Capex_in_source_presentation": True,
            "principal_interest_split": "UNKNOWN", "full_lease_cash_coverage": "UNKNOWN"}


def extract_lease_expenses(words: list, page_width: float = 595.25) -> dict:
    lessee = minority._one(words, "（1）本公司作为承租方")
    lessor = minority._one(words, "（2）本公司作为出租方")
    variable_end = minority._one(words, "简化处理的短期租赁或低价值资产的租赁费用")
    variable_table = _region(words, lessee, variable_end)
    variable = minority._one(variable_table, VARIABLE)
    variable_row = _two_cells(variable_table, variable, minority._one(variable_table, "本期发生额"),
                               minority._one(variable_table, "上期发生额"))
    short_end = minority._one(words, "涉及售后租回交易的情况")
    short_table = _region(words, variable_end, short_end)
    short = minority._one(short_table, SHORT)
    short_prior = minority._one(short_table, "上期")
    short_row = _two_cells(short_table, short, minority._one(short_table, "本期发生额"), short_prior)
    # This source table extends outside the original PDF page. Absence of the
    # rightmost amount is a clipping gap, not evidence of an empty/zero cell.
    if short_prior[2] < page_width - 2 or short_row["prior_comparative_amount"] is not None:
        raise ValueError("fixed clipped comparative layout changed; do not accept a partial currency cell")
    short_row["prior_comparative_state"] = "PAGE_EDGE_CLIPPED_NOT_OBSERVED"
    if not lessee[3] < variable[1] < variable_end[1] < short[1] < short_end[1] < lessor[1]:
        raise ValueError("lease expense outside lessee section")
    return {"variable_lease_expense": variable_row, "short_term_lease_expense": short_row,
            "measurement_basis": "EXPENSE_NOT_VERIFIED_CASH", "cashflow_allocation": "UNKNOWN",
            "unit_basis": "NO_UNIT_REPRINTED_IN_THESE_TWO_SUBTABLES_NOT_USED_AS_RULE_MONEY",
            "missing_comparative_is_not_zero": True,
            "source_layout_issue": "SHORT_TERM_COMPARATIVE_COLUMN_CLIPPED_AT_PDF_RIGHT_EDGE"}


def extract_contract_summary(words: list) -> dict:
    # Two summary tables repeat headers. Bound current-year rows before 上期数.
    current, prior = (minority._one(words, label) for label in ("本期数", "上期数"))
    table = [word for word in words if current[1] < word[1] and word[3] < prior[1]]
    total = minority._one(table, "合计")
    paid = minority._one(table, "支付的租金")
    expense_header = minority._one(table, "简化处理的短期租")
    interest_header = minority._one(table, "承担的租赁负")
    row = [word for word in table if abs(cashflow._centre_y(word) - cashflow._centre_y(total)) <= 2]
    result = {}
    for name, start, end in (("expense_display", expense_header[0], paid[0]),
                              ("rent_paid_display", paid[0], interest_header[0]),
                              ("interest_expense_display", interest_header[0], 475)):
        cells = [word for word in row if start <= (word[0] + word[2]) / 2 < end]
        if len(cells) > 1:
            raise ValueError("ambiguous contract summary cell")
        result[name] = minority.parse_money_cell(cells[0][4] if cells else None)
    return {**result, "coverage": "LISTED_CONTRACTS_NOT_PROVEN_CONSOLIDATED_CASH_UNIVERSE",
            "unit_basis": "NOT_EXPLICIT_IN_THIS_TABLE_NOT_CONVERTED_TO_RULE_MONEY",
            "not_added_to_financing_payment": True}


def build_review(root: Path = ROOT, render_dir: Path | None = None) -> dict:
    import fitz

    root = root.resolve()
    raw_scope = (root / INPUTS).read_bytes()
    scope = base._json(raw_scope)
    required = {"schema_version": "lease_cash_source_review_scope_v1", "security_id": "sz.000637",
                "issuer": "茂名石化实华股份有限公司", "as_of": "2026-09-30", "review_date": "2026-10-02",
                "period_start": "2025-01-01", "period_end": "2025-12-31", "statement_scope": "CONSOLIDATED",
                "timing_policy": "UNKNOWN_UNLESS_VERIFIED", "physical_pages": PAGES}
    if (any(scope.get(key) != value for key, value in required.items())
            or scope["diagnostic_only"] is not True or scope["official_selection"] is not False
            or tuple((item["role"], item["announcement_id"]) for item in scope["documents"]) != equity.VERSIONS):
        raise ValueError("fixed lease review scope or versions changed")
    previous_ref = scope["cashflow_supplement"]
    previous_raw = base.verified_bytes(root, previous_ref["path"], previous_ref["sha256"])
    previous = base._json(previous_raw)
    cashflow.validate_supplement(previous)
    if (previous["logical_content_hash"] != previous_ref["logical_content_hash"]
            or previous_raw != base.canonical_bytes(cashflow.build_supplement(root)) + b"\n"):
        raise ValueError("frozen cashflow/equity supplements do not reproduce")
    expected = scope["expected_per_version"]
    documents, bundles, renders = [], [], []
    pages = sorted({page for value in PAGES.values() for page in (value if isinstance(value, list) else [value])})
    for target, source in zip(scope["documents"], previous["source_documents"]):
        if (target["role"] != source["role"] or target["announcement_id"] != source["announcement_id"]
                or target["pdf_sha256"] != source["sha256"]):
            raise ValueError("fixed lease PDF identity changed")
        raw = base.verified_bytes(root, source["path"], source["sha256"])
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            texts = {page: pdf[page - 1].get_text() for page in pages}
            words = {page: pdf[page - 1].get_text("words") for page in pages}
            compact = {page: "".join(text.split()) for page, text in texts.items()}
            if (any("茂名石化实华股份有限公司2025年年度报告全文" not in text for text in compact.values())
                    or "本公司以人民币为记账本位币。" not in compact[117]
                    or "七、合并财务报表项目注释" not in compact[143]
                    or "十五、母公司财务报表主要项目注释" not in compact[200]
                    or "67、现金流量表项目" not in compact[182] or "单位：元" not in compact[182]
                    or "69、租赁" not in compact[185]
                    or "按照直线法将租赁付款额计入相关资产成本或当期损益" not in compact[139]
                    or "未纳入租赁负债计量的可变租赁付款额于实际发生时计入当期损益" not in compact[140]):
                raise ValueError("issuer, year, consolidated note, currency or policy context mismatch")
            financing = extract_financing_payment(words[183], words[101], words[102])
            expenses = extract_lease_expenses(words[185], pdf[184].rect.width)
            contracts = extract_contract_summary(words[74])
            # A balance is recorded only to prove it is excluded, never as cash.
            start, end = (minority._one(words[172], label) for label in ("39、租赁负债", "40、长期应付款"))
            liability_table = _region(words[172], start, end)
            liability = _two_cells(liability_table, minority._one(liability_table, "合计"),
                                    minority._one(liability_table, "期末余额"),
                                    minority._one(liability_table, "期初余额"))
        observed = {"financing_lease_cash_current_cny": financing["cash_payment"]["current_amount"],
                    "financing_lease_cash_prior_cny": financing["cash_payment"]["prior_comparative_amount"],
                    "other_financing_payment_current_cny": financing["reconciliation"]["current_amount"]["note_total"],
                    "other_financing_payment_prior_cny": financing["reconciliation"]["prior_comparative_amount"]["note_total"],
                    "variable_lease_expense_current_display": expenses["variable_lease_expense"]["current_amount"],
                    "variable_lease_expense_prior_display": expenses["variable_lease_expense"]["prior_comparative_amount"],
                    "short_term_lease_expense_current_display": expenses["short_term_lease_expense"]["current_amount"],
                    "short_term_lease_expense_prior_display": expenses["short_term_lease_expense"]["prior_comparative_amount"],
                    "contract_expense_current_display": contracts["expense_display"],
                    "contract_rent_paid_current_display": contracts["rent_paid_display"],
                    "contract_interest_expense_current_display": contracts["interest_expense_display"],
                    "liability_closing_balance_cny_not_cash": liability["current_amount"]}
        if observed != expected:
            raise ValueError("lease source cells differ from frozen observations")
        doc = {**source, "evidence_pages": sorted(set(source["evidence_pages"] + pages)), "lease_review_pages": pages}
        documents.append(doc)
        bundles.append({"version": doc["role"], "document_sha256": doc["sha256"],
                        "financing_cash_component": {**financing, "unit": "CNY", "source_label": PAYMENT,
                            "evidence_refs": [base._ref(doc, page) for page in (101, 102, 182, 183)],
                            "historical_pit_status": "UNKNOWN", "pit_value": None},
                        "expense_observations_not_cash": {**expenses, "evidence_refs": [base._ref(doc, 185)]},
                        "contract_summary_not_full_coverage": {**contracts, "evidence_refs": [base._ref(doc, 74)]},
                        "liability_stock_excluded": {**liability, "basis": "STOCK_NOT_CASH", "not_used_as_lease_cash": True,
                                                    "evidence_refs": [base._ref(doc, 172)]},
                        "policy_is_not_cash_allocation_evidence": {"evidence_refs": [base._ref(doc, page) for page in (139, 140)],
                                                                 "does_not_prove_cash_amount_or_overlap": True},
                        "Lease_cash_not_already_deducted": None, "FCF_conservative": None})
        renders.append((doc, raw))
    if render_dir is not None:
        render_dir.mkdir(parents=True, exist_ok=False)
        for doc, raw in renders:
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                for page in (74, 183, 185):
                    pdf[page - 1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(
                        str(render_dir / f'{doc["role"]}-physical-page-{page}.png'))
    report = {"schema_version": "lease_cash_source_review_v1",
              "title": "茂化实华 2025 租赁现金：已识别筹资部分与完整输入缺口（diagnostic_only=true）",
              **{key: scope[key] for key in ("security_id", "as_of", "period_start", "period_end", "review_date")},
              "diagnostic_only": True, "official_selection": False, "real_pit_strategy_run": False,
              "production_reader_ready": False, "prior_supplements_unchanged": True,
              "not_claimed": list(base.DISCLAIMERS), "timing_policy": "UNKNOWN_UNLESS_VERIFIED",
              "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
              "Lease_cash_not_already_deducted": None, "Lease_cash_pit": None, "FCF_conservative": None,
              "FCF": None, "source_documents": documents, "version_bundles": bundles,
              "gap_resolution": "PARTIAL_FINANCING_CASH_COMPONENT_KNOWN_FULL_LEASE_INPUT_UNKNOWN",
              "remaining_unknowns": REMAINING, "rule_execution": "NOT_EXECUTED_NO_FULL_FCF_CALCULATION",
              "visual_review": scope["visual_review"],
              "manifest": {"scope": {"path": INPUTS, "sha256": hashlib.sha256(raw_scope).hexdigest()},
                           "cashflow_supplement": previous_ref,
                           **{key: previous["manifest"][key] for key in ("parent_report", "equity_supplement", "minority_supplement",
                                                                       "rule_identity", "rule_version", "source_inputs", "catalogue_sources")},
                           "code_sources": [{"path": TOOL, "sha256": hashlib.sha256((root / TOOL).read_bytes()).hexdigest()},
                                            *previous["manifest"]["code_sources"]],
                           "dependencies": {"python": sys.version.split()[0], "pymupdf": fitz.VersionBind},
                           "hash_scope": "canonical_utf8_sorted_keys_except_top_level_logical_content_hash"}}
    report["logical_content_hash"] = base.logical_content_hash(report)
    validate_review(report)
    return report


def validate_review(report: dict) -> None:
    if (report["diagnostic_only"] is not True or report["official_selection"] is not False
            or report["real_pit_strategy_run"] is not False or report["production_reader_ready"] is not False
            or report["prior_supplements_unchanged"] is not True or report["diagnostic_available_at"] is not None
            or report["pit_admitted_observation_count"] != 0 or report["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED"
            or any(report[key] is not None for key in ("Lease_cash_not_already_deducted", "Lease_cash_pit", "FCF_conservative", "FCF"))):
        raise ValueError("lease review authority or unresolved full/PIT input changed")
    if (report["security_id"] != "sz.000637" or report["as_of"] != "2026-09-30"
            or report["period_start"] != "2025-01-01" or report["period_end"] != "2025-12-31"
            or report["logical_content_hash"] != base.logical_content_hash(report)
            or report["remaining_unknowns"] != REMAINING
            or len(report["version_bundles"]) != 2 or len(report["source_documents"]) != 2
            or tuple((doc["role"], doc["announcement_id"]) for doc in report["source_documents"]) != equity.VERSIONS):
        raise ValueError("fixed lease scope, versions, gaps or logical hash changed")
    for doc, bundle in zip(report["source_documents"], report["version_bundles"]):
        if (bundle["version"] != doc["role"] or bundle["document_sha256"] != doc["sha256"]
                or bundle["Lease_cash_not_already_deducted"] is not None or bundle["FCF_conservative"] is not None
                or doc["exact_available_at_utc"] is not None or doc["diagnostic_available_at"] is not None
                or doc["pit_admitted"] is not False or doc["historical_availability_status"] != "UNKNOWN"):
            raise ValueError("lease source version or full/PIT state changed")
        component = bundle["financing_cash_component"]
        if (component["unit"] != "CNY" or component["source_label"] != PAYMENT
                or component["cashflow_category"] != "FINANCING"
                or component["outside_OCF_and_Capex_in_source_presentation"] is not True
                or component["full_lease_cash_coverage"] != "UNKNOWN" or component["principal_interest_split"] != "UNKNOWN"
                or component["pit_value"] is not None or component["historical_pit_status"] != "UNKNOWN"):
            raise ValueError("identified component promoted to full lease input or wrong classification")
        for name, pages in (("financing_cash_component", (101, 102, 182, 183)),
                            ("expense_observations_not_cash", (185,)), ("contract_summary_not_full_coverage", (74,)),
                            ("liability_stock_excluded", (172,)), ("policy_is_not_cash_allocation_evidence", (139, 140))):
            if bundle[name]["evidence_refs"] != [base._ref(doc, page) for page in pages]:
                raise ValueError("lease observation PDF/page binding changed")
        if (bundle["expense_observations_not_cash"]["measurement_basis"] != "EXPENSE_NOT_VERIFIED_CASH"
                or bundle["expense_observations_not_cash"]["cashflow_allocation"] != "UNKNOWN"
                or bundle["expense_observations_not_cash"]["source_layout_issue"] != "SHORT_TERM_COMPARATIVE_COLUMN_CLIPPED_AT_PDF_RIGHT_EDGE"
                or bundle["expense_observations_not_cash"]["short_term_lease_expense"]["prior_comparative_amount"] is not None
                or bundle["expense_observations_not_cash"]["short_term_lease_expense"]["prior_comparative_state"] != "PAGE_EDGE_CLIPPED_NOT_OBSERVED"
                or bundle["contract_summary_not_full_coverage"]["coverage"] != "LISTED_CONTRACTS_NOT_PROVEN_CONSOLIDATED_CASH_UNIVERSE"
                or bundle["contract_summary_not_full_coverage"]["not_added_to_financing_payment"] is not True
                or bundle["liability_stock_excluded"]["not_used_as_lease_cash"] is not True
                or bundle["liability_stock_excluded"]["basis"] != "STOCK_NOT_CASH"):
            raise ValueError("expense, contract or liability used as missing lease cash")
        with calculation_context():
            for key, check in component["reconciliation"].items():
                values = [check[field] for field in ("lease_payment", "related_borrowing_payment", "note_total")]
                if any(value is not None and to_decimal(value) < 0 for value in values):
                    raise ValueError("financing payment cannot be negative")
                difference = (to_decimal(values[2]) - to_decimal(values[0]) - to_decimal(values[1])
                              if all(value is not None for value in values) else None)
                if (component["cash_payment"][key] != values[0] or check["main_statement_total"] != values[2]
                        or check["difference"] != (None if difference is None else format(difference, "f"))
                        or check["status"] != ("UNKNOWN" if difference is None else "RECONCILED")
                        or difference not in (None, Decimal("0"))):
                    raise ValueError("financing component bridge mismatch")
    forbidden = {"ranking", "rank", "tier", "top_n", "orders", "holdings", "nav", "target_weights", "F1", "F2", "F3", "F4", "F5"}

    def check_keys(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("forbidden strategy or FCF window output")
            for child in value.values():
                check_keys(child)
        elif isinstance(value, list):
            for child in value:
                check_keys(child)

    check_keys(report)


def render_markdown(report: dict) -> str:
    validate_review(report)
    lines = [f'# {report["title"]}', "", "## 本报告不宣称", ""]
    lines.extend(f"- {item}" for item in report["not_claimed"])
    lines += ["", "## 结论", "",
              '- 两版合并现金流附注均列明筹资分类的租赁负债偿还现金 `13214300.68` 元（2024 比较栏 `14834290.95` 元）。',
              '- 这只是已识别的筹资租赁现金部分，不是完整 `Lease_cash_not_already_deducted`。本金/利息现金、全部租赁现金范围及其他部分与 OCF/Capex 的重叠仍未闭环。',
              '- `Lease_cash_not_already_deducted/Lease_cash_pit/FCF_conservative/FCF=null`；缺口不填零，不增加已核实历史 PIT 输入。', "",
              "## 同版观察与不允许的替代", "",
              "| 观察 | 本期原文 | 比较栏 | 语义边界 |", "|---|---:|---:|---|",
              '| 租赁负债偿还现金 | 13214300.68 | 14834290.95 | 附注 183 页、合并筹资现金流，不等于完整租赁现金 |',
              '| 计入当期损益的可变租赁付款额 | 691333.32 | 371190.47 | 185 页费用观察；不等于已核实现金 |',
              '| 短期租赁费用 | 12645699.90 | UNKNOWN | 185 页费用观察；源表右侧越出页边界，比较栏不可见，不当空白/零 |',
              '| 合同表支付租金合计 | 13565977.47 | 本次不提取 | 74 页已列合同，不证明完整合并现金覆盖 |',
              '| 合同表租赁利息支出合计 | 5869196.00 | 本次不提取 | 不证明已付现金，也不直接追加到偿还额 |',
              '| 租赁负债期末余额 | 139414669.20 | 145632357.52 | 172 页存量，明确排除为现金代理 |', "",
              '- 费用/合同表子表未重印完整单位说明，保留显示数值及语义，不将它们转成规则 Money 或相加。现金附注偿还行有显式“单位：元”，另核验人民币本位币。',
              '- 现金附注对平：`13214300.68 + 115000000.00 = 128214300.68`；比较栏 `14834290.95 + 70252000.00 = 85086290.95`；合计与同版 102 页筹资现金流一致。',
              '- 租赁会计政策说明费用计入资产成本/当期损益，不提供这些费用的当年现金支付与 OCF/Capex 去重桥接。',
              '- 143 页合并附注与 200 页母公司附注边界单独核验；185 页承租方/出租方分开；不把租金收入抵减支付，不把空白当零。', "",
              "## 时点、范围与可复现性", "",
              '- `sz.000637`；`as_of=2026-09-30`；2025 年度；固定原版/更正版分别复核，不选择声称最新可见版。',
              '- `UNKNOWN_UNLESS_VERIFIED`；`diagnostic_available_at=null`；历史 PIT 准入观察为 0。原文抓取/目录时间不倒填。',
              '- 旧父诊断、N/E/OCF-Capex 补证不改写；不调用 Reader、premise 或 valuation；九域与真实策略编排状态不变。',
              '- 本次只结论为所核固定年报不足以闭环，不宣称所有公开 PDF 路径不可行，也不申请任何 ready 或运行授权。', ""]
    for doc in report["source_documents"]:
        lines += [f'### {doc["role"]}', "", f'- 公告 `{doc["announcement_id"]}`：[法定 PDF]({doc["url"]})。',
                  f'- `{doc["path"]}`；SHA-256 `{doc["sha256"]}`；来源物理页码逐项绑定于 JSON。', ""]
    lines += [f'- 前序现金流证据包：`{report["manifest"]["cashflow_supplement"]["logical_content_hash"]}`。',
              f'- 本证据包：`{report["logical_content_hash"]}`；canonical UTF-8 JSON、排序键、无运行时钟，唯一排除自身顶层哈希字段。',
              '- 离线重建；源 PDF 为证据，渲染仅作目视检查。遵守来源条款，仅本地复核，不对外发布或用于商业用途。', ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(DEFAULT_OUTPUT))
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
                raise ValueError(f"frozen lease review differs: {name}")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for name, raw in artifacts.items():
            (args.output_dir / name).write_bytes(raw)
    print(json.dumps({"diagnostic_only": True, "full_lease_cash": None,
                      "logical_content_hash": report["logical_content_hash"]}))


if __name__ == "__main__":
    main()
