"""Offline E2E acceptance using Git-restored code and existing bounded evidence.

No field supplementation, PIT assumptions, readiness changes, or real selections.
Two fresh isolated Python processes must reproduce frozen diagnostic artifacts.
The existing synthetic-strategy/real-benchmark controls run separately in memory.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
from dataclasses import asdict
from decimal import Decimal
import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import verify_workspace_integrity as integrity
from scripts.pilots import build_limited_diagnostics as base
from scripts.pilots import verify_minority_equity_000637 as supplement
from turtle_quant.core.result import ResultStatus, RuleKind, RuleResult
from turtle_quant.pipeline.decision import DecisionKind, decide


TOOL = "scripts/pilots/run_diagnostic_e2e.py"
DEFAULT_OUTPUT = "docs/testing/diagnostic-e2e-2026-10-02"
SUMMARY = "e2e-report.json"
MARKDOWN = "e2e-report.md"
CONTROL_MODULE = "tests/test_benchmark_technical_integration.py"
CONTROL_CLASS = "BenchmarkTechnicalIntegrationTests"


def project_diagnostic(report: dict) -> dict:
    """Carry verified diagnostic UNKNOWNs into ready pure decision aggregation.

This is NOT a complete company assessment. Financial gates already executed by
the frozen generator are restored unchanged. Other samples use an evidence-gap
result, not a fabricated financial premise. No source amount becomes PIT input.
"""
    base.validate_report(report)
    if (report["timing_assumptions"]["available_at"] is not None
            or report["timing_assumptions"]["admitted_pit_observation_count"] != 0):
        raise ValueError("unverified availability admitted to diagnostic pipeline")
    analysis = report["observed_arithmetic_not_pit_rule_outputs"]
    raw_gates = analysis.get("premise_execution", {}).get("hard_gates", [])
    if "policy_execution" in analysis:
        raw_gates = [analysis["policy_execution"]]
    gates = tuple(RuleResult(
        rule_id=item["rule_id"], kind=RuleKind(item["kind"]), status=ResultStatus(item["status"]),
        value=Decimal(item["value"]) if item["value"] is not None else None,
        notes=tuple(item["notes"]), missing_fields=tuple(item["missing_fields"]),
        evidence_refs=tuple(item["evidence_refs"]),
    ) for item in raw_gates)
    if not gates:
        gates = (RuleResult(
            rule_id="diagnostic.buybacks.required_input_coverage", kind=RuleKind.EVIDENCE,
            status=ResultStatus.UNKNOWN,
            missing_fields=tuple(gap["field"] for gap in report["necessary_input_gaps"]),
            notes=("source interval arithmetic is not a complete PIT buyback window",),
        ),)
    if any(gate.status is not ResultStatus.UNKNOWN or gate.value is not None for gate in gates):
        raise ValueError("frozen diagnostic gates must retain UNKNOWN / null")
    result = decide(gates, coverage6=None, gg_pct=None, required_return_pct=None,
                    score_coverage=Decimal("0"))
    if result.kind is not DecisionKind.NEEDS_REVIEW:
        raise ValueError("incomplete real sample escaped NEEDS_REVIEW")
    return {
        "sample_id": report["sample_id"], "security_id": report["security_id"],
        "as_of": report["as_of"], "parent_logical_content_hash": report["logical_content_hash"],
        "execution_scope": "missing_dependency_propagation_only_not_complete_company_assessment",
        "diagnostic_only": True, "official_selection": False,
        "admitted_pit_observation_count": 0, "available_at": None,
        "rule_results": base._plain([asdict(gate) for gate in gates]),
        "decision": base._plain(asdict(result)),
        "valuation": {"coverage6": None, "gg_pct": None, "required_return_pct": None,
                      "execution": "NOT_EXECUTED_UNKNOWN_DEPENDENCIES"},
        "score_coverage": "0", "quality_score": None,
    }


def require_control_success(result: unittest.TestResult, expected: int) -> dict:
    if (result.testsRun != expected or not result.wasSuccessful() or result.skipped
            or result.expectedFailures or result.unexpectedSuccesses):
        details = [text for _, text in result.errors + result.failures]
        details += [reason for _, reason in result.skipped]
        raise ValueError("technical controls failed or skipped: " + "\n".join(details))
    return {"tests_run": result.testsRun, "failures": 0, "errors": 0, "skipped": 0}


def run_synthetic_controls(evidence_root: Path) -> dict:
    # Import the Git-restored, unchanged technical fixture, NOT tests from the host.
    spec = importlib.util.spec_from_file_location("diagnostic_e2e_benchmark_controls", ROOT / CONTROL_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = evidence_root / "storage"  # raw-data directory is explicitly external to Git
    case = getattr(module, CONTROL_CLASS)
    loader = unittest.TestLoader()
    names = loader.getTestCaseNames(case)
    suite = loader.loadTestsFromTestCase(case)
    result = unittest.TestResult()
    suite.run(result)
    summary = require_control_success(result, 4)
    summary.update({
        "fixture": "synthetic_strategy_x_accepted_real_H00985_technical_only",
        "test_ids": names,
        "numeric_performance_or_trading_outputs_persisted": False,
    })
    return summary


def require_rejected(action, label: str) -> str:
    try:
        action()
    except (ValueError, FileExistsError):
        return label
    raise ValueError(f"negative control did not fail closed: {label}")


def artifact_hashes(directory: Path) -> list[dict]:
    return [{"path": path.relative_to(directory).as_posix(), "sha256": integrity.sha256_file(path)}
            for path in sorted(directory.rglob("*"))
            if path.is_file() and path.relative_to(directory).as_posix() not in {SUMMARY, MARKDOWN}]


def require_artifact_equality(first: Path, second: Path) -> None:
    if artifact_hashes(first) != artifact_hashes(second):
        raise ValueError("independent-process artifact identity mismatch")
    for item in artifact_hashes(first):
        if (first / item["path"]).read_bytes() != (second / item["path"]).read_bytes():
            raise ValueError(f"independent-process bytes differ: {item['path']}")


def verify_frozen_artifacts(directory: Path, evidence_root: Path) -> None:
    for sample in base.SAMPLE_SECURITIES:
        for ext in ("json", "md"):
            name = f"{sample}-diagnostic-only.{ext}"
            actual = (directory / "reports" / name).read_bytes()
            expected = (evidence_root / base.DEFAULT_OUTPUT / name).read_bytes()
            if actual != expected:
                raise ValueError(f"frozen report differs: {name}")
    for ext in ("json", "md"):
        name = f"diagnostic-only.{ext}"
        if ((directory / "supplement" / name).read_bytes()
                != (evidence_root / supplement.DEFAULT_OUTPUT / name).read_bytes()):
            raise ValueError(f"frozen supplement differs: {name}")


def fault_controls(report: dict, reports: list[dict], output: Path, evidence_root: Path) -> list[str]:
    labels = [require_rejected(lambda: base._json(b'{"id":1,"id":2}'), "duplicate_json_key")]
    doc = report["source_documents"][0]
    labels.append(require_rejected(
        lambda: base.verified_bytes(evidence_root, doc["path"], "0" * 64), "wrong_source_sha256"))
    for label, modify in (
        ("output_authority_escalation", lambda value: value.update(official_selection=True)),
        ("unknown_to_zero", lambda value: value["source_observations"][0].update(pit_value="0")),
        ("forbidden_ranking_output", lambda value: value.update(ranking=[])),
    ):
        altered = copy.deepcopy(report)
        modify(altered)
        altered["logical_content_hash"] = base.logical_content_hash(altered)
        labels.append(require_rejected(lambda: base.validate_report(altered), label))
    labels.append(require_rejected(lambda: base.write_reports(reports, output / "reports"),
                                   "existing_output_refused"))
    return labels


def run_worker(evidence_root: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing existing output: {output}")
    manifest = integrity.read_json(ROOT / integrity.MANIFEST)
    integrity.verify_manifest(evidence_root, manifest)
    # No network access or unready real Reader can hide within a successful run.
    with ExitStack() as guards:
        guards.enter_context(patch("socket.socket", side_effect=AssertionError("offline diagnostic")))
        guards.enter_context(patch("socket.create_connection", side_effect=AssertionError("offline diagnostic")))
        for target in (
            "turtle_quant.pit.parquet_financial_statements.ParquetFinancialStatementsReader.__init__",
            "turtle_quant.pit.parquet_buybacks.ParquetBuybackReader.__init__",
            "turtle_quant.pit.parquet_strategy_inputs._NotReadyReader.__init__",
        ):
            guards.enter_context(patch(target, side_effect=AssertionError("unready Reader forbidden")))
        reports = base.build_reports(evidence_root)
        extra = supplement.build_supplement(evidence_root)
        for report in [*reports, extra]:
            for source in report["manifest"]["code_sources"]:
                if integrity.sha256_file(ROOT / source["path"]) != source["sha256"]:
                    raise ValueError(f"runtime/source code identity mismatch: {source['path']}")
        diagnostics = [project_diagnostic(report) for report in reports]
        controls = run_synthetic_controls(evidence_root)
        output.mkdir(parents=True, exist_ok=False)
        base.write_reports(reports, output / "reports")
        (output / "supplement").mkdir()
        (output / "supplement/diagnostic-only.json").write_bytes(base.canonical_bytes(extra) + b"\n")
        (output / "supplement/diagnostic-only.md").write_bytes(supplement.render_markdown(extra).encode("utf-8"))
        negative = fault_controls(reports[0], reports, output, evidence_root)
        # Exercise the next pipeline boundary from deserialised files, not just objects.
        reread = [project_diagnostic(integrity.read_json(
            output / "reports" / f"{sample}-diagnostic-only.json")) for sample in base.SAMPLE_SECURITIES]
        if reread != diagnostics:
            raise ValueError("serialized report-to-decision round trip drift")
        verify_frozen_artifacts(output, evidence_root)
        payload = {
            "schema_version": "technical_diagnostic_pipeline_v1",
            "diagnostic_only": True, "official_selection": False,
            "real_pit_strategy_run": False, "production_reader_ready": False,
            "timing_policy": "UNKNOWN_UNLESS_VERIFIED",
            "real_samples": diagnostics, "synthetic_controls": controls,
            "negative_controls": negative,
            "supplement_logical_content_hash": extra["logical_content_hash"],
        }
        payload["logical_content_hash"] = base.logical_content_hash(payload)
        (output / "pipeline-result.json").write_bytes(base.canonical_bytes(payload) + b"\n")
    return payload


def launch_worker(runtime_root: Path, evidence_root: Path, output: Path, *, expect_failure=False):
    completed = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", str(runtime_root / TOOL), "--worker",
         "--evidence-root", str(evidence_root), "--output-dir", str(output)],
        cwd=runtime_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    if expect_failure:
        if completed.returncode == 0 or output.exists():
            raise ValueError("missing-evidence recovery control silently passed or wrote output")
        if b"required local snapshots absent" not in completed.stderr:
            raise ValueError("negative recovery control failed for an unexpected reason")
        return None
    if completed.returncode != 0:
        raise RuntimeError("diagnostic worker failed:\n" + completed.stderr.decode("utf-8", errors="replace"))
    payload = integrity.read_json(output / "pipeline-result.json")
    if payload["logical_content_hash"] != base.logical_content_hash(payload):
        raise ValueError("worker result hash mismatch")
    return payload


def restore_runtime(root: Path, revision: str, destination: Path) -> dict:
    commit = integrity.git_bytes(root, "rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii").strip()
    archived = integrity.git_bytes(root, "archive", "--format=zip", commit)
    verified = []
    with zipfile.ZipFile(io.BytesIO(archived)) as archive:
        names = archive.namelist()
        if TOOL not in names or "turtle_quant/storage/verification.py" not in names:
            raise ValueError("commit must contain the E2E tool and storage source package")
        for entry in archive.infolist():
            target = destination / entry.filename
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("unsafe Git archive entry")
            if entry.filename.startswith("storage/"):
                raise ValueError("raw storage unexpectedly tracked in Git")
            if not entry.is_dir() and (
                entry.filename.endswith(".py") or entry.filename in integrity.PROTECTED_PATHS
                or entry.filename in {integrity.MANIFEST, "pyproject.toml", ".gitignore", ".gitattributes"}
            ):
                raw = archive.read(entry)
                if integrity.relative_file(root, entry.filename).read_bytes() != raw:
                    raise ValueError(f"Git runtime differs from current workspace: {entry.filename}")
                verified.append({"path": entry.filename, "sha256": hashlib.sha256(raw).hexdigest()})
        archive.extractall(destination)
    return {"commit": commit, "verified_files": sorted(verified, key=lambda item: item["path"]),
            "raw_storage_in_archive": False,
            "recovery_mode": "fresh_Git_archive_code_with_explicit_external_local_evidence"}


def render_markdown(report: dict) -> str:
    lines = ["# 纯技术端到端诊断验收", "", "## 本报告不宣称", "",
             "不是官方 Top-N、真实选股、完整真实 PIT 策略运行或可发布回测；无投资建议。",
             "真实样本不生成排名、权重、订单、持仓或净值；九域与真实编排状态未变。", "",
             "## 验收结果", "",
             f'- Git 恢复基线：`{report["git_recovery"]["commit"]}`。',
             f'- 规则 SHA-256：`{report["integrity"]["rule_sha256"]}`。',
             '- 从 Git archive 恢复代码，在两个全新隔离 Python 进程运行；原始数据只从显式本地路径读取。',
             '- 目录/PDF 字节与物理页 → 原文算术 → UNKNOWN PIT 准入 → 前提/证据门控 → 诊断决策 → JSON/Markdown → 重读校验。',
             '- 四份冻结诊断与既有单字段补证原样复现；本轮没有补新字段。',
             '- 四个真实样本均 NEEDS_REVIEW；历史 PIT 观察准入数量为 0；没有调用未就绪 Reader。',
             '- 既有合成策略 × 真实基准的四项技术联调通过，无跳过；数值绩效和交易对象仅在内存中断言，未输出。',
             '- 两次进程的全部 11 个管线产物逐字节一致；从序列化文件重读所得诊断决策一致。',
             '- 无原始快照时恢复明确失败；错误哈希、重复键、UNKNOWN 填零、输出权限升级、排名与覆盖写入均被拒绝。',
             f'- 生产快照清单：{report["integrity"]["file_count"]} 文件，摘要 `{report["integrity"]["inventory_sha256"]}`。',
             f'- 本报告逻辑内容 SHA-256：`{report["logical_content_hash"]}`。', "",
             "## 保险边界", "",
             "Git 恢复验证只证明已提交代码/文档可恢复，不能恢复 Git 外的 PDF/Parquet，也不证明外部证据完整或历史时点可用。",
             "快照清单不包含所有 raw PDF。未创建异地备份、未推送远程、未发送询证；本地 Git 不等于异地备份。", ""]
    return "\n".join(lines)


def run_e2e(root: Path, evidence_root: Path, output: Path, revision: str = "HEAD", *, check=False) -> dict:
    if output.exists() and not check:
        raise FileExistsError(f"refusing existing output: {output}")
    frozen = integrity.read_json(output / SUMMARY) if check else None
    if frozen is not None:
        revision = frozen["git_recovery"]["commit"]
    manifest = integrity.read_json(root / integrity.MANIFEST)
    summary = integrity.verify_manifest(evidence_root, manifest)
    # Every disposable artifact lives under this one newly allocated temp directory.
    with TemporaryDirectory(prefix="quant-diagnostic-e2e-") as temporary:
        task_root = Path(temporary).resolve()
        runtime = task_root / "restored-code"
        recovery = restore_runtime(root, revision, runtime)
        first = task_root / "run-a"
        second = task_root / "run-b"
        payload = launch_worker(runtime, evidence_root, first)
        launch_worker(runtime, evidence_root, second)
        require_artifact_equality(first, second)
        absent = task_root / "no-evidence"
        absent.mkdir()
        launch_worker(runtime, absent, task_root / "must-not-write", expect_failure=True)
        report = {
            "schema_version": "technical_diagnostic_e2e_acceptance_v1",
            "diagnostic_only": True, "official_selection": False,
            "real_pit_strategy_run": False, "production_reader_ready": False,
            "git_recovery": recovery, "integrity": summary,
            "artifacts": artifact_hashes(first), "independent_process_runs": 2,
            "artifact_bytes_equal": True, "missing_raw_evidence_failed_closed": True,
            "pipeline_logical_content_hash": payload["logical_content_hash"],
            "real_sample_decisions": [
                {"sample_id": item["sample_id"], "kind": item["decision"]["kind"]}
                for item in payload["real_samples"]],
            "synthetic_controls": payload["synthetic_controls"],
            "negative_controls": payload["negative_controls"],
            "no_new_field_evidence_or_readiness_changes": True,
            "serialization": "canonical_utf8_sorted_keys_no_runtime_clock_except_own_hash",
        }
        report["logical_content_hash"] = base.logical_content_hash(report)
        raw = base.canonical_bytes(report) + b"\n"
        markdown = render_markdown(report).encode("utf-8")
        if check:
            if (output / SUMMARY).read_bytes() != raw or (output / MARKDOWN).read_bytes() != markdown:
                raise ValueError("frozen E2E acceptance report differs")
            require_artifact_equality(first, output)
        else:
            output.mkdir(parents=True, exist_ok=False)
            for item in artifact_hashes(first):
                target = output / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(first / item["path"], target)
            (output / SUMMARY).write_bytes(raw)
            (output / MARKDOWN).write_bytes(markdown)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / DEFAULT_OUTPUT)
    parser.add_argument("--evidence-root", type=Path, default=ROOT)
    parser.add_argument("--revision", default="HEAD", help="committed code to restore")
    parser.add_argument("--check", action="store_true", help="reproduce/check without rewriting outputs")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.check:
            parser.error("worker cannot use --check")
        result = run_worker(args.evidence_root.resolve(), args.output_dir.resolve())
    else:
        result = run_e2e(ROOT, args.evidence_root.resolve(), args.output_dir.resolve(),
                         args.revision, check=args.check)
    print(base.canonical_bytes({"diagnostic_only": True,
                                "logical_content_hash": result["logical_content_hash"]}).decode("utf-8"))


if __name__ == "__main__":
    main()
