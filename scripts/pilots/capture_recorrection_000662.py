"""Capture one public legal-PDF revision probe; never publish a PIT snapshot.

This is restricted to 000662's April 2009 disclosure catalogue and the six
specified legal documents. The catalogue timestamp is an observed source
field, not proof of earliest public availability. Existing captures are never
overwritten. Requires requests; PDF interpretation is a separate review.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import requests


ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
PAYLOAD = {
    "stock": "000662,gssz0000662", "column": "szse", "plate": "sz",
    "pageNum": 1, "pageSize": 30, "tabName": "fulltext",
    "seDate": "2009-04-01~2009-04-30", "searchkey": "",
    "sortName": "time", "sortType": "desc", "isHLtitle": "true",
}
TARGETS = (
    ("original_annual", "51114405", "2009-04-10"),
    ("original_audit", "51114401", "2009-04-10"),
    ("first_corrected_annual", "51167822", "2009-04-11"),
    ("first_correction_notice", "51167823", "2009-04-11"),
    ("second_corrected_annual", "51681509", "2009-04-24"),
    ("second_correction_notice", "51681510", "2009-04-24"),
)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate catalogue JSON key: {key}")
        result[key] = value
    return result


def select_rows(raw: bytes) -> tuple[int, dict]:
    response = json.loads(raw, object_pairs_hook=_unique_keys)
    rows = response.get("announcements")
    total = response.get("totalAnnouncement")
    if type(total) is not int or not isinstance(rows, list) or total != len(rows):
        raise ValueError("one-page probe catalogue is incomplete")
    by_id = {}
    for row in rows:
        if row.get("secCode") != "000662" or row.get("orgId") != "gssz0000662":
            raise ValueError("catalogue security identity drift")
        identifier = row.get("announcementId")
        if type(identifier) is not str or identifier in by_id:
            raise ValueError("invalid or duplicate announcement identity")
        by_id[identifier] = row
    for _, identifier, day in TARGETS:
        row = by_id.get(identifier)
        if row is None or row.get("adjunctUrl") != f"finalpage/{day}/{identifier}.PDF":
            raise ValueError(f"required legal document missing or URL drift: {identifier}")
        if type(row.get("announcementTime")) is not int:
            raise ValueError("catalogue timestamp missing")
    return total, by_id


def capture(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("capture directory already exists; refusing to overwrite")
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}
    response = requests.post(
        ENDPOINT, data=PAYLOAD, headers=headers, timeout=20, allow_redirects=False
    )
    if response.status_code != 200:
        raise ValueError(f"catalogue request failed: HTTP {response.status_code}")
    raw = response.content
    total, by_id = select_rows(raw)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "catalogue.json").open("xb") as target:
        target.write(raw)
    documents = []
    for role, identifier, day in TARGETS:
        url = f"https://static.cninfo.com.cn/finalpage/{day}/{identifier}.PDF"
        document = requests.get(url, headers=headers, timeout=20, allow_redirects=False)
        if document.status_code != 200 or not document.content.startswith(b"%PDF-"):
            raise ValueError(f"legal PDF request failed: {identifier}, HTTP {document.status_code}")
        filename = f"{role}-{identifier}.pdf"
        with (output / filename).open("xb") as target:
            target.write(document.content)
        row = by_id[identifier]
        documents.append({
            "role": role, "announcement_id": identifier,
            "source_url": url, "local_path": (output / filename).as_posix(),
            "sha256": hashlib.sha256(document.content).hexdigest(),
            "bytes": len(document.content), "catalogue_title": row["announcementTitle"],
            "catalogue_time_raw_ms": row["announcementTime"],
            "catalogue_time_utc": datetime.fromtimestamp(
                row["announcementTime"] / 1000, timezone.utc
            ).isoformat(),
            "associate_announcement": row.get("associateAnnouncement"),
            "storage_time": row.get("storageTime"),
            "exact_available_at_utc": None,
        })
    return {
        "schema_version": "legal_pdf_recorrection_capture_v1",
        "security_id": "sz.000662", "period_end": "2008-12-31",
        "purpose": "technical_legal_pdf_revision_probe_only",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_eligible": False, "snapshot_published": False,
        "production_reader_ready": False, "complete_revision_chain_verified": False,
        "exact_available_at_utc": None,
        "catalogue": {
            "endpoint": ENDPOINT, "payload": PAYLOAD,
            "local_path": (output / "catalogue.json").as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "reported_total": total, "returned_count": total,
            "completeness_scope": "this_query_response_only_not_entire_revision_history",
        },
        "documents": documents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(capture(args.output), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
