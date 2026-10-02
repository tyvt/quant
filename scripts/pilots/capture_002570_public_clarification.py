"""Capture bounded public clarification checks, never certify a revision chain.

Catalogue searches cover 2025-04-01 through 2026-10-01 for one issuer. Detail
responses are current observations, not historical withdrawal logs or verified
first-publication clocks. Only explicit official requests are made; no questions
are submitted, existing directories are refused, and no publisher is imported.
Requires requests. Numerical and audit-scope interpretation remain separate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import requests


CODE, ORG = "002570", "9900019035"
CATALOGUE_ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
DETAIL_ENDPOINT = "https://www.cninfo.com.cn/new/announcement/bulletin_detail"
BASE_PAYLOAD = {
    "stock": f"{CODE},{ORG}", "column": "szse", "plate": "sz",
    "pageNum": 1, "pageSize": 30, "tabName": "fulltext",
    "seDate": "2025-04-01~2026-10-01", "sortName": "time",
    "sortType": "desc", "isHLtitle": "false",
}
QUERY_KEYS = (
    "财务报表更正", "专项鉴证", "更正", "澄清", "审计报告", "撤回",
    "重新审计", "2024年报问询", "2024年年度报告",
    "2024年度履职情况", "2025年度履职情况", "关于回复",
)
DETAIL_TARGETS = (
    ("original_annual", "1216702448", "2023-04-29", "PDF"),
    ("first_corrected_annual", "1219043674", "2024-01-31", "PDF"),
    ("second_corrected_annual", "1223388226", "2025-04-29", "PDF"),
    ("second_correction_special_review", "1223478760", "2025-05-07", "PDF"),
)
# Raw clocks already fixed in the previous capture, not inferred availability.
DETAIL_CLOCKS = {
    "1216702448": 1682697600000, "1219043674": 1706630400000,
    "1223388226": 1745856000000, "1223478760": 1746547200000,
}
PDF_TARGETS = (
    ("audit_2024", "1223388231", "2025-04-29", "pdf"),
    ("auditor_performance_2024", "1223388222", "2025-04-29", "PDF"),
    ("auditor_performance_2025", "1225221537", "2026-04-28", "PDF"),
)
DETAIL_PAGE = (
    "https://www.cninfo.com.cn/new/disclosure/detail?plate=szse&orgId=9900019035"
    "&stockCode=002570&announcementId=1223478760&announcementTime=2025-05-07"
)
DETAIL_SCRIPT = (
    "https://static.cninfo.com.cn/new/assets/js/disclosure/notice-detail.js"
    "?v=20260710082532"
)
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_catalogue(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=unique_keys)
    if not isinstance(value, dict):
        raise ValueError("catalogue response must be an object")
    rows, total = value.get("announcements"), value.get("totalAnnouncement")
    if type(total) is not int or total < 0 or value.get("hasMore") is not False:
        raise ValueError("catalogue completeness not established")
    # This endpoint represents an empty result as null, not always as [].
    # Only its explicit zero counters certify an empty query response.
    if rows is None:
        if total != 0 or any(
            type(value.get(key)) is not int or value[key] != 0
            for key in ("totalRecordNum", "totalpages")
        ):
            raise ValueError("null rows without explicit empty-query counters")
        rows = []
    if not isinstance(rows, list) or len(rows) != total:
        raise ValueError("one-page catalogue is incomplete")
    found = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("secCode") != CODE or row.get("orgId") != ORG:
            raise ValueError("catalogue security identity drift")
        identifier = row.get("announcementId")
        if type(identifier) is not str or not identifier or identifier in found:
            raise ValueError("invalid or duplicate announcement identity")
        if type(row.get("announcementTime")) is not int:
            raise ValueError("catalogue timestamp missing")
        if not isinstance(row.get("announcementTitle"), str) or not row["announcementTitle"].strip():
            raise ValueError("catalogue title missing")
        found[identifier] = row
    return found


def merge_catalogues(catalogues: list[dict]) -> dict:
    found = {}
    for rows in catalogues:
        for identifier, row in rows.items():
            if identifier in found and found[identifier] != row:
                raise ValueError("cross-query catalogue drift")
            found[identifier] = row
    for _, identifier, day, suffix in PDF_TARGETS:
        row = found.get(identifier)
        if row is None or row.get("adjunctUrl") != f"finalpage/{day}/{identifier}.{suffix}":
            raise ValueError(f"required PDF missing or URL drift: {identifier}")
    return found


def parse_detail(raw: bytes, target: tuple) -> dict:
    value = json.loads(raw, object_pairs_hook=unique_keys)
    row = value.get("announcement") if isinstance(value, dict) else None
    role, identifier, day, suffix = target
    path = f"finalpage/{day}/{identifier}.{suffix}"
    if not isinstance(row, dict) or any((
        row.get("secCode") != CODE, row.get("orgId") != ORG,
        row.get("announcementId") != identifier, row.get("adjunctUrl") != path,
    )):
        raise ValueError("detail identity or URL drift")
    if type(row.get("announcementTime")) is not int:
        raise ValueError("detail timestamp missing")
    if row["announcementTime"] != DETAIL_CLOCKS[identifier]:
        raise ValueError("detail raw clock drift from fixed catalogue")
    if value.get("fileUrl") not in (f"http://static.cninfo.com.cn/{path}", f"https://static.cninfo.com.cn/{path}"):
        raise ValueError("detail file URL drift")
    return {
        "role": role, "announcement_id": identifier,
        "catalogue_time_raw_ms": row["announcementTime"],
        "catalogue_time_utc": datetime.fromtimestamp(
            row["announcementTime"] / 1000, timezone.utc
        ).isoformat(),
        "associate_announcement_raw": row.get("associateAnnouncement"),
        "storage_time_raw": row.get("storageTime"),
        "bulletin_status_raw": value.get("bulletinStatus"),
        "returned_file_url": value["fileUrl"],
        "exact_available_at_utc": None,
        "withdrawal_or_platform_replacement_verified": False,
        "earliest_public_availability_verified": False,
    }


def capture(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("capture directory already exists; refusing to overwrite")
    output.mkdir(parents=True, exist_ok=False)
    resources = []

    def fetch(name, method, url, *, data=None, params=None):
        started = datetime.now(timezone.utc).isoformat()
        response = requests.request(
            method, url, data=data, params=params, headers=HEADERS,
            timeout=20, allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError(f"official request failed: {name}, HTTP {response.status_code}")
        raw = response.content
        with (output / name).open("xb") as target:
            target.write(raw)
        resource = {
            "name": name, "method": method, "url": url,
            "request_data": data, "request_params": params,
            "local_path": (output / name).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "request_started_at_utc": started,
            "response_received_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        resources.append(resource)
        return raw, resource

    catalogues, parsed = [], []
    for number, key in enumerate(QUERY_KEYS, 1):
        raw, resource = fetch(
            f"catalogue-{number}.json", "POST", CATALOGUE_ENDPOINT,
            data={**BASE_PAYLOAD, "searchkey": key},
        )
        rows = parse_catalogue(raw)
        parsed.append(rows)
        catalogues.append({
            "resource": resource["name"], "searchkey": key,
            "reported_total": len(rows), "returned_count": len(rows),
            "announcement_ids": list(rows),
            "completeness_scope": "this_filtered_response_not_revision_universe",
            "empty_result_proves_absence_of_event": False,
        })
    found = merge_catalogues(parsed)
    page_raw, _ = fetch("detail-page.html", "GET", DETAIL_PAGE)
    script_raw, _ = fetch("notice-detail.js", "GET", DETAIL_SCRIPT)
    if b"notice-detail.js" not in page_raw or b"/announcement/bulletin_detail" not in script_raw:
        raise ValueError("public detail frontend endpoint provenance drift")
    details = []
    for target in DETAIL_TARGETS:
        role, identifier, day, _ = target
        raw, resource = fetch(
            f"detail-{identifier}.json", "POST", DETAIL_ENDPOINT,
            params={"announceId": identifier, "flag": "true", "announceTime": day},
        )
        details.append({**parse_detail(raw, target), "resource": resource["name"]})
    documents = []
    for role, identifier, day, suffix in PDF_TARGETS:
        path = f"finalpage/{day}/{identifier}.{suffix}"
        raw, resource = fetch(
            f"{role}-{identifier}.pdf", "GET", f"https://static.cninfo.com.cn/{path}"
        )
        if not raw.startswith(b"%PDF-"):
            raise ValueError(f"legal PDF signature missing: {identifier}")
        row = found[identifier]
        documents.append({
            "role": role, "announcement_id": identifier, "resource": resource["name"],
            "catalogue_title": row["announcementTitle"],
            "catalogue_time_raw_ms": row["announcementTime"],
            "exact_available_at_utc": None,
        })
    result = {
        "schema_version": "bounded_public_clarification_capture_v1",
        "security_id": "sz.002570", "target_period_end": "2022-12-31",
        "purpose": "public_source_gap_diagnosis_only",
        "capture_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "catalogues": catalogues, "details": details, "documents": documents,
        "resources": resources, "research_eligible": False,
        "snapshot_published": False, "production_reader_ready": False,
        "complete_revision_chain_verified": False,
        "exact_available_at_utc": None,
    }
    with (output / "capture.json").open("x", encoding="utf-8", newline="\n") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
        target.write("\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = capture(args.output)
    print(json.dumps({
        "capture_manifest": (args.output / "capture.json").as_posix(),
        "resource_count": len(result["resources"]),
        "catalogue_counts": [x["returned_count"] for x in result["catalogues"]],
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
