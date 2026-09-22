from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from feed_forge.account_discovery import (
    CostBudget,
    DiscoveryError,
    _select_by_topic_mix,
    load_discovery_config,
    render_discovery_markdown,
    resolve_discovery_authentication,
    run_account_discovery,
)
from feed_forge.x_api import ApiResponse
from feed_forge.x_diagnostics import ConfigurationError


FIXED_NOW = datetime(2026, 9, 22, 0, 30, tzinfo=UTC)


class FakeTransport:
    def __init__(self, responses: list[ApiResponse]) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> ApiResponse:
        self.urls.append(url)
        if not self.responses:
            raise AssertionError(f"No fake response for {url}")
        return self.responses.pop(0)


def response(data: list[dict[str, object]]) -> ApiResponse:
    return ApiResponse(
        status=200,
        body={"data": data, "meta": {"result_count": len(data)}},
        headers={"x-rate-limit-remaining": "99"},
        duration_ms=4,
    )


def post(post_id: str, author_id: str, text: str) -> dict[str, object]:
    return {
        "id": post_id,
        "author_id": author_id,
        "text": text,
        "created_at": "2026-09-22T00:00:00Z",
        "public_metrics": {"reply_count": 3, "like_count": 12},
    }


class AccountDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_discovery_config(Path("config/account_discovery.toml"))

    def test_pilot_configuration_has_expected_mix_pool_and_budget(self) -> None:
        self.assertEqual(8, self.config.topic_mix["ai_agents_builders"])
        self.assertEqual(4, self.config.topic_mix["consumer_tech"])
        peers = next(pool for pool in self.config.pools if pool.name == "peers")
        self.assertEqual((100, 1000), (peers.minimum_followers, peers.maximum_followers))
        self.assertEqual(0.5, self.config.max_cost_usd)

    def test_oauth1_credentials_are_preferred_for_scheduled_user_context(self) -> None:
        authentication = resolve_discovery_authentication(
            self.config,
            {
                "X_API_KEY": "key",
                "X_API_KEY_SECRET": "key-secret",
                "X_ACCESS_TOKEN": "token",
                "X_ACCESS_TOKEN_SECRET": "token-secret",
                "X_USER_ACCESS_TOKEN": "short-lived-oauth2-token",
            },
        )
        self.assertEqual("oauth1_user_context", authentication.mode)

    def test_partial_oauth1_credentials_fail_clearly(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "Incomplete OAuth 1.0a"):
            resolve_discovery_authentication(
                self.config,
                {"X_API_KEY": "key", "X_USER_ACCESS_TOKEN": "oauth2-token"},
            )

    def test_app_bearer_is_safe_fallback(self) -> None:
        authentication = resolve_discovery_authentication(
            self.config, {"X_BEARER_TOKEN": "app-token"}
        )
        self.assertEqual("app_only", authentication.mode)
        self.assertEqual("app-token", authentication.token)

    def test_discovery_searches_then_profiles_then_checks_timeline(self) -> None:
        search_post = post(
            "p1",
            "u1",
            "Building a coding agent with an LLM, MCP, evals and inference",
        )
        profile = {
            "id": "u1",
            "username": "individual_builder",
            "name": "Individual Builder",
            "description": "I build AI developer tools",
            "verified": True,
            "verified_type": "blue",
            "connection_status": ["followed_by"],
            "public_metrics": {"followers_count": 1000, "following_count": 120},
        }
        timeline = [
            post(str(index), "u1", "AI coding agent with MCP and LLM evals")
            for index in range(5)
        ]
        transport = FakeTransport(
            [response([search_post])] + [response([]) for _ in range(3)]
            + [response([profile]), response(timeline)]
        )

        report = run_account_discovery(
            self.config,
            "secret",
            transport=transport,
            now=FIXED_NOW,
        )

        self.assertEqual(1, report["summary"]["recommended"])
        candidate = report["candidates"][0]
        self.assertEqual("peers", candidate["pool"])
        self.assertEqual("not_following", candidate["follow_status"])
        self.assertEqual("recommended", candidate["status"])
        self.assertLessEqual(report["cost"]["projected_usd"], 0.5)
        self.assertIn("/2/tweets/search/recent", transport.urls[0])
        self.assertIn("/2/users?", transport.urls[4])
        self.assertIn("/2/users/u1/tweets", transport.urls[5])

    def test_business_and_already_followed_accounts_are_rejected(self) -> None:
        candidates = [
            post("p1", "org", "AI coding agent LLM MCP evals"),
            post("p2", "followed", "AI coding agent LLM MCP evals"),
        ]
        profiles = [
            {
                "id": "org",
                "username": "company",
                "name": "Company",
                "description": "Official account",
                "verified": True,
                "verified_type": "business",
                "public_metrics": {"followers_count": 500},
            },
            {
                "id": "followed",
                "username": "known_person",
                "name": "Known Person",
                "description": "AI builder",
                "verified": True,
                "verified_type": "blue",
                "connection_status": ["following"],
                "public_metrics": {"followers_count": 500},
            },
        ]
        transport = FakeTransport(
            [response(candidates)] + [response([]) for _ in range(3)] + [response(profiles)]
        )
        report = run_account_discovery(
            self.config,
            "secret",
            transport=transport,
            now=FIXED_NOW,
        )
        self.assertEqual([], report["candidates"])
        self.assertEqual(
            {"excluded_verification_type:business", "already_followed"},
            {item["reason"] for item in report["rejections"]},
        )

    def test_budget_rejects_an_oversized_reservation(self) -> None:
        budget = CostBudget(0.50)
        with self.assertRaisesRegex(DiscoveryError, "Cost budget would be exceeded"):
            budget.reserve(
                operation="too-large",
                resource_type="post",
                maximum_resources=101,
                unit_cost_usd=0.005,
            )

    def test_shortlist_uses_configured_topic_mix(self) -> None:
        candidates = []
        for topic, count in self.config.topic_mix.items():
            for index in range(count):
                candidates.append(
                    {
                        "id": f"{topic}-{index}",
                        "topic": topic,
                        "search_score": 100 - index,
                    }
                )
        selected = _select_by_topic_mix(candidates, 20, self.config.topic_mix)
        selected_counts = {
            topic: sum(item["topic"] == topic for item in selected)
            for topic in self.config.topic_mix
        }
        self.assertEqual(dict(self.config.topic_mix), selected_counts)

    def test_loader_rejects_configuration_above_cost_cap(self) -> None:
        source = Path("config/account_discovery.toml").read_text(encoding="utf-8")
        source = source.replace("timeline_finalist_limit = 5", "timeline_finalist_limit = 7")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "discovery.toml"
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "exceeds"):
                load_discovery_config(path)

    def test_markdown_exposes_cost_but_no_token(self) -> None:
        empty = replace(self.config, queries=(self.config.queries[0],))
        transport = FakeTransport([response([])])
        report = run_account_discovery(empty, "secret-token", transport=transport, now=FIXED_NOW)
        markdown = render_discovery_markdown(report)
        self.assertIn("Cost ledger", markdown)
        self.assertNotIn("secret-token", markdown)


if __name__ == "__main__":
    unittest.main()
