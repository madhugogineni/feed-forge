#!/usr/bin/env python3
"""Run the topic radar from a source checkout without installing the package."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from feed_forge.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["collect-topics", *sys.argv[1:]]))
