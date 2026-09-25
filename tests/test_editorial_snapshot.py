from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from feed_forge.editorial_snapshot import (
    EDITORIAL_INPUT_SCHEMA,
    EditorialSnapshotError,
    build_editorial_snapshot,
    canonicalize_url,
    validate_editorial_snapshot,
)


def _report() -> dict:
    shared = {
        "id": "shared-item",
        "title": "Shared story",
        "published_at": "2026-09-25T10:00:00Z",
        "source_ids": ["feed-b", "feed-a"],
        "topic_matches": {"topic-a": ["Alpha"], "topic-b": ["Beta"]},
    }
    return {
        "schema_version": "feed-forge/topic-radar/v1",
        "generated_at": "2026-09-25T12:03:48Z",
        "status": "ok",
        "source_health": [
            {"id": "feed-a", "name": "Feed A", "status": "ok"},
            {"id": "feed-b", "name": "Feed B", "status": "ok"},
        ],
        "topics": [
            {
                "id": "topic-b",
                "label": "Topic B",
                "lane": "review",
                "total_recent": 2,
                "term_counts": None,
                "selection": "newest_first",
                "items": [
                    {
                        **shared,
                        "url": "https://EXAMPLE.com:443/story?utm_source=rss#section",
                    },
                    {
                        "id": "second-item",
                        "title": "Second story",
                        "published_at": "2026-09-25T09:00:00Z",
                        "source_ids": ["feed-a"],
                        "topic_matches": {"topic-b": ["Beta"]},
                        "url": "https://example.com/second?edition=in&utm_medium=feed",
                    },
                ],
            },
            {
                "id": "topic-a",
                "label": "Topic A",
                "lane": "review",
                "total_recent": 2,
                "term_counts": {"Alpha": 2},
                "selection": "new_terms_first",
                "items": [
                    {**shared, "url": "https://example.com/story"},
                    {
                        "id": "third-item",
                        "title": "Third story",
                        "published_at": "2026-09-25T08:00:00Z",
                        "source_ids": ["feed-b"],
                        "topic_matches": {"topic-a": ["Alpha"]},
                        "url": "https://other.example/item#details",
                    },
                ],
            },
        ],
    }


def _load_records(root: Path, shard_entries: list[dict]) -> list[dict]:
    records = []
    for entry in shard_entries:
        records.extend(json.loads((root / entry["path"]).read_text())["records"])
    return records


def _rewrite_manifest_checksum(root: Path, manifest_field: str, index: int) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    shard_path = root / manifest[manifest_field][index]["path"]
    manifest[manifest_field][index]["sha256"] = hashlib.sha256(
        shard_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class EditorialSnapshotTests(unittest.TestCase):
    def _build(self, root: Path, *, shard_size: int = 2, report: dict | None = None) -> dict:
        return build_editorial_snapshot(
            report if report is not None else _report(),
            root,
            workflow_run_id=123456789,
            commit_sha="abc123",
            generated_at="2026-09-25T12:03:48Z",
            shard_size=shard_size,
        )

    def test_manifest_generation_provenance_totals_and_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)

            self.assertEqual(EDITORIAL_INPUT_SCHEMA, manifest["schema_version"])
            self.assertEqual(123456789, manifest["workflow_run_id"])
            self.assertEqual("abc123", manifest["commit_sha"])
            self.assertEqual("2026-09-25T12:03:48Z", manifest["generated_at"])
            self.assertEqual(2, manifest["topic_count"])
            self.assertEqual(4, manifest["url_occurrence_count"])
            self.assertEqual(3, manifest["unique_url_count"])
            self.assertEqual(
                {"manifest.json", "topics.json", "source-health.json", "occurrences", "urls"},
                {path.name for path in root.iterdir()},
            )
            self.assertEqual(manifest, validate_editorial_snapshot(root))

    def test_occurrences_preserve_duplicates_and_required_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)
            occurrences = _load_records(root, manifest["occurrence_shards"])

            self.assertEqual(4, len(occurrences))
            shared = [item for item in occurrences if item["pipeline_item_id"] == "shared-item"]
            self.assertEqual(2, len(shared))
            self.assertEqual({"topic-a", "topic-b"}, {item["topic_id"] for item in shared})
            self.assertEqual({"https://example.com/story"}, {item["canonical_url"] for item in shared})
            self.assertEqual(["feed-a", "feed-b"], shared[0]["feed_ids"])
            for field in (
                "occurrence_id",
                "pipeline_item_id",
                "topic",
                "feed_id",
                "feed_name",
                "title",
                "published_at",
                "original_url",
                "canonical_url",
            ):
                self.assertTrue(all(item[field] for item in occurrences))
            self.assertEqual(len(occurrences), len({item["occurrence_id"] for item in occurrences}))

    def test_canonical_urls_are_deduplicated_with_valid_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)
            urls = _load_records(root, manifest["url_shards"])
            shared = next(item for item in urls if item["canonical_url"].endswith("/story"))

            self.assertEqual(2, shared["occurrence_count"])
            self.assertEqual(2, len(shared["occurrence_ids"]))
            self.assertEqual(["topic-a", "topic-b"], shared["topic_ids"])
            validate_editorial_snapshot(root)

    def test_url_canonicalization_is_conservative_and_deterministic(self) -> None:
        self.assertEqual(
            "https://example.com/path?a=1&b=2",
            canonicalize_url(
                "HTTPS://Example.COM:443/path?a=1&utm_source=newsletter&b=2#fragment"
            ),
        )
        self.assertEqual(
            "http://example.com/",
            canonicalize_url("http://EXAMPLE.com:80#top"),
        )
        with self.assertRaises(EditorialSnapshotError):
            canonicalize_url("file:///tmp/report.json")

    def test_shards_have_deterministic_order_and_respect_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first = Path(first_directory) / "latest"
            second = Path(second_directory) / "latest"
            first_manifest = self._build(first, shard_size=2)
            second_manifest = self._build(second, shard_size=2)

            self.assertEqual(
                ["occurrences/001.json", "occurrences/002.json"],
                [entry["path"] for entry in first_manifest["occurrence_shards"]],
            )
            self.assertTrue(
                all(entry["record_count"] <= 2 for entry in first_manifest["occurrence_shards"])
            )
            self.assertTrue(all(entry["record_count"] <= 2 for entry in first_manifest["url_shards"]))
            first_files = {
                path.relative_to(first): path.read_bytes()
                for path in first.rglob("*.json")
            }
            second_files = {
                path.relative_to(second): path.read_bytes()
                for path in second.rglob("*.json")
            }
            self.assertEqual(first_files, second_files)

    def test_manifest_sha256_matches_exact_shard_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)
            for entry in manifest["occurrence_shards"] + manifest["url_shards"]:
                self.assertEqual(
                    hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest(),
                    entry["sha256"],
                )

    def test_missing_shard_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)
            (root / manifest["occurrence_shards"][0]["path"]).unlink()
            with self.assertRaisesRegex(EditorialSnapshotError, "missing"):
                validate_editorial_snapshot(root)

    def test_corrupted_shard_fails_checksum_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)
            shard = root / manifest["url_shards"][0]["path"]
            shard.write_bytes(shard.read_bytes() + b" ")
            with self.assertRaisesRegex(EditorialSnapshotError, "SHA-256 mismatch"):
                validate_editorial_snapshot(root)

    def test_malformed_json_fails_even_with_matching_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)
            shard = root / manifest["occurrence_shards"][0]["path"]
            shard.write_text("{not-json", encoding="utf-8")
            _rewrite_manifest_checksum(root, "occurrence_shards", 0)
            with self.assertRaisesRegex(EditorialSnapshotError, "Malformed JSON"):
                validate_editorial_snapshot(root)

    def test_invalid_url_mapping_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)
            shard = root / manifest["url_shards"][0]["path"]
            payload = json.loads(shard.read_text())
            payload["records"][0]["occurrence_ids"] = ["occ_999999"]
            payload["records"][0]["occurrence_count"] = 1
            shard.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            _rewrite_manifest_checksum(root, "url_shards", 0)
            with self.assertRaisesRegex(EditorialSnapshotError, "unknown occurrence"):
                validate_editorial_snapshot(root)

    def test_duplicate_occurrence_id_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root)
            shard = root / manifest["occurrence_shards"][0]["path"]
            payload = json.loads(shard.read_text())
            payload["records"][1]["occurrence_id"] = payload["records"][0][
                "occurrence_id"
            ]
            shard.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            _rewrite_manifest_checksum(root, "occurrence_shards", 0)
            with self.assertRaisesRegex(EditorialSnapshotError, "Duplicate occurrence_id"):
                validate_editorial_snapshot(root)

    def test_manifest_record_total_mismatch_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            self._build(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["url_occurrence_count"] += 1
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(EditorialSnapshotError, "Occurrence shard totals"):
                validate_editorial_snapshot(root)

    def test_empty_dataset_creates_valid_snapshot_without_shards(self) -> None:
        report = {
            "generated_at": "2026-09-25T12:03:48Z",
            "source_health": [],
            "topics": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "latest"
            manifest = self._build(root, report=report)
            self.assertEqual(0, manifest["url_occurrence_count"])
            self.assertEqual(0, manifest["unique_url_count"])
            self.assertEqual([], manifest["occurrence_shards"])
            self.assertEqual([], manifest["url_shards"])
            self.assertEqual([], list((root / "occurrences").iterdir()))
            self.assertEqual([], list((root / "urls").iterdir()))
            validate_editorial_snapshot(root)


if __name__ == "__main__":
    unittest.main()
