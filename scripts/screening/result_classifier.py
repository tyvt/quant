"""Operational queues, not investment decisions or official candidate status."""

from scripts.screening.hard_gates import GATE_ORDER


def classify(basic: dict, gates: list[dict]) -> dict:
    failed = [item["rule_id"] for item in gates if item["status"] == "FAIL"]
    unknown = [item["rule_id"] for item in gates
               if item["status"] in ("UNKNOWN", "NEEDS_REVIEW")]
    status = basic["status"]
    if status == "ELIGIBLE":
        if [item["rule_id"] for item in gates] != list(GATE_ORDER):
            raise ValueError("complete six-gate results are required")
        statuses = {item["status"] for item in gates}
        if not statuses <= {"PASS", "FAIL", "UNKNOWN", "NEEDS_REVIEW", "NOT_SUPPORTED"}:
            raise ValueError("unsupported hard-gate status")
        if gates[0]["status"] == "NOT_SUPPORTED":
            queue, premise_status = "STOPPED", "NOT_SUPPORTED"
        elif unknown:
            queue, premise_status = "NEEDS_EVIDENCE", "NEEDS_REVIEW"
        elif failed:
            queue, premise_status = "STOPPED", "FAIL"
        elif statuses == {"PASS"}:
            queue, premise_status = "PASSED", "PASS"
        else:
            raise ValueError("unsupported gate combination")
    elif status in ("REJECTED", "NOT_SUPPORTED"):
        queue, premise_status = "STOPPED", "NOT_RUN"
    elif status == "NEEDS_REVIEW":
        queue, premise_status = "NEEDS_EVIDENCE", "NOT_RUN"
    else:
        raise ValueError("unknown universe status")
    unsupported = status == "NOT_SUPPORTED" or premise_status == "NOT_SUPPORTED"
    return {
        "work_queue": queue, "premise_status": premise_status,
        "known_failed_gate_ids": failed, "unknown_gate_ids": unknown,
        "out_of_scope": unsupported,
        "known_failure": status == "REJECTED" or bool(failed),
        "stop_additional_deep_work": queue == "STOPPED" or bool(failed),
        "detailed_analysis_eligible": queue == "PASSED",
    }


def evidence_backlog(rows: list[dict]) -> list[dict]:
    """Group shared gaps without initiating repeated source searches."""
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for row in rows:
        if row["work_queue"] != "NEEDS_EVIDENCE":
            continue
        for reason in row["basic"]["reasons"]:
            grouped.setdefault(("BASIC", "universe", reason), set()).add(row["security_id"])
        for gate in row["enterprise_gates"]:
            if gate["status"] not in ("UNKNOWN", "NEEDS_REVIEW"):
                continue
            gaps = gate["missing_fields"] or gate["notes"] or ["evidence_unknown"]
            for gap in gaps:
                grouped.setdefault(("ENTERPRISE", gate["rule_id"], gap), set()).add(row["security_id"])
    return [{"stage": stage, "rule_id": rule_id, "gap": gap,
             "security_ids": sorted(ids)}
            for (stage, rule_id, gap), ids in sorted(grouped.items())]
