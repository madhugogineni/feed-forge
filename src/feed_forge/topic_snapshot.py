"""Create the repository-readable snapshot of a Topic Radar report."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TopicSnapshotError(ValueError):
    """Raised when a Topic Radar snapshot cannot be created safely."""


def publish_topic_snapshot(
    source_json: Path,
    source_markdown: Path,
    target_json: Path,
    target_markdown: Path,
    *,
    workflow_run_id: int,
    commit_sha: str,
    artifact_name: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Copy a report to its latest paths and add missing run provenance.

    The source JSON is read-only. Provenance is added only to the repository
    snapshot, leaving the historical Actions artifact byte-for-byte unchanged.
    """

    if workflow_run_id <= 0:
        raise TopicSnapshotError("workflow_run_id must be a positive integer")
    if not commit_sha.strip():
        raise TopicSnapshotError("commit_sha must not be empty")
    if not artifact_name.strip():
        raise TopicSnapshotError("artifact_name must not be empty")

    try:
        report = json.loads(source_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TopicSnapshotError(f"Could not read Topic Radar JSON: {error}") from error

    if not isinstance(report, dict) or not report:
        raise TopicSnapshotError("Topic Radar JSON must be a non-empty object")

    required_report_fields = ("schema_version", "status", "source_health", "topics")
    missing = [field for field in required_report_fields if field not in report]
    if missing:
        raise TopicSnapshotError(
            "Topic Radar JSON is missing required fields: " + ", ".join(missing)
        )

    _set_if_missing(report, "workflow_run_id", workflow_run_id)
    _set_if_missing(report, "commit_sha", commit_sha.strip())
    _set_if_missing(report, "artifact_name", artifact_name.strip())
    _set_if_missing(
        report,
        "generated_at",
        generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )

    target_json.parent.mkdir(parents=True, exist_ok=True)
    target_markdown.parent.mkdir(parents=True, exist_ok=True)
    target_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    try:
        shutil.copyfile(source_markdown, target_markdown)
    except OSError as error:
        raise TopicSnapshotError(f"Could not copy Topic Radar Markdown: {error}") from error

    return report


def _set_if_missing(report: dict[str, Any], key: str, value: Any) -> None:
    """Add provenance when absent or effectively empty; preserve real values."""

    if key not in report or report[key] is None or report[key] == "":
        report[key] = value
