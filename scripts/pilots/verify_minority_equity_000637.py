"""Verify one missing source field without reopening PIT or rewriting diagnoses.

This is an offline, two-fixed-PDF check, not a generic financial PDF adapter.
Cross-page scope, units, column geometry and the parent-table boundary are checked.
Missing cells stay None. Two versions agreeing on one row is not whole-file identity.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots import build_limited_diagnostics as base


INPUTS = "docs/data-pilots/2026-10-02-minority-equity-000637-inputs.json"
DEFAULT_OUTPUT = "docs/data-pilots/minority-equity-000637-2026-10-02"
TOOL = "scripts/pilots/verify_minority_equity_000637.py"
MONEY = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
MISSING_CELLS = {"", "-", "—", "–"}


def parse_money_cell(text: str | None) -> str | None:
    if text is None or text.strip() in MISSING_CELLS:
        return None
    if not MONEY.fullmatch(text.strip()):
        raise ValueError("unparseable currency cell")
    return format(Decimal(text.strip().replace(",", "")), "f")


def _one(words, label):
    matches = [word for word in words if word[4] == label]
    if len(matches) != 1:
        raise ValueError(f"missing/ambiguous label: {label}")
    return matches[0]


def extract_row(header_text: str, header_words: list, continuation_text: str,
                field_words: list) -> dict:
    """Use this sample's visible column positions, not extraction-list ordering."""
    compact = re.sub(r"\s+", "", header_text)
    for required in ("茂名石化实华股份有限公司", "1、合并资产负债表", "2025年12月31日", "单位：元"):
        if required not in compact:
            raise ValueError("issuer/statement/period/unit header mismatch")
    if "母公司资产负债表" in continuation_text:
        raise ValueError("consolidated continuation ends before target page")
    closing_header = _one(header_words, "期末余额")
    opening_header = _one(header_words, "期初余额")
    closing_x = (closing_header[0] + closing_header[2]) / 2
    opening_x = (opening_header[0] + opening_header[2]) / 2
    if closing_x >= opening_x:
        raise ValueError("column order mismatch")
    split = (closing_x + opening_x) / 2
    label = _one(field_words, "少数股东权益")
    parent = _one(field_words, "2、母公司资产负债表")
    if label[3] >= parent[1]:
        raise ValueError("minority equity row is outside consolidated table")
    row_y = (label[1] + label[3]) / 2
    # This PDF's frozen table geometry only; not a universal layout/OCR standard.
    row_cells = [word for word in field_words
                 if abs((word[1] + word[3]) / 2 - row_y) <= 1
                 and word[0] >= closing_header[0] - 45]
    columns = [[word for word in row_cells if (word[0] + word[2]) / 2 < split],
               [word for word in row_cells if (word[0] + word[2]) / 2 >= split]]
    if any(len(column) > 1 for column in columns):
        raise ValueError("ambiguous currency cell")
    values = [parse_money_cell(column[0][4] if column else None) for column in columns]
    return {
        "closing_amount_cny": values[0], "opening_comparative_amount_cny": values[1],
        "closing_state": "UNKNOWN" if values[0] is None else "EXPLICIT_NUMERIC",
        "opening_comparative_state": "UNKNOWN" if values[1] is None else "EXPLICIT_NUMERIC",
        "column_basis": "cross_page_header_positions_not_linear_text_order",
        "parent_table_starts_below_target_row": True,
    }


def build_supplement(root: Path = ROOT, render_dir: Path | None = None) -> dict:
    import fitz

    root = root.resolve()
    scope_raw = (root / INPUTS).read_bytes()
    scope = base._json(scope_raw)
    if (scope["security_id"] != "sz.000637" or scope["target_field"] != "minority_interest"
            or scope["statement_scope"] != "CONSOLIDATED" or scope["unit"] != "CNY"
            or scope["period_end"] != "2025-12-31"
            or scope["timing_policy"] != "UNKNOWN_UNLESS_VERIFIED"
            or scope["diagnostic_only"] is not True or scope["official_selection"] is not False):
        raise ValueError("single-field diagnostic scope mismatch")
    if date.fromisoformat(scope["as_of"]) > date.fromisoformat(scope["review_date"]):
        raise ValueError("diagnostic date order mismatch")
    parent_source = scope["parent_report"]
    parent = base._json(base.verified_bytes(root, parent_source["path"], parent_source["sha256"]))
    base.validate_report(parent)
    if (parent["security_id"] != scope["security_id"] or parent["as_of"] != scope["as_of"]
            or parent["logical_content_hash"] != parent_source["logical_content_hash"]):
        raise ValueError("parent diagnostic identity mismatch")
    gap = next(item for item in parent["necessary_input_gaps"] if item["field"] == "FCF")
    if scope["target_field"] not in gap["missing_dependencies"]:
        raise ValueError("target is not an existing diagnostic dependency gap")
    rule = parent["manifest"]["rule_identity"]
    base.verified_bytes(root, rule["path"], rule["sha256"])
    probes = [base._json(base.verified_bytes(root, source["path"], source["sha256"]))
              for source in scope["source_inputs"]]
    if any(probe["security_id"] != scope["security_id"] for probe in probes):
        raise ValueError("cross-security source evidence")
    rows, catalogue_sources = base._catalogues(root, probes[1])
    source_documents = {doc["role"]: doc for doc in probes[0]["documents"]}
    if [(doc["role"], doc["announcement_id"]) for doc in scope["documents"]] != [
        ("original_2025_annual_report", "1225248741"),
        ("amended_2025_annual_report", "1225460240"),
    ]:
        raise ValueError("frozen annual version identities changed")
    observations = []
    documents = []
    parsed_sources = []
    for target in scope["documents"]:
        if [target[key] for key in ("header_page", "continuation_page", "field_page")] != [93, 94, 95]:
            raise ValueError("frozen physical page bridge changed")
        source = source_documents[target["role"]]
        doc = base._document(root, probes[1], source, rows, [93, 94, 95])
        if doc["announcement_id"] != target["announcement_id"]:
            raise ValueError("annual document identity mismatch")
        raw = base.verified_bytes(root, doc["path"], doc["sha256"])
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            header, continuation, field = pdf[92], pdf[93], pdf[94]
            parsed = extract_row(header.get_text(), header.get_text("words"),
                                 continuation.get_text(), field.get_text("words"))
        if (parsed["closing_amount_cny"] != target["expected_closing_amount_cny"]
                or parsed["opening_comparative_amount_cny"] != target["expected_opening_comparative_amount_cny"]):
            raise ValueError("frozen observation disagrees with PDF cells")
        documents.append(doc)
        parsed_sources.append((doc, raw))
        observations.append({
            "field": "minority_interest", "security_id": scope["security_id"],
            "period_end": scope["period_end"], "statement_scope": "CONSOLIDATED", "unit": "CNY",
            "version": target["role"], "observed_value": parsed["closing_amount_cny"],
            "source_observation_status": "VERIFIED_IN_THIS_FIXED_DOCUMENT",
            "opening_comparative_not_target_value": parsed["opening_comparative_amount_cny"],
            "extraction_checks": parsed,
            "evidence_refs": [base._ref(doc, 93), base._ref(doc, 94), base._ref(doc, 95)],
            "historical_pit_status": "UNKNOWN", "pit_value": None,
        })
    if render_dir is not None:
        render_dir.mkdir(parents=True, exist_ok=False)
        for doc, raw in parsed_sources:
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                for page in (93, 95):
                    pdf[page - 1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(
                        str(render_dir / f'{doc["role"]}-physical-page-{page}.png'))
    supplement = {
        "schema_version": "single_field_evidence_supplement_v1",
        "title": "茂化实华 2025 少数股东权益：单字段补证（diagnostic_only=true）",
        "security_id": scope["security_id"], "as_of": scope["as_of"],
        "review_date": scope["review_date"], "period_end": scope["period_end"],
        "diagnostic_only": True, "official_selection": False, "real_pit_strategy_run": False,
        "production_reader_ready": False, "parent_report_unchanged": True,
        "not_claimed": list(base.DISCLAIMERS),
        "source_documents": documents, "observations": observations,
        "gap_resolution": {
            "target": "FCF.missing_dependencies.minority_interest",
            "source_observation_before": "NOT_BOUND_IN_PARENT_DIAGNOSTIC",
            "source_observation_after": "KNOWN_FOR_TWO_FIXED_VERSIONS",
            "historical_pit_before": "UNKNOWN", "historical_pit_after": "UNKNOWN",
            "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
            "amount_cny_per_version": "94585884.15", "version_difference_cny": "0.00",
            "does_not_prove": "两版这一行相同，不证明整份报表、完整修订链、审计状态或其他期间一致。",
        },
        "remaining_unknowns": ["available_at", "latest_visible_version", "attributable_equity_pit",
                               "lease_cash_not_already_deducted", "full_amended_audit_status",
                               "complete_revision_chain", "five_year_FCF_and_six_equities"],
        "alpha": None, "FCF": None,
        "rule_execution": "NOT_EXECUTED_SOURCE_FIELD_CHECK_ONLY",
        "timing_policy": "UNKNOWN_UNLESS_VERIFIED",
        "visual_review": scope["visual_review"],
        "manifest": {
            "scope": {"path": INPUTS, "sha256": hashlib.sha256(scope_raw).hexdigest()},
            "parent_report": parent_source, "rule_version": parent["manifest"]["rule_version"],
            "rule_identity": rule, "source_inputs": scope["source_inputs"],
            "catalogue_sources": catalogue_sources,
            "code_sources": [{"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}
                             for path in (TOOL, "scripts/pilots/build_limited_diagnostics.py")],
            "dependencies": {"python": sys.version.split()[0], "pymupdf": fitz.VersionBind},
            "hash_scope": "canonical_utf8_sorted_keys_except_top_level_logical_content_hash",
            "render_semantics": "derived_review_aid_not_source_identity_or_OCR_proof",
        },
    }
    supplement["logical_content_hash"] = base.logical_content_hash(supplement)
    return supplement


def render_markdown(report: dict) -> str:
    lines = [f'# {report["title"]}', "", "## 本报告不宣称", ""]
    lines.extend(f"- {text}" for text in report["not_claimed"])
    lines += ["", "## 单一目标与结果", "",
              '- 证券 `sz.000637`；`as_of=2026-09-30`；经济日期 `2025-12-31`。',
              '- 只补证原版与更正版合并资产负债表的 **少数股东权益 N** 原文观察。',
              '- 两版期末均为 **CNY 94,585,884.15**；期初比较栏为 **CNY 112,947,471.32**，不是本次目标值。',
              '- 关闭的是“此前没有在诊断中绑定该原文字段”的缺口，不是历史可用时点缺口；PIT 值仍为 `null / UNKNOWN`。',
              '- `alpha` 与 `FCF` 仍为 UNKNOWN；未调用规则门控、估值、生产 Reader、选股或回测。',
              "", "## 跨页与列位置核对", "",
              '- 物理第 93 页冻结发行人、2025-12-31、合并资产负债表、元单位、期末/期初表头。',
              '- 第 94 页检查表格继续；第 95 页用表头横向位置绑定两列，而不是按抽取数字出现顺序猜测。',
              '- 第 95 页下半部开始母公司资产负债表；目标行在其上方，不能混入母公司表。',
              '- 本工具只适用于已固定的这两份 PDF；1 点行对齐容差是本样本参数，不是通用 PDF 标准。缺格/空白/破折号保持 UNKNOWN，歧义硬失败。',
              '- 原版与更正版第 93/95 页已按原始 PDF 2 倍渲染目视核对；渲染图只是复核辅助，不替代源 bytes 或证明完整版本关系。',
              "", "## 证据与时点", ""]
    for doc in report["source_documents"]:
        lines += [f'### {doc["role"]}', "",
                  f'- 公告 ID `{doc["announcement_id"]}`；[原始 PDF]({doc["url"]})。',
                  f'- 本地 bytes：`{doc["path"]}`；SHA-256：`{doc["sha256"]}`。',
                  '- 字段物理第 95 页，表头/连续页为第 93/94 页。',
                  f'- 目录 `announcementTime={doc["catalogue_announcement_time_beijing"]}`；仅作目录观察。',
                  '- `diagnostic_available_at=null`；10 月取得原文不倒填 9 月历史时点。', ""]
    lines += ["## 保留的 UNKNOWN", "",
              '`available_at`、最新可见版本、PIT 归母权益、未重复扣除租赁现金、更正后整份审计、完整修订链、五年 FCF/六个年末权益均未因此闭环。', "",
              '两版目标行一致不是整份报表一致证明；不更新父报告，不把一个原文字段补齐宣称为生产域 ready。仅用于遵守来源条款的本地复核，不对外发布或用于商业目的。', "",
              "## 可复现身份", "",
              f'- 父诊断内容哈希：`{report["manifest"]["parent_report"]["logical_content_hash"]}`。',
              f'- 补证内容哈希：`{report["logical_content_hash"]}`；完整输入/工具/规则身份见同名 JSON。', ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(DEFAULT_OUTPUT))
    parser.add_argument("--render-dir", type=Path, help="new derived-review image directory only")
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
                raise ValueError(f"frozen supplement differs: {name}")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for name, raw in artifacts.items():
            (args.output_dir / name).write_bytes(raw)
    print(json.dumps({"diagnostic_only": True, "closed_source_field": "minority_interest",
                      "observed_amount_cny": "94585884.15", "historical_pit_status": "UNKNOWN",
                      "logical_content_hash": report["logical_content_hash"]}))


if __name__ == "__main__":
    main()
