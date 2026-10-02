"""CAPCO historical-PDF probe: content evidence, not a production PIT reader."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "docs" / "data-pilots" / "2026-10-01-industry-periodic-capco.json"
EXPECTED_PROBE_SHA256 = "2ebd4080c37c55f991e723c2f6bf5667d37390893112b28cbded475ac63a822d"


class CapcoIndustryProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = PROBE.read_bytes()
        cls.probe = json.loads(cls.raw.decode("utf-8"))

    def test_probe_identity_and_fail_closed_pit_boundary(self) -> None:
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), EXPECTED_PROBE_SHA256)
        self.assertEqual([x["period"] for x in self.probe["publications"]], ["2024H2", "2025H1"])
        self.assertIs(self.probe["historical_pdf_bytes_proven_at_original_publication"], False)
        self.assertIsNone(self.probe["exact_first_observed_at_utc"])
        self.assertIs(self.probe["snapshot_published"], False)
        self.assertIs(self.probe["research_eligible"], False)
        for publication in self.probe["publications"]:
            self.assertIn("/file/202603/", publication["attachment_url"])
            self.assertEqual([r["security_code"] for r in publication["sample_rows"]], ["600000", "600519"])

    def test_local_pdf_hashes_and_page_values_when_available(self) -> None:
        try:
            import fitz
        except ImportError:
            fitz = None
        for publication in self.probe["publications"]:
            with self.subTest(period=publication["period"]):
                path = ROOT / publication["local_file"]
                if not path.exists():
                    continue
                self.assertEqual(path.stat().st_size, publication["bytes"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), publication["sha256"])
                if fitz is None:
                    continue
                document = fitz.open(path)
                self.assertEqual(len(document), publication["page_count"])
                for row in publication["sample_rows"]:
                    text = document[row["evidence_page"] - 1].get_text()
                    self.assertIn(row["security_code"], text)
                    after_code = text.split(row["security_code"], 1)[1][:90]
                    self.assertIn("\n" + row["category_code"] + "\n", after_code)
                    self.assertIn("\n" + row["major_code"] + "\n", after_code)
                    if "subclass_code" in row:
                        self.assertIn("\n" + row["subclass_code"] + "\n", after_code)


if __name__ == "__main__":
    unittest.main()
