from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
import unicodedata
from unittest.mock import patch

from turtle_quant.storage.checkpoint import (
    checkpoint_payload,
    should_skip_completed_shard,
)
from turtle_quant.storage.snapshot import (
    BatchLock,
    IngestConfig,
    SnapshotSession,
    _canonical_json,
    compute_batch_id,
    compute_universe_hash,
    normalize_fetch_time_utc,
    provenance_to_manifest_source_versions,
    sha256_file,
)


class CanonicalIdentityTests(unittest.TestCase):
    def _config(self, **overrides: object) -> IngestConfig:
        values: dict[str, object] = {
            "ingest_calendar_date": date(2026, 9, 24),
            "steps": ("market_daily", "security_master"),
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 12, 31),
            "max_symbols": None,
            "board_filter_version": "main_board_v1",
            "source_provenance_template": {
                "stockdb_rd": {
                    "sdk_version": "local",
                    "fetch_time_utc": "2026-09-24T01:00:00Z",
                }
            },
        }
        values.update(overrides)
        return IngestConfig(**values)

    def test_canonical_json_sorts_keys_and_normalizes_unicode(self) -> None:
        composed = "café"
        decomposed = unicodedata.normalize("NFD", composed)
        left = _canonical_json({"z": decomposed, "a": 1})
        right = _canonical_json({"a": 1, "z": composed})
        self.assertEqual(left, right)
        self.assertEqual(left, '{"a":1,"z":"café"}')

    def test_batch_id_is_pure_and_ignores_fetch_time(self) -> None:
        first = self._config()
        second = self._config(
            steps=("security_master", "market_daily"),
            source_provenance_template={
                "stockdb_rd": {
                    "sdk_version": "local",
                    "fetch_time_utc": "2026-09-24T05:00:00Z",
                }
            },
        )
        self.assertEqual(compute_batch_id(first), compute_batch_id(second))
        self.assertRegex(
            compute_batch_id(first),
            r"^local-20260924-[0-9a-f]{16}$",
        )

    def test_ingest_calendar_date_is_required_and_not_implicit(self) -> None:
        with self.assertRaises(TypeError):
            IngestConfig(  # type: ignore[call-arg]
                steps=("security_master",),
                start_date=None,
                end_date=None,
                max_symbols=0,
                board_filter_version="main_board_v1",
                source_provenance_template={},
            )

    def test_universe_hash_is_order_independent_and_ignores_metadata(self) -> None:
        rows = [
            {
                "symbol": "sz.000001",
                "listing_date": "1991-04-03",
                "delisting_date": None,
                "source": "a",
                "fetch_time_utc": "2026-09-24T01:00:00Z",
            },
            {
                "symbol": "sh.600000",
                "listing_date": "1999-11-10",
                "delisting_date": None,
                "source": "a",
            },
        ]
        changed_metadata = [dict(row, source="b") for row in reversed(rows)]
        first = compute_universe_hash(rows)
        second = compute_universe_hash(changed_metadata)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{16}$")

    def test_provenance_is_canonical_and_excludes_acquisition_time(self) -> None:
        first = provenance_to_manifest_source_versions(
            {
                "源": {
                    "version": "1",
                    "fetch_time_utc": "2026-09-24T01:00:00Z",
                }
            }
        )
        second = provenance_to_manifest_source_versions(
            {
                "源": {
                    "fetch_time_utc": "2026-09-24T09:00:00Z",
                    "version": "1",
                }
            }
        )
        self.assertEqual(first, second)
        self.assertEqual(first["源"], '{"version":"1"}')
        self.assertEqual(
            normalize_fetch_time_utc(
                datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
            ),
            "2026-09-24T12:00:00Z",
        )


class SnapshotLifecycleTests(unittest.TestCase):
    def _config(self) -> IngestConfig:
        return IngestConfig(
            ingest_calendar_date=date(2026, 9, 24),
            steps=("security_master", "calendar"),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            max_symbols=0,
            board_filter_version="main_board_v1",
            source_provenance_template={"fixture": {"version": "1"}},
        )

    def test_partial_snapshot_publishes_by_content_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = SnapshotSession.start(root, self._config())
            security_file = session.staging_path / "security_master" / "part.parquet"
            security_file.parent.mkdir(parents=True)
            security_file.write_bytes(b"security")
            calendar_file = session.staging_path / "calendar" / "part.parquet"
            calendar_file.parent.mkdir(parents=True)
            calendar_file.write_bytes(b"calendar")

            session.complete_domain(
                "security_master",
                files=(security_file,),
                row_count=2,
            )
            session.complete_domain(
                "calendar",
                files=(calendar_file,),
                row_count=250,
            )
            snapshot_id = session.publish(
                universe_hash="0123456789abcdef",
                source_descriptors={"fixture": {"version": "1"}},
            )

            self.assertRegex(snapshot_id, r"^snapshot-[0-9a-f]{16}$")
            snapshot_path = root / "snapshots" / snapshot_id
            self.assertTrue((snapshot_path / "meta.json").is_file())
            self.assertFalse(session.staging_path.exists())
            meta = json.loads((snapshot_path / "meta.json").read_text("utf-8"))
            self.assertEqual(meta["status"], "complete")
            self.assertEqual(meta["snapshot_id"], snapshot_id)
            self.assertEqual(meta["universe_hash"], "0123456789abcdef")
            self.assertEqual(
                sorted(meta["domains"]),
                ["calendar", "security_master"],
            )

    def test_publish_rejects_missing_required_domain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = SnapshotSession.start(Path(temporary), self._config())
            security_file = session.staging_path / "security_master" / "part"
            security_file.parent.mkdir(parents=True)
            security_file.write_bytes(b"security")
            session.complete_domain(
                "security_master",
                files=(security_file,),
                row_count=1,
            )
            with self.assertRaisesRegex(ValueError, "calendar"):
                session.publish(
                    universe_hash="0123456789abcdef",
                    source_descriptors={"fixture": {"version": "1"}},
                )

    def test_resume_rejects_a_different_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = SnapshotSession.start(root, self._config())
            different = IngestConfig(
                ingest_calendar_date=date(2026, 9, 24),
                steps=("security_master", "calendar"),
                start_date=date(2024, 1, 1),
                end_date=date(2025, 12, 31),
                max_symbols=0,
                board_filter_version="main_board_v1",
                source_provenance_template={"fixture": {"version": "1"}},
            )
            with self.assertRaisesRegex(ValueError, "config"):
                SnapshotSession.resume(root, original.batch_id, different)

    def test_explicit_batch_id_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "batch_id"):
                SnapshotSession.start(
                    Path(temporary),
                    self._config(),
                    batch_id="../../outside",
                )

    def test_stale_batch_lock_from_dead_process_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / ".locks" / "batch.lock"
            lock_path.parent.mkdir()
            lock_path.write_text("2147483646\n", encoding="ascii")
            with BatchLock(lock_path):
                self.assertTrue(lock_path.is_file())
            self.assertFalse(lock_path.exists())

    def test_interrupted_publish_can_be_finished_without_refetching(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = SnapshotSession.start(root, self._config())
            for name, content in (
                ("security_master", b"security"),
                ("calendar", b"calendar"),
            ):
                path = session.staging_path / name / "part"
                path.parent.mkdir()
                path.write_bytes(content)
                session.complete_domain(name, files=(path,), row_count=1)
            real_replace = os.replace

            def fail_directory_move(source: object, destination: object) -> None:
                if Path(str(source)).is_dir():
                    raise OSError(22, "simulated publish interruption")
                real_replace(source, destination)

            with patch(
                "turtle_quant.storage.snapshot.os.replace",
                side_effect=fail_directory_move,
            ):
                with self.assertRaises(OSError):
                    session.publish(
                        universe_hash="0123456789abcdef",
                        source_descriptors={"fixture": {"version": "1"}},
                    )
            self.assertTrue((session.staging_path / "meta.json").is_file())
            snapshot_id = SnapshotSession.finish_interrupted_publish(
                root, session.batch_id
            )
            self.assertIsNotNone(snapshot_id)
            self.assertTrue(
                (root / "snapshots" / str(snapshot_id) / "meta.json").is_file()
            )
            self.assertFalse(session.staging_path.exists())

    def test_batch_lock_rejects_concurrent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / ".locks" / "batch.lock"
            with BatchLock(lock_path):
                with self.assertRaises(FileExistsError):
                    with BatchLock(lock_path):
                        self.fail("second writer acquired the same lock")

    def test_publish_rechecks_file_hash_and_abort_removes_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = SnapshotSession.start(root, self._config())
            security_file = session.staging_path / "security_master" / "part"
            security_file.parent.mkdir(parents=True)
            security_file.write_bytes(b"before")
            session.complete_domain(
                "security_master",
                files=(security_file,),
                row_count=1,
            )
            calendar_file = session.staging_path / "calendar" / "part"
            calendar_file.parent.mkdir(parents=True)
            calendar_file.write_bytes(b"calendar")
            session.complete_domain(
                "calendar",
                files=(calendar_file,),
                row_count=1,
            )
            security_file.write_bytes(b"after")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                session.publish(
                    universe_hash="0123456789abcdef",
                    source_descriptors={"fixture": {"version": "1"}},
                )
            session.abort()
            self.assertFalse(session.staging_path.exists())


class CheckpointTests(unittest.TestCase):
    def test_resume_skips_only_complete_intact_shard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parquet = root / "part-60.parquet"
            parquet.write_bytes(b"stable")
            checkpoint = root / "part-60.checkpoint.json"
            checkpoint.write_text(
                _canonical_json(
                    checkpoint_payload(
                        domain="market_daily",
                        batch_id="local-20260924-0123456789abcdef",
                        prefix="60",
                        status="complete",
                        parquet_sha256=sha256_file(parquet),
                    )
                ),
                encoding="utf-8",
            )
            self.assertTrue(should_skip_completed_shard(checkpoint, parquet))

            parquet.write_bytes(b"corrupted")
            self.assertFalse(should_skip_completed_shard(checkpoint, parquet))


if __name__ == "__main__":
    unittest.main()
