#!/usr/bin/env python3
"""Publish the latest Topic Radar report as repository-readable files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from feed_forge.topic_snapshot import TopicSnapshotError, publish_topic_snapshot  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-json", type=Path, required=True)
    parser.add_argument("--source-markdown", type=Path, required=True)
    parser.add_argument("--target-json", type=Path, required=True)
    parser.add_argument("--target-markdown", type=Path, required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--generated-at")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        publish_topic_snapshot(
            args.source_json,
            args.source_markdown,
            args.target_json,
            args.target_markdown,
            workflow_run_id=args.workflow_run_id,
            commit_sha=args.commit_sha,
            artifact_name=args.artifact_name,
            generated_at=args.generated_at,
        )
    except TopicSnapshotError as error:
        print(f"Snapshot publication failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
