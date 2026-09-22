"""Command-line interface for Feed Forge scripts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from .x_diagnostics import (
    ConfigurationError,
    load_config,
    render_markdown,
    resolve_credential,
    run_diagnostics,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feed-forge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    diagnostics = subparsers.add_parser(
        "check-x-api",
        help="Validate X credentials and required read endpoints.",
    )
    diagnostics.add_argument(
        "--config",
        type=Path,
        default=Path("config/x_api_checks.toml"),
        help="Path to the versioned TOML configuration.",
    )
    diagnostics.add_argument(
        "--json-output",
        type=Path,
        default=Path("artifacts/x-api-diagnostics.json"),
        help="Machine-readable report path.",
    )
    diagnostics.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("artifacts/x-api-diagnostics.md"),
        help="Human-readable report path.",
    )
    diagnostics.add_argument(
        "--github-summary",
        action="store_true",
        help="Append Markdown to the GITHUB_STEP_SUMMARY file when available.",
    )
    diagnostics.add_argument(
        "--auth-mode",
        choices=("auto", "app_only", "user_context"),
        help="Override x_api.auth_mode from the configuration file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check-x-api":
        return _check_x_api(args)
    return 2


def _check_x_api(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        if args.auth_mode:
            config = replace(config, auth_mode=args.auth_mode)
        credential = resolve_credential(config)
        report = run_diagnostics(config, credential)
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    markdown = render_markdown(report)
    _write_text(args.json_output, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write_text(args.markdown_output, markdown)
    if args.github_summary:
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as summary_file:
                summary_file.write(markdown)
        else:
            print(
                "GITHUB_STEP_SUMMARY is not set; skipped job summary.", file=sys.stderr
            )

    print(markdown)
    print(f"JSON report: {args.json_output}")
    print(f"Markdown report: {args.markdown_output}")
    return 0 if report["overall_status"] == "passed" else 3


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
