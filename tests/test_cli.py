from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feed_forge.cli import main


class CliTests(unittest.TestCase):
    def test_high_reach_preview_writes_reports_without_x_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {}, clear=True):
                exit_code = main([
                    "watch-high-reach", "--json-output", str(root / "watch.json"),
                    "--markdown-output", str(root / "watch.md"),
                    "--lane", "global_tech_ai",
                ])
            report = json.loads((root / "watch.json").read_text(encoding="utf-8"))
            self.assertEqual(0, exit_code)
            self.assertEqual("preview", report["status"])
            self.assertEqual(0, report["cost"]["estimated_returned_usd"])
            self.assertAlmostEqual(0.14, report["cost"]["projected_maximum_usd"])

    def test_topic_radar_writes_github_summary_without_x_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.md"
            report = {
                "schema_version": "feed-forge/topic-radar/v1",
                "generated_at": "2026-09-23T06:00:00Z",
                "timezone": "Asia/Kolkata",
                "max_age_hours": 168,
                "status": "ok",
                "source_health": [],
                "topics": [{"id": "indian_brands", "label": "Indian brands", "lane": "review", "total_recent": 0, "term_counts": {"Frido": 0}, "selection": "new_terms_first", "items": []}],
                "unique_matched_stories": 0,
                "note": "No X API requests.",
            }
            with patch("feed_forge.cli.collect_topics", return_value=report), patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}, clear=True):
                exit_code = main(["collect-topics", "--github-summary", "--json-output", str(root / "report.json"), "--markdown-output", str(root / "report.md")])
            self.assertEqual(0, exit_code)
            self.assertIn("Known topics", summary.read_text(encoding="utf-8"))
            self.assertIn("Frido: 0", summary.read_text(encoding="utf-8"))

    def test_discovery_configuration_failure_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "failure.json"
            markdown_path = Path(directory) / "failure.md"
            with patch.dict(os.environ, {}, clear=True):
                exit_code = main(
                    [
                        "discover-accounts",
                        "--json-output",
                        str(json_path),
                        "--markdown-output",
                        str(markdown_path),
                    ]
                )

            report = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(2, exit_code)
            self.assertEqual("failed", report["status"])
            self.assertEqual("configuration", report["error"]["category"])
            self.assertIn("No X credential", report["error"]["detail"])
            self.assertIn("Status: `failed`", markdown_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
