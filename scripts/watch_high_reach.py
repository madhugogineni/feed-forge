#!/usr/bin/env python3
"""Run the high-reach watch from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from feed_forge.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["watch-high-reach", *sys.argv[1:]]))
