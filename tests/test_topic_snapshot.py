from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from feed_forge.topic_snapshot import publish_topic_snapshot


class TopicSnapshotTests(unittest.TestCase):
    def test_latest_json_is_complete_valid_and_has_provenance(self) -> None:
        source_report = {
            "schema_version": "feed-forge/topic-radar/v1",
            "generated_at": "2026-09-25T06:00:00Z",
            "status": "ok",
            "source_health": [],
            "topics": [],
            "unique_matched_stories": 0,
            "note": "Preserve every normal report field.",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_json = root / "topic-radar.json"
            source_markdown = root / "topic-radar.md"
            latest_json = root / "topic-radar" / "latest.json"
            latest_markdown = root / "topic-radar" / "latest.md"
            source_json.write_text(
                json.dumps(source_report, indent=2) + "\n", encoding="utf-8"
            )
            source_markdown.write_text("# Topic Radar\n", encoding="utf-8")
            original_json = source_json.read_bytes()

            publish_topic_snapshot(
                source_json,
                source_markdown,
                latest_json,
                latest_markdown,
                workflow_run_id=123456789,
                commit_sha="abc123",
                artifact_name="topic-radar-123456789",
            )

            self.assertGreater(latest_json.stat().st_size, 0)
            snapshot = json.loads(latest_json.read_text(encoding="utf-8"))
            for field in ("schema_version", "status", "source_health", "topics"):
                self.assertIn(field, snapshot)
            self.assertEqual(123456789, snapshot["workflow_run_id"])
            self.assertEqual("abc123", snapshot["commit_sha"])
            self.assertEqual("2026-09-25T06:00:00Z", snapshot["generated_at"])
            self.assertEqual("topic-radar-123456789", snapshot["artifact_name"])
            self.assertEqual(source_report["note"], snapshot["note"])
            self.assertEqual("# Topic Radar\n", latest_markdown.read_text(encoding="utf-8"))

            # Snapshot provenance must never alter the historical artifact JSON.
            self.assertEqual(original_json, source_json.read_bytes())
            self.assertNotIn("workflow_run_id", json.loads(source_json.read_text()))

    def test_existing_provenance_is_preserved(self) -> None:
        report = {
            "schema_version": "feed-forge/topic-radar/v1",
            "generated_at": "2026-09-24T06:00:00Z",
            "status": "ok",
            "source_health": [],
            "topics": [],
            "workflow_run_id": 42,
            "commit_sha": "existing-sha",
            "artifact_name": "existing-artifact",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_json = root / "source.json"
            source_markdown = root / "source.md"
            source_json.write_text(json.dumps(report), encoding="utf-8")
            source_markdown.write_text("report", encoding="utf-8")

            snapshot = publish_topic_snapshot(
                source_json,
                source_markdown,
                root / "latest.json",
                root / "latest.md",
                workflow_run_id=99,
                commit_sha="new-sha",
                artifact_name="new-artifact",
            )

            self.assertEqual(42, snapshot["workflow_run_id"])
            self.assertEqual("existing-sha", snapshot["commit_sha"])
            self.assertEqual("existing-artifact", snapshot["artifact_name"])

    def test_workflow_keeps_schedule_artifact_upload_and_loop_guard(self) -> None:
        workflow = Path(".github/workflows/topic-radar.yml").read_text(encoding="utf-8")

        self.assertIn('cron: "30 0,3,6,9,12,15 * * *"', workflow)
        self.assertIn("uses: actions/upload-artifact@v4", workflow)
        self.assertIn("artifacts/topic-radar.json", workflow)
        self.assertIn("artifacts/topic-radar.md", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn(
            "git add -- artifacts/topic-radar/latest.json artifacts/topic-radar/latest.md",
            workflow,
        )
        self.assertNotIn("git add .", workflow)

        push_paths = _workflow_push_paths(workflow)
        self.assertNotIn("artifacts/topic-radar/latest.json", push_paths)
        self.assertNotIn("artifacts/topic-radar/latest.md", push_paths)


def _workflow_push_paths(workflow: str) -> set[str]:
    """Return the path allowlist under the workflow's push trigger."""

    lines = workflow.splitlines()
    push_index = lines.index("  push:")
    paths_index = lines.index("    paths:", push_index)
    paths: set[str] = set()
    for line in lines[paths_index + 1 :]:
        if line.startswith("  ") and not line.startswith("      "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            paths.add(stripped[2:])
    return paths


if __name__ == "__main__":
    unittest.main()
