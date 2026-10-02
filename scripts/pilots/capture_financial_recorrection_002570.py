"""Fix a bounded 002570 core-statement re-correction probe, not a PIT snapshot.

Four explicit catalogue queries and eight official PDFs cover observations of
the 2022 statements. Query completeness is not historical-version completeness;
catalogue clocks are not verified earliest public availability. No production
Reader or publisher is called, and existing capture directories are refused.
Requires requests. Interpretation and numerical reconciliation are separate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import requests


ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
SECURITY_CODE = "002570"
ORG_ID = "9900019035"
BASE_PAYLOAD = {
    "stock": f"{SECURITY_CODE},{ORG_ID}", "column": "szse", "plate": "sz",
    "pageNum": 1, "pageSize": 30, "tabName": "fulltext",
    "seDate": "2023-01-01~2025-06-30", "sortName": "time",
    "sortType": "desc", "isHLtitle": "false",
}
QUERY_KEYS = ("2022年年度报告", "会计差错", "年报问询函", "财务报表更正")
TARGETS = (
    ("original_annual", "1216702448", "2023-04-29"),
    ("first_corrected_annual", "1219043674", "2024-01-31"),
    ("second_corrected_annual", "1223388226", "2025-04-29"),
    ("first_correction_notice", "1219043656", "2024-01-31"),
    ("first_correction_special_review", "1219043661", "2024-01-31"),
    ("second_correction_notice", "1223388206", "2025-04-29"),
    ("second_correction_special_review", "1223478760", "2025-05-07"),
    ("auditor_2023_inquiry_reply", "1220361222", "2024-06-15"),
)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate catalogue JSON key: {key}")
        result[key] = value
    return result


def catalogue_rows(raw: bytes) -> dict:
    response = json.loads(raw, object_pairs_hook=_unique_keys)
    if not isinstance(response, dict):
        raise ValueError("catalogue response must be an object")
    rows = response.get("announcements")
    total = response.get("totalAnnouncement")
    if type(total) is not int or not isinstance(rows, list) or total != len(rows):
        raise ValueError("one-page probe catalogue is incomplete")
    by_id = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("catalogue row must be an object")
        if row.get("secCode") != SECURITY_CODE or row.get("orgId") != ORG_ID:
            raise ValueError("catalogue security identity drift")
        identifier = row.get("announcementId")
        if type(identifier) is not str or not identifier or identifier in by_id:
            raise ValueError("invalid or duplicate announcement identity")
        by_id[identifier] = row
    return by_id


def target_rows(catalogues: list[dict]) -> dict:
    found = {}
    for catalogue in catalogues:
        for identifier, row in catalogue.items():
            if identifier in found and found[identifier] != row:
                raise ValueError("cross-query catalogue identity/content drift")
            found[identifier] = row
    selected = {}
    for _, identifier, day in TARGETS:
        row = found.get(identifier)
        if row is None or row.get("adjunctUrl") != f"finalpage/{day}/{identifier}.PDF":
            raise ValueError(f"required legal document missing or URL drift: {identifier}")
        if type(row.get("announcementTime")) is not int:
            raise ValueError("catalogue timestamp missing")
        selected[identifier] = row
    return selected


def capture(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("capture directory already exists; refusing to overwrite")
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}
    responses = []
    for key in QUERY_KEYS:
        payload = {**BASE_PAYLOAD, "searchkey": key}
        started = datetime.now(timezone.utc).isoformat()
        response = requests.post(
            ENDPOINT, data=payload, headers=headers, timeout=20, allow_redirects=False
        )
        if response.status_code != 200:
            raise ValueError(f"catalogue request failed: HTTP {response.status_code}")
        raw = response.content
        rows = catalogue_rows(raw)
        responses.append((payload, raw, rows, started))
    selected = target_rows([rows for _, _, rows, _ in responses])
    output.mkdir(parents=True, exist_ok=False)
    catalogue_metadata = []
    for number, (payload, raw, rows, started) in enumerate(responses, 1):
        filename = f"catalogue-{number}.json"
        with (output / filename).open("xb") as target:
            target.write(raw)
        catalogue_metadata.append({
            "endpoint": ENDPOINT, "payload": payload,
            "local_path": (output / filename).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "reported_total": len(rows), "returned_count": len(rows),
            "request_started_at_utc": started,
            "completeness_scope": "this_query_response_only_not_entire_revision_history",
        })
    documents = []
    for role, identifier, day in TARGETS:
        url = f"https://static.cninfo.com.cn/finalpage/{day}/{identifier}.PDF"
        started = datetime.now(timezone.utc).isoformat()
        response = requests.get(url, headers=headers, timeout=20, allow_redirects=False)
        if response.status_code != 200 or not response.content.startswith(b"%PDF-"):
            raise ValueError(f"legal PDF request failed: {identifier}, HTTP {response.status_code}")
        filename = f"{role}-{identifier}.pdf"
        with (output / filename).open("xb") as target:
            target.write(response.content)
        row = selected[identifier]
        documents.append({
            "role": role, "announcement_id": identifier, "source_url": url,
            "local_path": (output / filename).as_posix(),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "bytes": len(response.content), "request_started_at_utc": started,
            "catalogue_title": row["announcementTitle"],
            "catalogue_time_raw_ms": row["announcementTime"],
            "catalogue_time_utc": datetime.fromtimestamp(
                row["announcementTime"] / 1000, timezone.utc
            ).isoformat(),
            "associate_announcement": row.get("associateAnnouncement"),
            "storage_time": row.get("storageTime"),
            "exact_available_at_utc": None,
        })
    return {
        "schema_version": "legal_pdf_core_financial_recorrection_capture_v1",
        "security_id": "sz.002570", "period_end": "2022-12-31",
        "purpose": "technical_core_financial_revision_probe_only",
        "capture_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_eligible": False, "snapshot_published": False,
        "production_reader_ready": False, "complete_revision_chain_verified": False,
        "withdrawal_or_platform_replacement_verified": False,
        "exact_available_at_utc": None,
        "catalogues": catalogue_metadata, "documents": documents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print(json.dumps(capture(parser.parse_args().output), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
