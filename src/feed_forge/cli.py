"""Command-line interface for Feed Forge scripts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from .account_discovery import (
    DiscoveryError,
    load_discovery_config,
    render_discovery_markdown,
    resolve_discovery_authentication,
    run_account_discovery,
)
from .topic_feeds import (
    TopicFeedError,
    collect_topics,
    load_topic_feed_config,
    render_topics_markdown,
)
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
    discovery = subparsers.add_parser(
        "discover-accounts",
        help="Find and rank verified individual X accounts within a cost cap.",
    )
    discovery.add_argument(
        "--config",
        type=Path,
        default=Path("config/account_discovery.toml"),
        help="Path to the account-discovery TOML configuration.",
    )
    discovery.add_argument(
        "--json-output",
        type=Path,
        default=Path("artifacts/account-discovery.json"),
        help="Machine-readable report path.",
    )
    discovery.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("artifacts/account-discovery.md"),
        help="Human-readable report path.",
    )
    discovery.add_argument(
        "--github-summary",
        action="store_true",
        help="Append Markdown to GITHUB_STEP_SUMMARY when available.",
    )
    topics = subparsers.add_parser(
        "collect-topics",
        help="Collect public RSS/Atom feeds into a reviewable topic report.",
    )
    topics.add_argument("--config", type=Path, default=Path("config/topic_feeds.toml"))
    topics.add_argument("--json-output", type=Path, default=Path("artifacts/topic-radar.json"))
    topics.add_argument("--markdown-output", type=Path, default=Path("artifacts/topic-radar.md"))
    topics.add_argument("--github-summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check-x-api":
        return _check_x_api(args)
    if args.command == "discover-accounts":
        return _discover_accounts(args)
    if args.command == "collect-topics":
        return _collect_topics(args)
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


def _discover_accounts(args: argparse.Namespace) -> int:
    try:
        config = load_discovery_config(args.config)
        authentication = resolve_discovery_authentication(config)
        report = run_account_discovery(
            config,
            authentication.token,
            transport=authentication.transport,
            authentication_mode=authentication.mode,
        )
    except (ConfigurationError, DiscoveryError) as error:
        failure = {
            "schema_version": "feed-forge/account-discovery-failure/v1",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "status": "failed",
            "error": {
                "category": (
                    "configuration"
                    if isinstance(error, ConfigurationError)
                    else "discovery"
                ),
                "detail": str(error),
            },
        }
        markdown = (
            "# X account discovery\n\n"
            "- Status: `failed`\n"
            f"- Category: `{failure['error']['category']}`\n"
            f"- Detail: {failure['error']['detail']}\n"
        )
        _write_text(
            args.json_output, json.dumps(failure, indent=2, sort_keys=True) + "\n"
        )
        _write_text(args.markdown_output, markdown)
        _append_github_summary(markdown, args.github_summary)
        print(f"Account discovery failed: {error}", file=sys.stderr)
        print(f"JSON failure report: {args.json_output}", file=sys.stderr)
        print(f"Markdown failure report: {args.markdown_output}", file=sys.stderr)
        return 2

    markdown = render_discovery_markdown(report)
    _write_text(args.json_output, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write_text(args.markdown_output, markdown)
    _append_github_summary(markdown, args.github_summary)

    print(markdown)
    print(f"JSON report: {args.json_output}")
    print(f"Markdown report: {args.markdown_output}")
    return 0


def _collect_topics(args: argparse.Namespace) -> int:
    try:
        config = load_topic_feed_config(args.config)
        report = collect_topics(config)
    except TopicFeedError as error:
        report = {
            "schema_version": "feed-forge/topic-radar-failure/v1",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "status": "failed",
            "error": str(error),
        }
        markdown = f"# Feed Forge topic radar\n\nStatus: **failed**\n\nConfiguration error: {error}\n"
        exit_code = 2
    else:
        markdown = render_topics_markdown(report)
        exit_code = 0 if report["status"] == "ok" else 3
    _write_text(args.json_output, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write_text(args.markdown_output, markdown)
    _append_github_summary(markdown, args.github_summary)
    print(f"Topic radar status: {report['status']}")
    print(f"JSON report: {args.json_output}")
    print(f"Markdown report: {args.markdown_output}")
    return exit_code


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _append_github_summary(markdown: str, enabled: bool) -> None:
    if not enabled:
        return
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(markdown)
    else:
        print("GITHUB_STEP_SUMMARY is not set; skipped job summary.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
