"""Fix an explicit 2021 annual and a separately classified event correction.

Only the current bounded title-filtered catalogue is checked for completeness.
No historical revision-chain, earliest-availability or production-ready claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots import capture_financial_2024_000637 as previous

ENDPOINT = previous.ENDPOINT
PAYLOAD = {**previous.PAYLOAD, "seDate": "2022-01-01~2026-10-02"}
QUERIES = ("2021年年度报告", "更正", "撤回")
ANNUAL = ("original_2021_annual_report", "1212743936", "2022-03-31", "2021年年度报告")
NOTICE = ("performance_meeting_correction", "1212765280", "2022-04-01", "关于召开2021年度业绩说明会的更正公告")
TARGETS = (ANNUAL, NOTICE)


def merge_catalogues(catalogues):
    found = {}
    for rows in catalogues:
        for identifier, row in rows.items():
            if identifier in found and found[identifier] != row:
                raise ValueError("cross-query catalogue drift")
            found[identifier] = row
    for _, identifier, day, title in TARGETS:
        row = found.get(identifier)
        if (row is None or row["announcementTitle"] != title
                or row["adjunctUrl"] != f"finalpage/{day}/{identifier}.PDF"):
            raise ValueError(f"required explicit PDF missing or identity drift: {identifier}")
    return found


def capture(output):
    if output.exists():
        raise FileExistsError("capture directory exists; refusing to overwrite")
    output.mkdir(parents=True, exist_ok=False)
    resources = []

    def fetch(name, method, url, data=None):
        started = datetime.now(timezone.utc).isoformat()
        response = previous.requests.request(method, url, data=data, headers=previous.HEADERS,
                                              timeout=30, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f"official request failed: HTTP {response.status_code}")
        raw = response.content
        with (output / name).open("xb") as target:
            target.write(raw)
        resource = {"name": name, "local_path": (output / name).as_posix(), "method": method,
                    "url": url, "request_data": data, "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw), "request_started_at_utc": started,
                    "response_received_at_utc": datetime.now(timezone.utc).isoformat()}
        resources.append(resource)
        return raw, resource

    catalogues, parsed = [], []
    for number, query in enumerate(QUERIES, 1):
        raw, resource = fetch(f"catalogue-{number}.json", "POST", ENDPOINT, {**PAYLOAD, "searchkey": query})
        rows = previous.parse_catalogue(raw)
        parsed.append(rows)
        catalogues.append({"resource": resource["name"], "searchkey": query,
                           "reported_total": len(rows), "announcement_ids": list(rows),
                           "completeness_scope": "FILTERED_CURRENT_RESPONSE_ONLY",
                           "empty_result_proves_no_withdrawal": False})
    found = merge_catalogues(parsed)
    documents = []
    for role, identifier, day, title in TARGETS:
        raw, resource = fetch(f"{role}-{identifier}.pdf", "GET",
                              f"https://static.cninfo.com.cn/finalpage/{day}/{identifier}.PDF")
        if not raw.startswith(b"%PDF-"):
            raise ValueError("legal PDF signature missing")
        documents.append({"role": role, "announcement_id": identifier, "resource": resource["name"],
                          "catalogue_title": title, "catalogue_time_raw_ms": found[identifier]["announcementTime"],
                          "exact_available_at_utc": None})
    result = {"schema_version": "financial_2021_000637_capture_v1", "security_id": "sz.000637",
              "target_period_end": "2021-12-31", "resources": resources, "catalogues": catalogues,
              "documents": documents, "capture_completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "complete_revision_chain_verified": False, "snapshot_published": False,
              "production_reader_ready": False, "research_eligible": False, "exact_available_at_utc": None}
    with (output / "capture.json").open("x", encoding="utf-8", newline="\n") as target:
        json.dump(result, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    result = capture(parser.parse_args().output)
    print(json.dumps({"resources": len(result["resources"]),
                      "catalogue_counts": [item["reported_total"] for item in result["catalogues"]]}))


if __name__ == "__main__":
    main()
