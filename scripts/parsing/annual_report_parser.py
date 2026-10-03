"""Conservative, layout-derived annual source bundles, not GeneralFCFInputs.

Supported: native text, unrotated two-amount-column consolidated statements with
explicit boundaries, units and years, optionally with an explicit note column.
Other layouts yield UNKNOWN and evidence candidates.
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
    "attributable_equity_end": ("balance", ("归属于母公司所有者权益合计",
                                          "归属于母公司所有者权益（或股东权益）合计")),
    "minority_interest_end": ("balance", ("少数股东权益",)),
    "total_equity_end": ("balance", ("所有者权益合计", "所有者权益（或股东权益）合计")),
    "parent_net_profit": ("income", ("归属于母公司股东的净利润", "归属于母公司所有者的净利润")),
    "total_net_profit": ("income", ("净利润（",)),
    "operating_cash_flow": ("cashflow", ("经营活动产生的现金流量净额",)),
    "capex": ("cashflow", ("购建固定资产、无形资产和其他长期资产支付的现金",)),
}
UNITS = {"单位：元": 1, "单位：人民币元": 1, "单位：万元": 10000,
         "单位：人民币万元": 10000, "单位：亿元": 100000000}
LEASE_LABELS = ("偿还租赁负债支付的金额", "租赁支付的现金")


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


def _header(page, words, year, kind, title_word, *, title_page=None):
    groups = _lines(words)
    for group in groups:
        if not any(compact(word.text) == "项目" for word in group):
            continue
        label = next(word for word in group if compact(word.text) == "项目")
        columns = []
        for word in (item for item in group if item.box[0] > label.box[2]):
            if not columns or word.box[0] - columns[-1][-1].box[2] > 18:
                columns.append([word])
            else:
                columns[-1].append(word)
        # Only an explicit non-amount note header, before both amount columns,
        # can be separated. Never discard an unknown or extra numeric column.
        note_group = None
        if len(columns) == 3 and re.fullmatch(r"附注(?:[一二三四五六七八九十0-9]+)?",
                                             compact("".join(word.text for word in columns[0]))):
            note_group, columns = columns[0], columns[1:]
        if len(columns) != 2:
            continue
        left_group, right_group = columns
        labels = [compact("".join(word.text for word in column)) for column in columns]
        allowed = (({"期末余额", f"{year}年12月31日"},
                    {"期初余额", f"{year - 1}年12月31日", f"{year}年1月1日"}) if kind == "balance"
                   else ({"本期发生额"}, {"上期发生额"}) if kind == "lease"
                   else ({f"{year}年度"}, {f"{year - 1}年度"}))
        if labels[0] not in allowed[0] or labels[1] not in allowed[1]:
            continue
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
        if kind == "balance" and labels[0] == "期末余额" and f"{year}年12月31日" not in before:
            return None
        result = {"section": kind, "physical_page": page.number,
                "title": title_word.text, "title_box": list(title_word.box),
                "title_physical_page": title_page if title_page is not None else page.number,
                "unit_text": unit.text, "unit_box": list(unit.box),
                "unit_multiplier": UNITS[compact(unit.text)],
                "current_column": "".join(word.text for word in left_group),
                "comparative_column": "".join(word.text for word in right_group),
                "column_boxes": [left_box, right_box],
                "label_right": left_box[0] - delta / 3,
                "column_split": (left_box[0] + left_box[2] + right_box[0] + right_box[2]) / 4,
                "header_bottom": max(word.box[3] for word in group),
                "fiscal_year": year}
        if note_group is not None:
            note_box = union_box(note_group)
            if not label.box[2] < note_box[0] < note_box[2] < left_box[0]:
                return None
            result["label_right"] = (label.box[0] + label.box[2] + note_box[0] + note_box[2]) / 4
            result["note_column"] = {"header_text": "".join(word.text for word in note_group),
                                     "header_box": note_box,
                                     "amount_left": (note_box[2] + left_box[0]) / 2}
        return result
    return None


def _row_labels(words, label_right, *, amount_left=None):
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
            exact_aliases = tuple(alias for kind, aliases in ALIASES.values() for alias in aliases
                                  if kind in ("balance", "cashflow"))
            completes_target = _title(appended) in exact_aliases and _title(joined) not in exact_aliases
            # A centered amount can accompany a two-line profit label whose
            # second line is solely the explicit loss-sign qualifier. Do not
            # join it to another independent financial item.
            profit_aliases = ALIASES["parent_net_profit"][1]
            profit_qualifier = (_title(joined) in profit_aliases
                                and re.fullmatch(r"（净亏损以[“\"][-－−][”\"]号填列）",
                                                 compact("".join(word.text for word in next_group))) is not None)
            unclosed = joined.count("（") > joined.count("）")
            closes_parenthesis = unclosed and appended.count("（") <= appended.count("）")
            merged_y = (min(word.box[1] for word in (*selected, *next_group))
                        + max(word.box[3] for word in (*selected, *next_group))) / 2
            data_left = label_right if amount_left is None else amount_left
            separate_row_data = any(
                word.box[0] >= data_left and re.fullmatch(r"[-−－]?[0-9][0-9,.]*", compact(word.text))
                and abs(word.y - merged_y) > 2
                and (abs(word.y - selected[0].y) <= 2 or abs(word.y - next_group[0].y) <= 2)
                for word in words)
            if (0 <= gap <= 12 and not separate_row_data
                    and (completes_target or closes_parenthesis or profit_qualifier)):
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
    if not inside(start_page, (title,)):
        return {"state": "TABLE_TITLE_GEOMETRY_UNKNOWN", "rows": []}
    ends = [(page, word) for page in pdf.pages for word in page.words
            if _title(word.text) == end_title and (page.number, word.y) > (start_page.number, title.y)]
    if not ends:
        return {"state": "CONSOLIDATED_BOUNDARY_UNKNOWN", "rows": []}
    end_page, end_word = min(ends, key=lambda item: (item[0].number, item[1].y))
    header = None
    # Explicit table title may be at a page's foot. Search only that page and
    # its immediate successor, never arbitrary later pages or parent tables.
    for page in pdf.pages[start_page.number - 1:min(start_page.number + 1, end_page.number)]:
        opening = tuple(word for word in page.words
                        if (page.number != start_page.number or word.y > title.y)
                        and (page.number != end_page.number or word.y < end_word.y))
        header = _header(page, opening, source["fiscal_year"], kind, title, title_page=start_page.number)
        if header is not None:
            break
        if any(compact(word.text) == "项目" for word in opening):
            break  # An explicit but invalid first header cannot be bypassed.
    if header is None:
        return {"state": "HEADER_UNIT_YEAR_OR_COLUMNS_UNKNOWN", "rows": []}
    rows = []
    for page in pdf.pages[header["physical_page"] - 1:end_page.number]:
        lower = header["header_bottom"] if page.number == header["physical_page"] else 60
        upper = end_word.box[1] if page.number == end_page.number else page.height - 35
        selected = tuple(word for word in page.words if lower < word.y < upper)
        signatures = [word.box[1] for word in selected if "法定代表人" in word.text]
        if signatures:
            selected = tuple(word for word in selected if word.y < min(signatures))
        compatible_geometry = (page.rotation == 0 and abs(page.width - start_page.width) <= 1)
        repeated_units = {compact(word.text) for word in selected if compact(word.text).startswith("单位：")}
        if repeated_units and repeated_units != {compact(header["unit_text"])}:
            compatible_geometry = False
        for label_words in _row_labels(selected, header["label_right"],
                                      amount_left=header.get("note_column", {}).get("amount_left")):
            text = compact("".join(word.text for word in label_words))
            if not text or text == "项目":
                continue
            box = union_box(label_words)
            observed = cell(page, selected, (box[1] + box[3]) / 2,
                            header["label_right"], header["column_split"], header["unit_multiplier"],
                            amount_left=header.get("note_column", {}).get("amount_left"))
            if not compatible_geometry or not inside(page, label_words):
                observed = {key: {**value, "value_cny": None,
                                 "state": "PAGE_EDGE_OR_GEOMETRY_UNKNOWN"} for key, value in observed.items()}
            row = {"source_label": text, **observed,
                   "binding": binding(source, page, label_words, header)}
            if "note_column" in header:
                note_words = [word for word in selected if abs(word.y - (box[1] + box[3]) / 2) <= 2
                              and header["label_right"] <= word.box[0] < header["note_column"]["amount_left"]]
                row["note_column_observation"] = {"raw_text": [word.text for word in note_words],
                                                  "boxes": [list(word.box) for word in note_words]}
            rows.append(row)
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
            if compact(word.text) not in LEASE_LABELS or not start < (page.number, word.y) < end:
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
            cash_contexts = [item for item in prior
                             if re.search(r"与(?:经营|投资|筹资)活动有关的现金", compact(item.text))]
            context = max(cash_contexts, key=lambda item: item.y) if cash_contexts else None
            if (header is None or context is None or "与筹资活动有关的现金" not in compact(context.text)
                    or "支付" not in context.text or not inside(page, (context,))):
                continue
            observed = cell(page, page.words, word.y, header["label_right"],
                            header["column_split"], header["unit_multiplier"])
            rows.append({"source_label": word.text, **observed,
                         "classification_evidence": {"physical_page": page.number, "text": context.text,
                                                     "box": list(context.box), "classification": "FINANCING_PAYMENT"},
                         "binding": binding(source, page, (word,), header)})
    result = _field(rows, LEASE_LABELS)
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


def _currency_evidence(pdf):
    # Native line observations, not a full-text substring search. A quoted or
    # subsidiary-only sentence elsewhere cannot establish issuer currency.
    lines = [(page, group, compact("".join(word.text for word in group)))
             for page in pdf.pages for group in _lines(page.words)]
    starts = [index for index, (_, _, text) in enumerate(lines)
              if re.fullmatch(r"[一二三四五六七八九十]+、重要会计政策及会计估计", text)]
    if len(starts) != 1:
        return []
    start = starts[0]
    chapter = lines[start][2].split("、", 1)[0]
    numerals = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
    if chapter not in numerals[:-1]:
        return []
    next_chapter = numerals[numerals.index(chapter) + 1] + "、"
    end = next((index for index in range(start + 1, len(lines))
                if lines[index][2].startswith(next_chapter)), None)
    if end is None or not all(inside(lines[index][0], lines[index][1]) for index in (start, end)):
        return []
    headings = [index for index in range(start + 1, end) if _title(lines[index][2]) == "记账本位币"]
    if len(headings) != 1:
        return []
    index = headings[0]
    page, heading, heading_text = lines[index]
    if index + 1 >= end:
        return []
    first_page, first, text = lines[index + 1]
    gap = min(word.box[1] for word in first) - max(word.box[3] for word in heading)
    if (first_page.number != page.number or not page.text.strip()
            or not inside(page, (*heading, *first)) or not 0 <= gap <= 48):
        return []  # No arbitrary paragraph/page joins, rotation or clipping.
    accepted = ("本公司以人民币为记账本位币。", "本公司采用人民币为记账本位币。",
                "本集团以人民币为记账本位币。", "本集团采用人民币为记账本位币。",
                "本公司的记账本位币为人民币。", "本集团的记账本位币为人民币。",
                "采用人民币为记账本位币。", "以人民币为记账本位币。")
    section_end = next((pos for pos in range(index + 1, end)
                        if re.match(r"[0-9]+[、.．]", lines[pos][2])), end)
    joint_sentence = "本公司及境内子公司记账本位币为人民币。"
    joint = text.startswith(joint_sentence)
    continuation = None
    if joint and text != joint_sentence:
        # The issuer sentence itself must be complete on one native row. Only
        # this explicit subsidiary-determination context may continue on the
        # immediately adjacent row; never join a split currency declaration.
        prefix = "本公司下属子公司根据其经营所处的主要经济环境确定其记账本位币，境外子公司"
        tail = text[len(joint_sentence):]
        context_words = [first]
        if not tail.startswith(prefix):
            if index + 2 >= section_end:
                return []
            next_page, following, following_text = lines[index + 2]
            context_gap = min(word.box[1] for word in following) - max(word.box[3] for word in first)
            if (not prefix.startswith(tail) or not tail.startswith("本公司下属子公司")
                    or next_page.number != page.number or not inside(page, following)
                    or not 0 <= context_gap <= 12 or not (tail + following_text).startswith(prefix)):
                return []
            context_words.append(following)
        continuation = {"kind": "SUBSIDIARY_DETERMINATION_NOT_ISSUER_CURRENCY",
                        "physical_page": page.number,
                        "text": "".join(word.text for group in context_words for word in group),
                        "boxes": [union_box(group) for group in context_words]}
    if not joint and not any(text == sentence or text.startswith(sentence + "境外子公司") for sentence in accepted):
        return []
    # Repeated/conflicting issuer claims also count when they share a row or
    # lack a final full stop. Foreign subsidiary statements do not replace the
    # issuer, and arbitrary joint subjects are not new supported declarations.
    subject = r"(?:本公司及境内子公司|本公司|本集团)"
    claim = re.compile(subject + r"(?:以|采用)[^。]*?为记账本位币"
                       r"|" + subject + r"(?:的)?记账本位币为"
                       r"|(?:^|(?<=。))(?:以|采用)[^。]*?为记账本位币")
    # Joining context is only a veto for extra claims, never positive evidence
    # for a broken declaration. A wrapped conflicting claim is still unsafe.
    context_text = "".join(lines[pos][2] for pos in range(index + 1, section_end))
    if len(claim.findall(context_text)) != 1:
        return []
    policy_page, policy_words, policy_text = lines[start]
    end_page, end_words, end_text = lines[end]
    evidence = {"physical_page": page.number, "kind": "SCOPED_CURRENCY_POLICY_DECLARATION",
             "subject_scope": "ISSUER_ACCOUNTING_POLICY_NOT_SUBSIDIARY_OR_EXAMPLE",
             "document_sha256": pdf.sha256,
             "policy_heading_text": policy_text, "policy_heading_box": union_box(policy_words),
             "policy_heading_physical_page": policy_page.number,
             "policy_end_text": end_text, "policy_end_box": union_box(end_words),
             "policy_end_physical_page": end_page.number,
             "heading_text": heading_text, "heading_box": union_box(heading),
             "declaration_text": "".join(word.text for word in first),
             "declaration_box": union_box(first)}
    if joint:
        evidence["matched_sentence"] = joint_sentence
        if continuation is not None:
            evidence["continuation_context"] = continuation
    return [evidence]


def _annual_identity(pdf, source):
    """Keep legacy Arabic admission; narrowly bind a new Chinese cover title.

    A catalogue, publication date or digits elsewhere cannot stand in for the
    new path's issuer, A-share identity and complete reporting-period evidence.
    No title repair changes currency, amount units or statement boundaries.
    """
    first = "".join(compact(page.text) for page in pdf.pages[:10])
    year, issuer, code = source["fiscal_year"], compact(source["issuer"]), source["security_id"].split(".")[1]
    if issuer not in first or code not in first:
        raise ValueError("issuer, annual period or security identity absent/mismatched")
    cover = pdf.pages[0]
    rows = [(group, compact("".join(word.text for word in group))) for group in _lines(cover.words)]
    titles = [(group, text) for group, text in rows
              if re.fullmatch(r"(?:[0-9]{4}年?|[〇零一二三四五六七八九]{4}年?)年度报告", text)]
    chinese_year = "".join("〇一二三四五六七八九"[int(digit)] for digit in str(year))
    allowed = {f"{year}年年度报告", chinese_year + "年度报告"}
    if any(text not in allowed for _, text in titles):
        raise ValueError("cover annual title year or syntax disagrees with declared source")
    # Legacy reports may use varied period definitions. An explicit full-year
    # definition, when recognized, must not conflict even on the old path.
    periods = []
    for page in pdf.pages[:10]:
        for group in _lines(page.words):
            text = compact("".join(word.text for word in group))
            if re.match(r"(?:报告期[:：]|报告期指|本报告期指|报告期、本报告期指)", text):
                match = re.fullmatch(r"(?:报告期[:：]|报告期指|本报告期指|报告期、本报告期指)"
                                     r"([0-9]{4})年1月1日至([0-9]{4})年12月31日(?:之期间)?", text)
                if match and match.groups() != (str(year), str(year)):
                    raise ValueError("explicit reporting period disagrees with declared source")
                periods.append((page, group, text, match))
    selected = [(group, text) for group, text in titles if text == chinese_year + "年度报告"]
    if f"{year}年年度报告" in first and not selected:
        return None  # Existing Arabic path and its table date/unit guards remain.
    names = [group for group, text in rows if text == issuer]
    shares = [(group, text) for group, text in rows
              if re.fullmatch(r"（A股：[0-9]{6}(?:H股：[0-9]{5})?）", text)]
    if (len(selected) != 1 or len(names) != 1 or len(shares) != 1
            or not re.fullmatch(r"（A股：" + re.escape(code) + r"(?:H股：[0-9]{5})?）", shares[0][1])
            or len(periods) != 1 or periods[0][3] is None
            or not inside(cover, (*selected[0][0], *names[0], *shares[0][0]))
            or not inside(periods[0][0], periods[0][1])):
        raise ValueError("Chinese annual title requires bound issuer, A-share code and full-year period")
    period_page, period_words, period_text, _ = periods[0]
    return {"kind": "CHINESE_ANNUAL_TITLE_WITH_EXPLICIT_FULL_YEAR_PERIOD",
            "document_sha256": pdf.sha256, "declared_fiscal_year": year,
            "physical_page": cover.number, "issuer_text": issuer, "issuer_box": union_box(names[0]),
            "title_text": selected[0][1], "title_box": union_box(selected[0][0]),
            "share_code_text": shares[0][1], "share_code_box": union_box(shares[0][0]),
            "period_physical_page": period_page.number, "period_text": period_text,
            "period_box": union_box(period_words), "period_start": f"{year}-01-01", "period_end": f"{year}-12-31",
            "public_availability_verified": False}


def parse_annual(pdf: ParsedPDF, source: dict) -> dict:
    if pdf.sha256 != source["pdf_sha256"]:
        raise ValueError("source identity does not match parsed PDF")
    identity = _annual_identity(pdf, source)
    currency_evidence = _currency_evidence(pdf)
    currency = sorted({item["physical_page"] for item in currency_evidence})
    tables = {kind: (_table(pdf, source, kind) if currency else
                     {"state": "CURRENCY_EVIDENCE_UNKNOWN", "rows": []}) for kind in SECTIONS}
    fields = {key: _field(tables[kind]["rows"], aliases, prefix=(key in ("parent_net_profit", "total_net_profit")))
              for key, (kind, aliases) in ALIASES.items()}
    if fields["capex"]["observed_value_cny"] is not None and Decimal(fields["capex"]["observed_value_cny"]) < 0:
        fields["capex"]["state"] = "NEGATIVE_PAYMENT_REQUIRES_REVIEW"
    lease = _lease(pdf, source) if currency else _field([], ("偿还租赁负债支付的金额",))
    lease.update(is_complete_lease_cash=False, full_lease_cash_not_already_deducted=None)
    audit = _audit(pdf, source)
    result = {"source": source, "currency": "CNY" if currency else None, "currency_evidence_pages": currency,
            "currency_evidence": currency_evidence,
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
    if identity is not None:
        result["document_identity_evidence"] = identity
    return result
