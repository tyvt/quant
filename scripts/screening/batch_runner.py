"""Bounded synthetic orchestration, unlimited queues, content-keyed memory cache."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path

from scripts.screening.basic_filter import basic_filter
from scripts.screening.contracts import BatchRequest, content_hash
from scripts.screening.hard_gates import GATE_ORDER, hard_gates
from scripts.screening.result_classifier import classify, evidence_backlog


ROOT = Path(__file__).resolve().parents[2]
RULE_VERSION = "v1.3.2"
RULE_SHA256 = "db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812"
SOURCE_PATHS = (
    "turtle_quant/core/result.py", "turtle_quant/core/types.py",
    "turtle_quant/core/share_capital_policy.py", "turtle_quant/pipeline/decision.py",
    "turtle_quant/premise/general_fcf.py", "turtle_quant/strategy/selection.py",
    "scripts/screening/__init__.py", "scripts/screening/contracts.py",
    "scripts/screening/basic_filter.py", "scripts/screening/hard_gates.py",
    "scripts/screening/result_classifier.py", "scripts/screening/batch_runner.py",
    "scripts/screening/demo.py", "scripts/run_batch_screening.py",
)


def implementation_identity(root: Path = ROOT) -> dict:
    rule_hash = hashlib.sha256((root / "RULE_SPEC.md").read_bytes()).hexdigest()
    if rule_hash != RULE_SHA256:
        raise ValueError("RULE_SPEC baseline drift; do not run against an unapproved identity")
    return {"rule_version": RULE_VERSION, "rule_sha256": rule_hash,
            "source_sha256": {path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                              for path in SOURCE_PATHS}}


@dataclass(frozen=True)
class BatchRun:
    report: dict
    evaluated_securities: int
    cache_hits: int


class BatchRunner:
    """Cache is process-local, defensive-copying, and not a PDF extraction cache.

    Cache keys include issuer, as_of, every normalized input, rule and code hashes.
    Chunk size and cache warmth are execution details, not output identity.
    """

    def __init__(self, root: Path = ROOT):
        self.root = root
        self._identity = implementation_identity(root)
        self._cache: dict[str, dict] = {}

    def run(self, request: BatchRequest, *, batch_size: int = 128) -> BatchRun:
        if not isinstance(request, BatchRequest):
            raise ValueError("request must be a validated BatchRequest")
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        identity = implementation_identity(self.root)
        if identity != self._identity:
            raise ValueError("implementation changed during session; restart with reviewed code")
        normalized = request.normalized()
        by_id = {item.security_id: item for item in request.inputs}
        normalized_by_id = {item["security_id"]: item for item in normalized["inputs"]}
        rows, evaluated, hits = [], 0, 0
        # Process every requested ID, including absent records. Never silently drop one.
        for start in range(0, len(request.security_ids), batch_size):
            for security_id in request.security_ids[start:start + batch_size]:
                cache_key = content_hash({"identity": identity, "schema": request.schema,
                                          "data_kind": request.data_kind,
                                          "as_of": request.as_of, "security_id": security_id,
                                          "inputs": normalized_by_id.get(security_id)})
                if cache_key in self._cache:
                    row = deepcopy(self._cache[cache_key])
                    hits += 1
                else:
                    record = by_id.get(security_id)
                    basic = basic_filter(record.basic if record else None)
                    enterprise = (hard_gates(record.financial if record else None)
                                  if basic["status"] == "ELIGIBLE" else [])
                    row = {"security_id": security_id, "basic": basic,
                           "enterprise_gates": enterprise,
                           "enterprise_stage": "EVALUATED" if enterprise else "NOT_RUN",
                           "not_run_reason": None if enterprise else "basic_screen_not_eligible",
                           **classify(basic, enterprise)}
                    self._cache[cache_key] = deepcopy(row)
                    evaluated += 1
                rows.append(row)
        queues = {key: [row["security_id"] for row in rows if row["work_queue"] == key]
                  for key in ("PASSED", "STOPPED", "NEEDS_EVIDENCE")}
        report = {
            "schema": request.schema, "data_kind": request.data_kind,
            "purpose": "SYNTHETIC_BATCH_HARD_GATE_DIAGNOSTIC",
            "diagnostic_only": True, "official_selection": False,
            "real_pit_run_authorized": False, "whole_month_eligibility": "NOT_EVALUATED",
            "as_of": request.as_of.isoformat(), "identity": identity,
            "input_content_hash": content_hash(normalized),
            "gate_display_order": list(GATE_ORDER),
            "security_order": "SECURITY_ID_ONLY_NOT_RANKING",
            "requested_security_ids": list(request.security_ids),
            "rows": rows, "queues": queues,
            "evidence_backlog": evidence_backlog(rows),
            "counts": {key: len(values) for key, values in queues.items()},
            "contains_needs_review": bool(queues["NEEDS_EVIDENCE"]),
        }
        report["logical_content_hash"] = content_hash(report)
        return BatchRun(report, evaluated, hits)
