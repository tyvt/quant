"""Audit-only checks for the two legal-PDF historical-shares source probes."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase

from turtle_quant.pit.parquet_strategy_inputs import ParquetSharesReader


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/data-pilots/2026-10-01-historical-shares-pit-probe.json"


class HistoricalSharesPitProbeTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_scope_and_pit_time_axes_stay_explicit(self) -> None:
        self.assertEqual(self.probe["purpose"], "technical_source_probe_only")
        self.assertFalse(self.probe["research_eligible"])
        self.assertFalse(self.probe["snapshot_published"])
        self.assertEqual({sample["market"] for sample in self.probe["samples"]}, {"SH", "SZ"})
        for sample in self.probe["samples"]:
            with self.subTest(market=sample["market"]):
                axes = sample["time_axes"]
                self.assertIsNone(axes["exact_platform_publication_at_utc"])
                self.assertIsNone(axes["earliest_public_availability_at_utc"])
                catalogue_marker = datetime.fromtimestamp(
                    axes["cninfo_announcement_time_raw_ms"] / 1000,
                    timezone(timedelta(hours=8)),
                )
                self.assertEqual(catalogue_marker.date().isoformat(), axes["cninfo_catalogue_date"])
                self.assertEqual(catalogue_marker.time().isoformat(), "00:00:00")
                self.assertEqual(axes["official_pdf_url_date"], axes["cninfo_catalogue_date"])
                self.assertEqual(sample["pit_disposition"], "NO_PRODUCTION_S_VALUE")
                self.assertTrue(sample["blockers"])

    def test_each_class_bridge_and_page_reference(self) -> None:
        expected = {"SH": (9377629650, 74541486, 9303088164),
                    "SZ": (3070692107, 28223296, 3042468811)}
        for sample in self.probe["samples"]:
            with self.subTest(market=sample["market"]):
                bridge = sample["share_bridge"]
                before, cancelled, after = expected[sample["market"]]
                self.assertEqual(bridge["pre_total_issued_shares"], before)
                self.assertEqual(bridge["cancelled_shares"], cancelled)
                self.assertEqual(bridge["post_total_issued_shares"], after)
                self.assertEqual(before - cancelled, after)
                self.assertEqual(sum(c["pre_issued_shares"] for c in bridge["classes"]), before)
                self.assertEqual(sum(c["post_issued_shares"] for c in bridge["classes"]), after)
                pdf = sample["pdf"]
                for item in sample["evidence"]:
                    digest, page = item["ref"].split("#page=")
                    self.assertEqual(digest, "sha256:" + pdf["sha256"])
                    self.assertTrue(1 <= int(page) <= pdf["pages"])
        self.assertEqual(
            self.probe["samples"][0]["share_bridge"]["post_total_status"],
            "PROJECTED_PENDING_REGISTRAR_CONFIRMATION",
        )

    def test_local_original_pdf_bytes_match_if_available(self) -> None:
        paths = [ROOT / sample["pdf"]["local_path"] for sample in self.probe["samples"]]
        if not all(path.exists() for path in paths):
            self.skipTest("raw pilot PDFs are local storage artifacts")
        for sample, path in zip(self.probe["samples"], paths):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"%PDF-"))
                self.assertEqual(len(raw), sample["pdf"]["bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), sample["pdf"]["sha256"])

    def test_pilot_does_not_unlock_production_shares_reader(self) -> None:
        reader = ParquetSharesReader(ROOT / "storage/snapshots")
        with self.assertRaisesRegex(NotImplementedError, "not ready"):
            reader.shares_on("sh.600690", as_of=date(2026, 9, 1))
