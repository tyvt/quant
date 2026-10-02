"""Fix two 2024 annual PDFs and three bounded current catalogue responses.

One issuer, explicit document identities, no redirects or fallback. A complete
filtered response is not a complete historical revision/withdrawal chain, and
catalogue clocks are never promoted to verified historical availability.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import requests


CODE, ORG = "000637", "gssz0000637"
ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
PAYLOAD = {
    "stock": f"{CODE},{ORG}", "column": "szse", "plate": "sz",
    "pageNum": 1, "pageSize": 30, "tabName": "fulltext",
    "seDate": "2025-01-01~2026-10-02", "sortName": "time",
    "sortType": "desc", "isHLtitle": "false",
}
QUERIES = ("2024年年度报告", "更正", "撤回")
TARGETS = (
    ("original_2024_annual_report", "1223369814", "2025-04-29", "2024年年度报告"),
    ("amended_2024_annual_report", "1225460241", "2026-08-06", "2024年年度报告（更正后）"),
)
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}


def strict_json(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"nonfinite JSON number: {value}")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def parse_catalogue(raw: bytes) -> dict:
    value = strict_json(raw)
    if not isinstance(value, dict):
        raise ValueError("catalogue response must be an object")
    total = value.get("totalAnnouncement")
    # CNINFO currently returns totalpages=0 for complete sub-page responses.
    # Accept only this fixed one-page response shape; never silently truncate.
    if (type(total) is not int or not 0 <= total <= PAYLOAD["pageSize"]
            or type(value.get("totalRecordNum")) is not int
            or value["totalRecordNum"] != total
            or type(value.get("totalpages")) is not int or value["totalpages"] != 0
            or value.get("hasMore") is not False):
        raise ValueError("bounded one-page catalogue completeness not established")
    rows = value.get("announcements")
    if rows is None and total == 0:
        rows = []
    if not isinstance(rows, list) or len(rows) != total:
        raise ValueError("catalogue count mismatch")
    found = {}
    for row in rows:
        if (not isinstance(row, dict) or row.get("secCode") != CODE
                or row.get("orgId") != ORG):
            raise ValueError("catalogue security identity drift")
        identifier = row.get("announcementId")
        if (not isinstance(identifier, str) or not re.fullmatch(r"[0-9]+", identifier)
                or identifier in found):
            raise ValueError("invalid or duplicate announcement identity")
        if (type(row.get("announcementTime")) is not int
                or not isinstance(row.get("announcementTitle"), str)
                or not row["announcementTitle"].strip()
                or not isinstance(row.get("adjunctUrl"), str)
                or not re.fullmatch(rf"finalpage/\d{{4}}-\d{{2}}-\d{{2}}/{identifier}\.[Pp][Dd][Ff]",
                                    row["adjunctUrl"])):
            raise ValueError("catalogue clock, title or PDF URL missing/drifted")
        found[identifier] = row
    return found


def merge_catalogues(catalogues: list[dict]) -> dict:
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
            raise ValueError(f"required annual PDF missing or identity drift: {identifier}")
    return found


def capture(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("capture directory exists; refusing to overwrite")
    output.mkdir(parents=True, exist_ok=False)
    resources = []

    def fetch(name, method, url, data=None):
        started = datetime.now(timezone.utc).isoformat()
        response = requests.request(method, url, data=data, headers=HEADERS,
                                    timeout=30, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f"official request failed: HTTP {response.status_code}")
        raw = response.content
        with (output / name).open("xb") as target:
            target.write(raw)
        resource = {
            "name": name, "local_path": (output / name).as_posix(),
            "method": method, "url": url, "request_data": data,
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "request_started_at_utc": started,
            "response_received_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        resources.append(resource)
        return raw, resource

    catalogues, parsed = [], []
    for number, key in enumerate(QUERIES, 1):
        raw, resource = fetch(f"catalogue-{number}.json", "POST", ENDPOINT,
                              {**PAYLOAD, "searchkey": key})
        rows = parse_catalogue(raw)
        parsed.append(rows)
        catalogues.append({
            "resource": resource["name"], "searchkey": key,
            "reported_total": len(rows), "announcement_ids": list(rows),
            "completeness_scope": "FILTERED_CURRENT_RESPONSE_ONLY",
            "empty_result_proves_no_withdrawal": False,
        })
    found = merge_catalogues(parsed)
    documents = []
    for role, identifier, day, _ in TARGETS:
        raw, resource = fetch(f"{role}-{identifier}.pdf", "GET",
                              f"https://static.cninfo.com.cn/finalpage/{day}/{identifier}.PDF")
        if not raw.startswith(b"%PDF-"):
            raise ValueError("legal PDF signature missing")
        documents.append({
            "role": role, "announcement_id": identifier, "resource": resource["name"],
            "catalogue_title": found[identifier]["announcementTitle"],
            "catalogue_time_raw_ms": found[identifier]["announcementTime"],
            "exact_available_at_utc": None,
        })
    result = {
        "schema_version": "financial_2024_000637_capture_v1", "security_id": "sz.000637",
        "target_period_end": "2024-12-31", "resources": resources,
        "catalogues": catalogues, "documents": documents,
        "capture_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete_revision_chain_verified": False, "snapshot_published": False,
        "production_reader_ready": False, "research_eligible": False,
        "exact_available_at_utc": None,
    }
    with (output / "capture.json").open("x", encoding="utf-8", newline="\n") as target:
        json.dump(result, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    result = capture(parser.parse_args().output)
    print(json.dumps({"resources": len(result["resources"]),
                      "catalogue_counts": [x["reported_total"] for x in result["catalogues"]]}))


if __name__ == "__main__":
    main()
