from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from turtle_quant.storage import (
    DomainRevokedError,
    IngestConfig,
    SnapshotSession,
    SnapshotVerificationError,
    verify_published_domain,
)
from turtle_quant.storage.snapshot import _canonical_json


class PublishedSnapshotVerificationTests(unittest.TestCase):
    @staticmethod
    def _write_catalog(root: Path, revocations: dict[str, object]) -> None:
        catalog = root / "catalog" / "domain-revocations.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(
            json.dumps(
                {"schema_version": 1, "revocations": revocations},
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _publish(
        self,
        root: Path,
        *,
        quality_flags: tuple[str, ...] = (),
        details: dict[str, object] | None = None,
    ) -> tuple[str, Path]:
        config = IngestConfig(
            ingest_calendar_date=date(2026, 9, 29),
            steps=("calendar",),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            max_symbols=0,
            board_filter_version="main_board_v1",
            source_provenance_template={"fixture": {"version": "1"}},
        )
        session = SnapshotSession.start(root, config)
        data_file = session.staging_path / "calendar" / "trade_dates.parquet"
        data_file.parent.mkdir(parents=True)
        data_file.write_bytes(b"immutable-calendar-fixture")
        session.complete_domain(
            "calendar",
            files=(data_file,),
            row_count=2,
            quality_flags=quality_flags,
            details=details,
        )
        snapshot_id = session.publish(
            universe_hash="0123456789abcdef",
            source_descriptors={"fixture": {"version": "1"}},
        )
        self._write_catalog(root, {})
        return snapshot_id, root / "snapshots" / snapshot_id

    def _publish_benchmark_meta(
        self,
        root: Path,
        *,
        quality_flags: tuple[str, ...],
        details: dict[str, object],
        exclusion_policy: str = "explicit_whitelist_v1",
    ) -> tuple[str, Path]:
        config = IngestConfig(
            ingest_calendar_date=date(2026, 9, 30),
            steps=("benchmark",),
            start_date=date(2018, 6, 15),
            end_date=date(2018, 6, 19),
            max_symbols=None,
            board_filter_version="benchmark_fixture",
            source_provenance_template={"fixture": {"version": "benchmark-meta"}},
        )
        session = SnapshotSession.start(root, config)
        session.set_source_provenance("csindex", {
            "exclusion_policy": exclusion_policy,
        })
        data_file = session.staging_path / "benchmark" / "values.parquet"
        data_file.parent.mkdir(parents=True)
        data_file.write_bytes(b"benchmark-metadata-fixture")
        session.complete_domain(
            "benchmark", files=(data_file,), row_count=1,
            quality_flags=quality_flags, details=details,
        )
        snapshot_id = session.publish(
            universe_hash="benchmark-metadata-fixture",
            source_descriptors={"fixture": {"version": "benchmark-meta"}},
        )
        self._write_catalog(root, {})
        return snapshot_id, root / "snapshots" / snapshot_id

    def test_benchmark_exclusion_marker_and_details_must_correspond(self) -> None:
        marker = "benchmark_excluded_dates"
        day = "2018-06-18"
        evidence = {
            "excluded_date": day,
            "official_close": "5161.74",
            "calendar_verdict": "NON_TRADING_DAY",
            "exclusion_reason": "approved fixture",
            "evidence_ref": "fixture:raw:data[1]:row-hash",
            "rule_version": "v1.3.0",
        }
        valid_details = {
            marker: [day], "exclusion_evidence": [evidence],
        }
        cases = (
            ("valid", (marker,), valid_details, "explicit_whitelist_v1", False, None),
            ("marker_without_dates", (marker,), {}, "explicit_whitelist_v1", False,
             "marker and dates disagree"),
            ("dates_without_marker", (), valid_details, "explicit_whitelist_v1", False,
             "marker and dates disagree"),
            ("snapshot_marker_missing", (marker,), valid_details,
             "explicit_whitelist_v1", True, "marker and dates disagree"),
            ("evidence_missing", (marker,), {marker: [day]},
             "explicit_whitelist_v1", False, "evidence count differs"),
            ("evidence_date_mismatch", (marker,), {
                marker: [day], "exclusion_evidence": [{**evidence, "excluded_date": "2005-01-01"}],
            }, "explicit_whitelist_v1", False, "evidence date differs"),
            ("policy_missing", (marker,), valid_details, "none", False,
             "exclusion policy is invalid"),
        )
        for name, flags, details, policy, remove_top_flag, error in cases:
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                snapshot_id, snapshot_path = self._publish_benchmark_meta(
                    root, quality_flags=flags, details=details,
                    exclusion_policy=policy,
                )
                if remove_top_flag:
                    meta_path = snapshot_path / "meta.json"
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta["data_quality_flags"] = []
                    meta_path.write_text(json.dumps(meta), encoding="utf-8")
                if error is None:
                    verified = verify_published_domain(root, snapshot_id, "benchmark")
                    self.assertEqual(verified.snapshot_quality_flags, (marker,))
                    self.assertEqual(verified.domain_details[marker], (day,))
                else:
                    with self.assertRaisesRegex(SnapshotVerificationError, error):
                        verify_published_domain(root, snapshot_id, "benchmark")

    def test_benchmark_marker_without_benchmark_domain_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, snapshot_path = self._publish(root)
            meta_path = snapshot_path / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["data_quality_flags"] = ["benchmark_excluded_dates"]
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            with self.assertRaisesRegex(
                SnapshotVerificationError, "no complete benchmark domain"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    @staticmethod
    def _rewrite_content_identity(
        snapshot_path: Path,
        mutate: object,
    ) -> tuple[str, Path]:
        meta_path = snapshot_path / "meta.json"
        meta = json.loads(meta_path.read_text("utf-8"))
        assert callable(mutate)
        mutate(meta)
        payload = {
            "schema_version": meta["schema_version"],
            "config_hash": meta["config_hash"],
            "domains": meta["domains"],
            "source_descriptors": meta["source_descriptors"],
            "universe_hash": meta["universe_hash"],
        }
        content_hash = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        snapshot_id = f"snapshot-{content_hash[:16]}"
        meta["content_hash"] = content_hash
        meta["snapshot_id"] = snapshot_id
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        destination = snapshot_path.parent / snapshot_id
        snapshot_path.rename(destination)
        return snapshot_id, destination

    def test_verifies_content_identity_and_returns_only_whitelisted_files(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, snapshot_path = self._publish(root)

            verified = verify_published_domain(root, snapshot_id, "calendar")

            self.assertEqual(verified.snapshot_id, snapshot_id)
            self.assertEqual(verified.domain, "calendar")
            self.assertEqual(verified.snapshot_path, snapshot_path.resolve())
            self.assertEqual(verified.row_count, 2)
            self.assertEqual(verified.universe_hash, "0123456789abcdef")
            self.assertEqual(
                verified.file_paths,
                ((snapshot_path / "calendar" / "trade_dates.parquet").resolve(),),
            )
            self.assertEqual(verified.quality_flags, ())
            self.assertEqual(verified.snapshot_quality_flags, ())
            self.assertEqual(
                verified.config["end_date"],
                "2024-01-02",
            )
            self.assertEqual(
                verified.source_descriptors["fixture"],
                {"version": "1"},
            )
            self.assertEqual(dict(verified.domain_details), {})
            with self.assertRaises(TypeError):
                verified.config["end_date"] = "2099-01-01"  # type: ignore[index]
            with self.assertRaises(TypeError):
                verified.source_descriptors["fixture"]["version"] = "2"  # type: ignore[index]

    def test_rejects_file_tampering_after_publish(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, snapshot_path = self._publish(root)
            (snapshot_path / "calendar" / "trade_dates.parquet").write_bytes(
                b"tampered"
            )

            with self.assertRaisesRegex(
                SnapshotVerificationError, "file hash mismatch"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    def test_rejects_revoked_domain_without_following_replacement(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, _snapshot_path = self._publish(root)
            replacement = "snapshot-0123456789abcdef"
            self._write_catalog(
                root,
                {
                    snapshot_id: {
                        "calendar": {
                            "reason": "fixture revoked",
                            "replacement_snapshot_id": replacement,
                        }
                    }
                },
            )

            with self.assertRaisesRegex(
                DomainRevokedError,
                rf"fixture revoked; replacement={replacement}",
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    def test_fails_closed_when_revocation_catalog_is_missing(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, _snapshot_path = self._publish(root)
            (root / "catalog" / "domain-revocations.json").unlink()

            with self.assertRaisesRegex(
                SnapshotVerificationError, "revocation catalog.*missing"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    def test_rejects_modified_meta_and_incomplete_domain(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, snapshot_path = self._publish(root)
            meta_path = snapshot_path / "meta.json"
            meta = json.loads(meta_path.read_text("utf-8"))
            meta["content_hash"] = "0" * 64
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

            with self.assertRaisesRegex(
                SnapshotVerificationError, "content hash mismatch"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, _snapshot_path = self._publish(root)
            with self.assertRaisesRegex(
                SnapshotVerificationError, "missing or incomplete"
            ):
                verify_published_domain(root, snapshot_id, "market_daily")

    def test_rejects_config_body_tampering_even_when_content_hash_is_unchanged(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, snapshot_path = self._publish(root)
            meta_path = snapshot_path / "meta.json"
            meta = json.loads(meta_path.read_text("utf-8"))
            meta["config"]["end_date"] = "2099-01-01"
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

            with self.assertRaisesRegex(
                SnapshotVerificationError, "config hash mismatch"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    def test_rejects_required_domains_that_disagree_with_config_steps(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, snapshot_path = self._publish(root)
            meta_path = snapshot_path / "meta.json"
            meta = json.loads(meta_path.read_text("utf-8"))
            meta["required_domains"] = []
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

            with self.assertRaisesRegex(
                SnapshotVerificationError, "do not match config steps"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    def test_returns_deeply_immutable_domain_details_and_snapshot_flags(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, _snapshot_path = self._publish(
                root,
                quality_flags=("calendar:fixture:warning",),
                details={
                    "missing_security_ids": ["sh.600001"],
                    "security_coverage": "0.5",
                },
            )

            verified = verify_published_domain(root, snapshot_id, "calendar")

            self.assertEqual(
                verified.snapshot_quality_flags,
                ("calendar:fixture:warning",),
            )
            self.assertEqual(
                verified.domain_details["missing_security_ids"],
                ("sh.600001",),
            )
            with self.assertRaises(TypeError):
                verified.domain_details["security_coverage"] = "1"  # type: ignore[index]

    def test_rejects_source_descriptors_that_disagree_with_hashed_config(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _snapshot_id, snapshot_path = self._publish(root)

            def mutate(meta: dict[str, object]) -> None:
                meta["source_descriptors"] = {"fixture": {"version": "2"}}

            snapshot_id, _new_path = self._rewrite_content_identity(
                snapshot_path, mutate
            )
            with self.assertRaisesRegex(
                SnapshotVerificationError, "source descriptors do not match"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    def test_rejects_invalid_snapshot_quality_flags(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, snapshot_path = self._publish(root)
            meta_path = snapshot_path / "meta.json"
            meta = json.loads(meta_path.read_text("utf-8"))
            meta["data_quality_flags"] = "not-a-list"
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

            with self.assertRaisesRegex(
                SnapshotVerificationError, "data_quality_flags"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    def test_rejects_invalid_snapshot_identifier_before_path_access(self) -> None:
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                SnapshotVerificationError, "invalid format"
            ):
                verify_published_domain(
                    temporary,
                    "../snapshot-0123456789abcdef",
                    "calendar",
                )

    def test_rejects_invalid_top_level_meta_and_missing_snapshot(self) -> None:
        cases = (
            ("schema_version", 2, "unsupported snapshot schema"),
            ("status", "in_progress", "not complete"),
            ("snapshot_id", "snapshot-0000000000000000", "does not match"),
            ("required_domains", None, "required_domains"),
            (
                "required_domains",
                ["calendar", "market_daily"],
                "required domains are not complete",
            ),
        )
        for field, value, message in cases:
            with self.subTest(field=field, value=value), TemporaryDirectory() as temporary:
                root = Path(temporary)
                snapshot_id, snapshot_path = self._publish(root)
                meta_path = snapshot_path / "meta.json"
                meta = json.loads(meta_path.read_text("utf-8"))
                meta[field] = value
                meta_path.write_text(json.dumps(meta), encoding="utf-8")

                with self.assertRaisesRegex(SnapshotVerificationError, message):
                    verify_published_domain(root, snapshot_id, "calendar")

        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                SnapshotVerificationError, "published snapshot is missing"
            ):
                verify_published_domain(
                    temporary,
                    "snapshot-0123456789abcdef",
                    "calendar",
                )

    def test_rejects_malformed_revocation_catalog_records(self) -> None:
        cases: tuple[dict[str, object], str] = (
            ({"schema_version": 2, "revocations": {}}, "unsupported.*schema"),
            ({"schema_version": 1, "revocations": []}, "catalog.revocations"),
        )
        for catalog_payload, message in cases:
            with self.subTest(catalog=catalog_payload), TemporaryDirectory() as temporary:
                root = Path(temporary)
                snapshot_id, _snapshot_path = self._publish(root)
                catalog = root / "catalog" / "domain-revocations.json"
                catalog.write_text(json.dumps(catalog_payload), encoding="utf-8")

                with self.assertRaisesRegex(SnapshotVerificationError, message):
                    verify_published_domain(root, snapshot_id, "calendar")

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_id, _snapshot_path = self._publish(root)
            self._write_catalog(
                root,
                {
                    snapshot_id: {
                        "calendar": {
                            "reason": "fixture revoked",
                            "replacement_snapshot_id": "latest",
                        }
                    }
                },
            )
            with self.assertRaisesRegex(
                SnapshotVerificationError, "replacement_snapshot_id is invalid"
            ):
                verify_published_domain(root, snapshot_id, "calendar")

    def test_rejects_invalid_domain_metadata_after_valid_content_identity(self) -> None:
        def set_row_count(meta: dict[str, object]) -> None:
            meta["domains"]["calendar"]["row_count"] = -1  # type: ignore[index]

        def clear_files(meta: dict[str, object]) -> None:
            domain = meta["domains"]["calendar"]  # type: ignore[index]
            domain["file_hashes"] = {}

        def break_logical_hash(meta: dict[str, object]) -> None:
            domain = meta["domains"]["calendar"]  # type: ignore[index]
            domain["logical_hash"] = "0" * 64

        def break_quality_flags(meta: dict[str, object]) -> None:
            domain = meta["domains"]["calendar"]  # type: ignore[index]
            domain["quality_flags"] = "not-a-list"

        def add_parent_path(meta: dict[str, object]) -> None:
            domain = meta["domains"]["calendar"]  # type: ignore[index]
            hashes = domain["file_hashes"]
            expected = next(iter(hashes.values()))
            domain["file_hashes"] = {"../outside.parquet": expected}
            domain["logical_hash"] = hashlib.sha256(
                _canonical_json(
                    {
                        "row_count": domain["row_count"],
                        "file_hashes": domain["file_hashes"],
                    }
                ).encode("utf-8")
            ).hexdigest()

        cases = (
            (set_row_count, "row_count"),
            (clear_files, "no whitelisted files"),
            (break_logical_hash, "logical hash mismatch"),
            (break_quality_flags, "quality_flags"),
            (add_parent_path, "escapes root"),
        )
        for mutate, message in cases:
            with self.subTest(message=message), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _old_id, snapshot_path = self._publish(root)
                snapshot_id, _new_path = self._rewrite_content_identity(
                    snapshot_path, mutate
                )

                with self.assertRaisesRegex(SnapshotVerificationError, message):
                    verify_published_domain(root, snapshot_id, "calendar")
