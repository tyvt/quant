"""Offline bounded audit-block regression on existing sources, not new blind tests.

Full raw blocks MUST stay below ignored storage/. Export only a public index.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_annual_report_bundle import RULE_SHA256, build_bundle, verified_bytes
from scripts.parsing.generic_extractor import PDFCache
from scripts.pilots.assess_annual_audit_narratives import read_assessment_scope, source_key
from scripts.pilots.export_annual_audit_index import public_index
from scripts.screening.contracts import canonical_bytes, content_hash


def build_blocks(raw_scope, *, root=ROOT):
    scope = read_assessment_scope(raw_scope)
    cache, rows, keys, manifest = PDFCache(), [], set(), None
    for ref in scope["inputs"]:
        bundle = build_bundle(verified_bytes(root, ref["path"], ref["sha256"]), root=root, cache=cache)
        if bundle["as_of"] != scope["as_of"]:
            raise ValueError("mixed audit block as_of")
        current_manifest = bundle["manifest"]
        if manifest is not None and manifest["code_sha256"] != current_manifest["code_sha256"]:
            raise ValueError("audit parser drift during batch")
        manifest = current_manifest
        for observation in bundle["bundles"]:
            key = source_key(observation["source"])
            if key in keys:
                raise ValueError("duplicate audit block source")
            keys.add(key)
            rows.append({"source": observation["source"],
                         "audit_text_observation": observation["audit_text_observation"]})
    rows.sort(key=lambda r: source_key(r["source"]))
    states = [r["audit_text_observation"]["narrative_opinion_block"]["state"] for r in rows]
    report = {"schema": "annual-audit-block-diagnostic-v1", "diagnostic_only": True,
              "as_of": scope["as_of"], "scope_sha256": hashlib.sha256(raw_scope).hexdigest(),
              "method": "BOUNDED_RAW_BLOCK_REGRESSION_NOT_NEW_BLIND_TEST_OR_OPINION_TYPE",
              "manifest": {"parser_code_sha256": manifest["code_sha256"], "rule_sha256": RULE_SHA256,
                           "pdf_backend": manifest["pdf_backend"], "input_scopes": scope["inputs"],
                           "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "counts": {"issuers": len({key[0] for key in keys}), "PDF_versions": len(rows),
                         "legacy_raw_type_identified": sum(r["audit_text_observation"]["raw_opinion_type"] is not None for r in rows),
                         "narrative_raw_blocks_observed": states.count("OBSERVED_NARRATIVE_OPINION_BLOCK_NOT_TYPE"),
                         "narrative_raw_blocks_unresolved": sum(state not in (
                             "OBSERVED_NARRATIVE_OPINION_BLOCK_NOT_TYPE",
                             "NOT_EVALUATED_TABLE_TYPE_TEXT_ALREADY_OBSERVED") for state in states)},
              "observations": rows, "diagnostic_available_at": None, "pit_admitted_observation_count": 0,
              "screening_input_exported": False, "real_pit_run_authorized": False,
              "production_reader_ready": False, "official_selection": False}
    report["logical_content_hash"] = content_hash(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-index", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to((ROOT / "storage").resolve()):
        raise ValueError("full native audit blocks must remain below local storage/")
    raw = canonical_bytes(build_blocks(args.scope.read_bytes())) + b"\n"
    public = canonical_bytes(public_index(raw)) + b"\n"
    if args.check:
        if args.output.read_bytes() != raw or args.public_index.read_bytes() != public:
            raise ValueError("audit block report/index identity mismatch")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.public_index.parent.mkdir(parents=True, exist_ok=True)
        for path, data in ((args.output, raw), (args.public_index, public)):
            with path.open("xb") as stream:
                stream.write(data)
    print(hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
