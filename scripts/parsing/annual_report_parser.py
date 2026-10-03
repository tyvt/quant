"""Conservative, layout-derived annual source bundles, not GeneralFCFInputs.

Supported: native text, unrotated two-column consolidated statements with explicit
boundaries, units and years. Other layouts yield UNKNOWN and evidence candidates.
No issuer-specific page or amount constants, OCR, PIT admission or audit promotion.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
import re

from scripts.parsing.field_binder import binding, cell, compact, inside, union_box
from scripts.parsing.generic_extractor import ParsedPDF


SECTIONS = {
    "balance": ("合并资产负债表", "母公司资产负债表"),
    "income": ("合并利润表", "母公司利润表"),
    "cashflow": ("合并现金流量表", "母公司现金流量表"),
}
ALIASES = {
    "attributable_equity_end": ("balance", ("归属于母公司所有者权益合计",)),
    "minority_interest_end": ("balance", ("少数股东权益",)),
    "total_equity_end": ("balance", ("所有者权益合计",)),
    "parent_net_profit": ("income", ("归属于母公司股东的净利润", "归属于母公司所有者的净利润")),
    "total_net_profit": ("income", ("净利润（",)),
    "operating_cash_flow": ("cashflow", ("经营活动产生的现金流量净额",)),
    "capex": ("cashflow", ("购建固定资产、无形资产和其他长期资产支付的现金",)),
}
UNITS = {"单位：元": 1, "单位：人民币元": 1, "单位：万元": 10000,
         "单位：人民币万元": 10000, "单位：亿元": 100000000}


def _title(text):
    return re.sub(r"^(?:[0-9一二三四五六七八九十]+[、.．])", "", compact(text))


def _lines(words):
    groups = []
    for word in sorted(words, key=lambda item: (item.y, item.box[0])):
        if not groups or abs(groups[-1][0].y - word.y) > 2:
            groups.append([word])
        else:
            groups[-1].append(word)
    return [sorted(group, key=lambda item: item.box[0]) for group in groups]


def _header(page, words, year, kind, title_word):
    groups = _lines(words)
    for group in groups:
        if not any(compact(word.text) == "项目" for word in group):
            continue
        current = [word for word in group if compact(word.text) in
                   (("期末余额", str(year), f"{year}年12月31日") if kind == "balance"
                    else (str(year), f"{year}年度", "本期发生额"))]
        prior = [word for word in group if compact(word.text) in
                 (("期初余额", str(year - 1), f"{year - 1}年12月31日") if kind == "balance"
                  else (str(year - 1), f"{year - 1}年度", "上期发生额"))]
        if len(current) != 1 or len(prior) != 1:
            continue
        left, right = current[0], prior[0]
        left_group = [word for word in group if left.box[0] <= word.box[0] < right.box[0]]
        right_group = [word for word in group if word.box[0] >= right.box[0]]
        left_box, right_box = union_box(left_group), union_box(right_group)
        delta = (right_box[0] + right_box[2] - left_box[0] - left_box[2]) / 2
        if delta <= 0 or not inside(page, group):
            return None
        preceding = [word for word in words if word.y < group[0].y and "单位" in compact(word.text)]
        if not preceding:
            return None
        unit = max(preceding, key=lambda word: word.y)
        if compact(unit.text) not in UNITS or not inside(page, (unit,)):
            return None
        # Balance headers using closing/opening labels still require the dated title.
        before = "".join(compact(word.text) for word in words if word.y < group[0].y)
        if kind == "balance" and compact(left.text) == "期末余额" and f"{year}年12月31日" not in before:
            return None
        if kind not in ("balance", "lease") and "年度" not in "".join(word.text for word in group):
            return None
        return {"section": kind, "physical_page": page.number,
                "title": title_word.text, "title_box": list(title_word.box),
                "unit_text": unit.text, "unit_box": list(unit.box),
                "unit_multiplier": UNITS[compact(unit.text)],
                "current_column": "".join(word.text for word in left_group),
                "comparative_column": "".join(word.text for word in right_group),
                "column_boxes": [left_box, right_box],
                "label_right": left.box[0] - delta / 3,
                "column_split": (left_box[0] + left_box[2] + right_box[0] + right_box[2]) / 4,
                "header_bottom": max(word.box[3] for word in group),
                "fiscal_year": year}
    return None


def _row_labels(words, label_right):
    label_words = [word for word in words if word.box[0] < label_right]
    groups = _lines(label_words)
    result, index = [], 0
    while index < len(groups):
        selected = list(groups[index])
        joined = compact("".join(word.text for word in selected))
        if index + 1 < len(groups):
            next_group = groups[index + 1]
            appended = joined + compact("".join(word.text for word in next_group))
            gap = min(word.box[1] for word in next_group) - max(word.box[3] for word in selected)
            capex = ALIASES["capex"][1][0]
            unclosed = joined.count("（") > joined.count("）")
            if 0 <= gap <= 12 and (appended == capex or unclosed):
                selected.extend(next_group)
                index += 1
        result.append(selected)
        index += 1
    return result


def _table(pdf, source, kind):
    start_title, end_title = SECTIONS[kind]
    starts = [(page, word) for page in pdf.pages for word in page.words if _title(word.text) == start_title]
    if len(starts) != 1:
        return {"state": "TABLE_NOT_IDENTIFIED" if not starts else "AMBIGUOUS_TABLE", "rows": []}
    start_page, title = starts[0]
    ends = [(page, word) for page in pdf.pages for word in page.words
            if _title(word.text) == end_title and (page.number, word.y) > (start_page.number, title.y)]
    if not ends:
        return {"state": "CONSOLIDATED_BOUNDARY_UNKNOWN", "rows": []}
    end_page, end_word = min(ends, key=lambda item: (item[0].number, item[1].y))
    opening = tuple(word for word in start_page.words if word.y > title.y
                    and (start_page.number != end_page.number or word.y < end_word.y))
    header = _header(start_page, opening, source["fiscal_year"], kind, title)
    if header is None:
        return {"state": "HEADER_UNIT_YEAR_OR_COLUMNS_UNKNOWN", "rows": []}
    rows = []
    for page in pdf.pages[start_page.number - 1:end_page.number]:
        lower = header["header_bottom"] if page.number == start_page.number else 60
        upper = end_word.box[1] if page.number == end_page.number else page.height - 35
        selected = tuple(word for word in page.words if lower < word.y < upper)
        signatures = [word.box[1] for word in selected if "法定代表人" in word.text]
        if signatures:
            selected = tuple(word for word in selected if word.y < min(signatures))
        compatible_geometry = (page.rotation == 0 and abs(page.width - start_page.width) <= 1)
        repeated_units = {compact(word.text) for word in selected if compact(word.text).startswith("单位：")}
        if repeated_units and repeated_units != {compact(header["unit_text"])}:
            compatible_geometry = False
        for label_words in _row_labels(selected, header["label_right"]):
            text = compact("".join(word.text for word in label_words))
            if not text or text == "项目":
                continue
            box = union_box(label_words)
            observed = cell(page, selected, (box[1] + box[3]) / 2,
                            header["label_right"], header["column_split"], header["unit_multiplier"])
            if not compatible_geometry or not inside(page, label_words):
                observed = {key: {**value, "value_cny": None,
                                 "state": "PAGE_EDGE_OR_GEOMETRY_UNKNOWN"} for key, value in observed.items()}
            rows.append({"source_label": text, **observed,
                         "binding": binding(source, page, label_words, header)})
    return {"state": "NATIVE_TWO_COLUMN_OBSERVATIONS", "header": header,
            "end_boundary": {"physical_page": end_page.number, "text": end_word.text,
                             "box": list(end_word.box)},
            "completeness_certified": False, "rows": rows}


def _field(rows, aliases, *, prefix=False):
    candidates = [row for row in rows if any((_title(row["source_label"]).startswith(alias) if prefix
                                             else _title(row["source_label"]) == alias) for alias in aliases)]
    state = "NOT_IDENTIFIED" if not candidates else "AMBIGUOUS_LABEL" if len(candidates) > 1 else candidates[0]["current"]["state"]
    return {"observed_value_cny": candidates[0]["current"]["value_cny"] if len(candidates) == 1 else None,
            "comparative_not_target_value_cny": candidates[0]["comparative"]["value_cny"] if len(candidates) == 1 else None,
            "state": state, "candidates": candidates, "pit_value": None,
            "diagnostic_available_at": None, "historical_pit_status": "UNKNOWN"}


def _lease(pdf, source):
    starts = [(page, word) for page in pdf.pages for word in page.words
              if _title(word.text) == "合并财务报表项目注释"]
    ends = [(page, word) for page in pdf.pages for word in page.words
            if _title(word.text) == "母公司财务报表主要项目注释"]
    if len(starts) != 1 or len(ends) != 1:
        return _field([], ("偿还租赁负债支付的金额",))
    start, end = (starts[0][0].number, starts[0][1].y), (ends[0][0].number, ends[0][1].y)
    rows = []
    for page in pdf.pages:
        for word in page.words:
            if compact(word.text) != "偿还租赁负债支付的金额" or not start < (page.number, word.y) < end:
                continue
            prior = tuple(item for item in page.words if item.y < word.y)
            headers = [group for group in _lines(prior) if any(compact(item.text) == "项目" for item in group)]
            if not headers:
                continue
            group = max(headers, key=lambda item: item[0].y)
            units = [item for item in prior if "单位" in compact(item.text) and item.y < group[0].y]
            if not units:
                continue
            # Use only the nearest note header, within the consolidated-note interval.
            units_word = max(units, key=lambda item: item.y)
            note_words = (units_word, *group)
            header = _header(page, note_words, source["fiscal_year"], "lease", word)
            financing = [item for item in prior if "与筹资活动有关的现金" in compact(item.text)]
            if header is None or not financing:
                continue
            observed = cell(page, page.words, word.y, header["label_right"],
                            header["column_split"], header["unit_multiplier"])
            rows.append({"source_label": word.text, **observed,
                         "binding": binding(source, page, (word,), header)})
    result = _field(rows, ("偿还租赁负债支付的金额",))
    result["is_complete_lease_cash"] = False
    result["full_lease_cash_not_already_deducted"] = None
    return result


def _audit(pdf, source):
    matches = [(page, word) for page in pdf.pages for word in page.words
               if compact(word.text) == "审计意见类型" and "审计报告正文" in compact(page.text)
               and "审计报告文号" in compact(page.text)
               and f"{source['fiscal_year']}年12月31" in compact(page.text)]
    candidates = []
    for page, word in matches:
        values = [item for item in page.words if abs(item.y - word.y) <= 2 and item.box[0] > word.box[2]]
        if not values:
            continue
        candidates.append({"raw_opinion_type": "".join(item.text for item in sorted(values, key=lambda item: item.box[0])),
                           "binding": binding(source, page, (word, *values), None),
                           "inside_page": inside(page, (word, *values))})
    known = len(candidates) == 1 and candidates[0]["inside_page"]
    return {"raw_opinion_type": candidates[0]["raw_opinion_type"] if known else None,
            "state": "OBSERVED_TEXT_NOT_AUDIT_GATE" if known else "UNKNOWN",
            "candidates": candidates, "latest_audit_unmodified_pit": None,
            "going_concern_uncertainty_pit": None, "amended_whole_statement_audit_status": "UNKNOWN"}


def _reconcile(fields, tables):
    checks = []
    equations = (("E_plus_N", (fields["attributable_equity_end"], fields["minority_interest_end"],
                               fields["total_equity_end"]), (1, 1, -1)),)
    incoming = _field(tables["cashflow"]["rows"], ("经营活动现金流入小计",))
    outgoing = _field(tables["cashflow"]["rows"], ("经营活动现金流出小计",))
    equations += (("OCF_subtotals", (incoming, outgoing, fields["operating_cash_flow"]), (1, -1, -1)),)
    for name, parts, signs in equations:
        for key in ("observed_value_cny", "comparative_not_target_value_cny"):
            values = [part[key] for part in parts]
            difference = None
            if all(value is not None for value in values):
                with localcontext() as context:
                    context.prec = max(40, sum(len(value) for value in values) + 8)
                    difference = sum((Decimal(value) * sign for value, sign in zip(values, signs)), Decimal(0))
                if difference != 0:
                    raise ValueError(f"source column reconciliation failed: {name}/{key}")
            checks.append({"check": name, "column": key,
                           "difference_cny": format(difference, "f") if difference is not None else None,
                           "state": "RECONCILED" if difference is not None else "UNKNOWN"})
    return checks


def parse_annual(pdf: ParsedPDF, source: dict) -> dict:
    if pdf.sha256 != source["pdf_sha256"]:
        raise ValueError("source identity does not match parsed PDF")
    first = "".join(compact(page.text) for page in pdf.pages[:10])
    if (compact(source["issuer"]) not in first or f"{source['fiscal_year']}年年度报告" not in first
            or source["security_id"].split(".")[1] not in first):
        raise ValueError("issuer, annual period or security identity absent/mismatched")
    currency = [page.number for page in pdf.pages if any(sentence in compact(page.text)
                for sentence in ("本公司以人民币为记账本位币", "本公司采用人民币为记账本位币",
                                 "本集团以人民币为记账本位币", "本集团采用人民币为记账本位币"))]
    tables = {kind: (_table(pdf, source, kind) if currency else
                     {"state": "CURRENCY_EVIDENCE_UNKNOWN", "rows": []}) for kind in SECTIONS}
    fields = {key: _field(tables[kind]["rows"], aliases, prefix=(key in ("parent_net_profit", "total_net_profit")))
              for key, (kind, aliases) in ALIASES.items()}
    if fields["capex"]["observed_value_cny"] is not None and Decimal(fields["capex"]["observed_value_cny"]) < 0:
        fields["capex"]["state"] = "NEGATIVE_PAYMENT_REQUIRES_REVIEW"
    lease = _lease(pdf, source) if currency else _field([], ("偿还租赁负债支付的金额",))
    lease.update(is_complete_lease_cash=False, full_lease_cash_not_already_deducted=None)
    audit = _audit(pdf, source)
    return {"source": source, "currency": "CNY" if currency else None, "currency_evidence_pages": currency,
            "statement_scope": "CONSOLIDATED", "fields": fields,
            "lease_financing_component": lease, "audit_text_observation": audit,
            "balance_sheet_row_inventory": tables["balance"]["rows"],
            "table_states": {kind: {key: value for key, value in table.items() if key != "rows"}
                             for kind, table in tables.items()},
            "reconciliations": _reconcile(fields, tables),
            "dependency_preview_only": {"fiscal_year": source["fiscal_year"],
                **{key: value["observed_value_cny"] for key, value in fields.items()},
                "lease_cash_not_already_deducted": None, "available_at": None,
                "admitted_to_hard_gates": False, "reason": "unverified_PIT_versions_lease_audit_and_comparability"},
            "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
            "rule_execution": "NOT_EXECUTED_SOURCE_EXTRACTION_ONLY",
            "full_balance_sheet_semantics_certified": False}
