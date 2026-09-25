#!/usr/bin/env python3
"""Validate a repository-readable editorial snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from feed_forge.editorial_snapshot import (  # noqa: E402
    EditorialSnapshotError,
    validate_editorial_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot_directory", type=Path)
    args = parser.parse_args()
    try:
        manifest = validate_editorial_snapshot(args.snapshot_directory)
    except EditorialSnapshotError as error:
        print(f"Editorial snapshot validation failed: {error}", file=sys.stderr)
        return 2
    print(
        "Editorial snapshot is valid: "
        f"{manifest['url_occurrence_count']} occurrences, "
        f"{manifest['unique_url_count']} unique URLs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
