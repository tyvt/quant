"""Offline synthetic-only batch entry point; no network, PDF parser or production Reader."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.screening.batch_runner import BatchRunner
from scripts.screening.contracts import canonical_bytes, load_request
from scripts.screening.demo import demo_request


def markdown(report: dict) -> bytes:
    labels = {"PASSED": "通过：可进入详细分析", "STOPPED": "停止：已知失败／范围不支持",
              "NEEDS_EVIDENCE": "待补证"}
    lines = ["# 批量硬门筛选 · 纯技术诊断（全部合成输入）", "",
             "不是官方 Top-N、真实选股结果、真实 PIT 运行或可发布回测；不构成投资建议。",
             "硬门通过仅进入详细分析工作队列，不表示正式候选或买入资格。",
             "证券按代码排列，不是排名。范围不支持单独标记，不等于财务 FAIL。", "",
             f"as_of：`{report['as_of']}`。规则：`{report['identity']['rule_version']}`。",
             f"logical_content_hash：`{report['logical_content_hash']}`。", "",
             "| 证券 | 工作队列 | 原基础状态 | 前提汇总状态 | 原因／缺口 |",
             "|---|---|---|---|---|"]
    for row in report["rows"]:
        notes = list(row["basic"]["reasons"])
        for gate in row["enterprise_gates"]:
            if gate["status"] != "PASS":
                notes.append(f"{gate['rule_id']}={gate['status']}")
                notes.extend(gate["missing_fields"])
                notes.extend(gate["notes"])
        text = "; ".join(sorted(set(notes))) or "六门均 PASS（合成验收）"
        text = text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {row['security_id']} | {labels[row['work_queue']]} | "
                     f"{row['basic']['status']} | {row['premise_status']} | {text} |")
    lines += ["", "## 集中待补证索引", "",
              "| 阶段 | 规则 | 缺口 | 涉及证券（代码序，非排名） |",
              "|---|---|---|---|"]
    for item in report["evidence_backlog"]:
        gap = item["gap"].replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {item['stage']} | {item['rule_id']} | {gap} | "
                     f"{', '.join(item['security_ids'])} |")
    lines += ["", "## 未执行的范围", "",
              "不调用未就绪 Reader；不解析真实 PDF；不计算机会资格、评分、排名、权重、订单或净值。",
              "本批不证明完整结构证券池或整月完整性。UNKNOWN 与已知 FAIL 并存时保留待补证，",
              "但停止追加详细工作；不靠短路把未知变成失败。未执行的企业阶段保持 NOT_RUN。",
              "完整逐门状态、缺失字段及证据引用见同目录 JSON。", ""]
    return "\n".join(lines).encode("utf-8")


def write_output(directory: Path, report: dict):
    # A fresh directory avoids partial replacement of any earlier evidence package.
    directory.mkdir(parents=True, exist_ok=False)
    for name, raw in (("diagnostic-only.json", canonical_bytes(report) + b"\n"),
                      ("diagnostic-only.md", markdown(report))):
        with (directory / name).open("xb") as stream:
            stream.write(raw)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="strict SYNTHETIC_FIXTURE JSON")
    source.add_argument("--demo", action="store_true", help="five artificial securities")
    parser.add_argument("--output", type=Path, help="new output directory; never overwrite")
    parser.add_argument("--batch-size", type=int, default=128, help="execution chunk size, not a quota")
    parser.add_argument("--check", action="store_true", help="compare existing output and deterministic rerun")
    args = parser.parse_args(argv)
    if args.check and args.output is None:
        parser.error("--check requires --output")
    try:
        request = demo_request() if args.demo else load_request(args.input.read_bytes())
        runner = BatchRunner()
        first = runner.run(request, batch_size=args.batch_size)
        second = runner.run(request, batch_size=1)
        if canonical_bytes(first.report) != canonical_bytes(second.report):
            raise ValueError("warm/chunked rerun content mismatch")
        report = first.report
        if args.check:
            expected = {"diagnostic-only.json": canonical_bytes(report) + b"\n",
                        "diagnostic-only.md": markdown(report)}
            if any((args.output / name).read_bytes() != raw for name, raw in expected.items()):
                raise ValueError("existing diagnostic content mismatch")
        elif args.output:
            write_output(args.output, report)
        else:
            sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
        if args.output:
            print(f"SYNTHETIC_FIXTURE {report['counts']} "
                  f"logical_content_hash={report['logical_content_hash']}")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"batch screening stopped: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
