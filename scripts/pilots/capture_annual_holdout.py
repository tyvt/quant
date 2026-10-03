"""Capture one explicitly planned official annual PDF without reading its body.

Only a bounded catalogue and the exact PDF are fetched, without retries or
redirects. Page count is metadata, not a layout pre-inspection. Frozen parser
bytes are checked before and after capture; the unchanged CLI runs separately.
This is source acquisition for a blind diagnostic, never a production publisher.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import fitz
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import SOURCE_PATHS, read_scope
from scripts.pilots.capture_financial_2024_000637 import strict_json

ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}


def verify_parser(plan, root=ROOT):
    expected = plan["parser_code_sha256"]
    if set(expected) != set(SOURCE_PATHS):
        raise ValueError("incomplete frozen parser identity")
    for name, digest in expected.items():
        raw = (root / name).read_bytes()
        committed = subprocess.check_output(["git", "show", f"{plan['parser_commit']}:{name}"], cwd=root)
        if hashlib.sha256(raw).hexdigest() != digest or raw != committed:
            raise ValueError(f"pre-blind parser drift: {name}")


def select_source(raw, plan):
    value = strict_json(raw)
    rows = value.get("announcements") if isinstance(value, dict) else None
    total = value.get("totalAnnouncement") if isinstance(value, dict) else None
    if (type(total) is not int or not 1 <= total <= plan["catalogue_payload"]["pageSize"]
            or type(value.get("totalRecordNum")) is not int or value["totalRecordNum"] != total
            or type(value.get("totalpages")) is not int or value["totalpages"] != 0
            or value.get("hasMore") is not False or not isinstance(rows, list) or len(rows) != total):
        raise ValueError("bounded catalogue counts/pagination not established")
    source = plan["source"]
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("secCode") != source["security_id"].split(".")[1]
                or row.get("orgId") != source["org_id"]):
            raise ValueError("catalogue issuer drift")
        identifier = row.get("announcementId")
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9]+", identifier) or identifier in seen:
            raise ValueError("invalid/duplicate announcement ID")
        seen.add(identifier)
    matches = [row for row in rows if row["announcementId"] == source["announcement_id"]]
    if (len(matches) != 1 or matches[0].get("announcementTitle") != source["catalogue_title"]
            or matches[0].get("adjunctUrl") != source["url"].removeprefix("https://static.cninfo.com.cn/")
            or type(matches[0].get("announcementTime")) is not int):
        raise ValueError("explicit annual title/URL/clock drift")
    return matches[0]


def capture(plan_path, output, *, request=requests.request):
    plan_raw = plan_path.read_bytes()
    plan = strict_json(plan_raw)
    if plan.get("schema") != "annual-holdout-plan-v1":
        raise ValueError("unsupported holdout plan")
    protocol = plan["protocol"]
    if (protocol["pdf_body_inspected_before_first_run"] is not False
            or protocol["parser_edited_before_first_run"] is not False
            or protocol["capture_request_limit"] != 2 or protocol["fixes_in_this_run"] is not False):
        raise ValueError("not a fixed no-repair blind plan")
    verify_parser(plan)
    output = output.absolute()
    if output.resolve() != output or not output.is_relative_to(ROOT.resolve() / "storage/pilots"):
        raise ValueError("capture output must be an unlinked workspace pilot directory")
    # Validate the same URL and identity contract as the unchanged offline CLI.
    source = {key: plan["source"][key] for key in (
        "security_id", "issuer", "fiscal_year", "version", "announcement_id", "url")}
    source.update(pdf_path=(output / "annual.pdf").relative_to(ROOT).as_posix(),
                  pdf_sha256="0" * 64, page_count=1)
    scope = {"schema": "annual-source-bundle-scope-v1", "as_of": plan["as_of"],
             "sources": [source], "reference_reports": []}
    read_scope(json.dumps(scope).encode("utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    resources = []

    def fetch(name, method, url, data=None):
        started = datetime.now(timezone.utc).isoformat()
        response = request(method, url, data=data, headers=HEADERS, timeout=30, allow_redirects=False)
        raw = response.content
        with (output / name).open("xb") as stream:
            stream.write(raw)
        resources.append({"name": name, "method": method, "url": url, "request_data": data,
                          "http_status": response.status_code, "sha256": hashlib.sha256(raw).hexdigest(),
                          "bytes": len(raw), "request_started_at_utc": started,
                          "response_received_at_utc": datetime.now(timezone.utc).isoformat()})
        if response.status_code != 200:
            raise ValueError(f"official request failed: HTTP {response.status_code}; no fallback")
        return raw

    row = select_source(fetch("catalogue.json", "POST", ENDPOINT, plan["catalogue_payload"]), plan)
    raw_pdf = fetch("annual.pdf", "GET", source["url"])
    if not raw_pdf.startswith(b"%PDF-"):
        raise ValueError("PDF signature missing")
    with fitz.open(stream=raw_pdf, filetype="pdf") as pdf:
        if pdf.needs_pass or pdf.page_count <= 0:
            raise ValueError("encrypted/empty PDF")
        source["page_count"] = pdf.page_count  # No page text, words or renders read here.
    source["pdf_sha256"] = hashlib.sha256(raw_pdf).hexdigest()
    verify_parser(plan)
    scope_raw = json.dumps(scope, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    read_scope(scope_raw)
    with (output / "scope.json").open("xb") as stream:
        stream.write(scope_raw)
    record = {"schema": "annual-holdout-capture-v1", "plan_sha256": hashlib.sha256(plan_raw).hexdigest(),
              "capture_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "source": source, "resources": resources, "catalogue_time_raw_ms": row["announcementTime"],
              "scope_sha256": hashlib.sha256(scope_raw).hexdigest(), "pdf_body_read": False,
              "exact_available_at_utc": None, "complete_revision_chain_verified": False,
              "snapshot_published": False, "production_reader_ready": False}
    with (output / "capture.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = capture(args.plan, args.output)
    print(json.dumps({"source": result["source"], "requests": len(result["resources"]), "pdf_body_read": False}))


if __name__ == "__main__":
    main()
