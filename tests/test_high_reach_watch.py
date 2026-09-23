from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from feed_forge.high_reach_watch import (
    Lane, WatchError, load_watch_config, render_watch_markdown, run_watch,
)
from feed_forge.x_api import ApiResponse


NOW = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)


class FakeTransport:
    def __init__(self, responses: list[ApiResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url: str, *, headers: Mapping[str, str], timeout_seconds: float) -> ApiResponse:
        self.urls.append(url)
        return self.responses.pop(0)


def ok(items: list[dict[str, object]], **extra: object) -> ApiResponse:
    return ApiResponse(200, {"data": items, "meta": {"result_count": len(items)}, **extra}, {}, 1)


def profile(handle: str, followers: int, verified: bool = True) -> dict[str, object]:
    return {"id": handle, "username": handle, "verified": verified,
            "verified_type": "business", "public_metrics": {"followers_count": followers}}


def post(post_id: str, handle: str, text: str, *, lang: str = "en",
         created: str = "2026-09-23T07:40:00Z") -> dict[str, object]:
    return {"id": post_id, "author_id": handle, "text": text, "lang": lang,
            "created_at": created, "public_metrics": {"reply_count": 12}}


class HighReachWatchTests(unittest.TestCase):
    def setUp(self) -> None:
        base = load_watch_config(Path("config/high_reach_watch.toml"))
        self.config = replace(base, lanes=(
            Lane("india_news", ("IndiaToday",), 100_000, None),
            Lane("global_tech_ai", ("TheRundownAI",), 150_000, 750_000),
        ))

    def test_pilot_cost_envelope_and_dry_run(self) -> None:
        full = load_watch_config(Path("config/high_reach_watch.toml"))
        self.assertEqual(12, len(full.handles))
        self.assertAlmostEqual(0.32, full.projected_cost_usd)
        report = run_watch(full, live=False, now=NOW)
        self.assertEqual("preview", report["status"])
        self.assertEqual([], report["posts"])
        self.assertIn("no X API calls", render_watch_markdown(report))

    def test_live_qualifies_profiles_and_ranks_only_fresh_relevant_english_posts(self) -> None:
        transport = FakeTransport([
            ok([profile("IndiaToday", 2_000_000), profile("TheRundownAI", 220_000)]),
            ok([
                post("1", "IndiaToday", "Hyderabad gets a new software update"),
                post("2", "TheRundownAI", "OpenAI announces an AI model"),
                post("3", "IndiaToday", "Election campaign update"),
                post("4", "IndiaToday", "Hyderabad launch", lang="hi"),
                post("5", "IndiaToday", "Hyderabad launch", created="2026-09-23T00:00:00Z"),
            ]),
        ])
        report = run_watch(self.config, live=True, token="test", transport=transport, now=NOW)
        self.assertEqual("ok", report["status"])
        self.assertEqual({"1", "2"}, {item["id"] for item in report["posts"]})
        self.assertEqual(0.045, report["cost"]["estimated_returned_usd"])
        self.assertIn("/2/users/by?", transport.urls[0])
        self.assertIn("/2/tweets/search/recent?", transport.urls[1])
        self.assertIn("from%3AIndiaToday", transport.urls[1])
        self.assertTrue(all(item["review_state"] == "needs_human_review" for item in report["posts"]))

    def test_ineligible_accounts_are_not_searched(self) -> None:
        transport = FakeTransport([ok([profile("IndiaToday", 50_000),
                                       profile("TheRundownAI", 220_000, False)])])
        report = run_watch(self.config, live=True, token="test", transport=transport, now=NOW)
        self.assertEqual("no_eligible_accounts", report["status"])
        self.assertEqual(1, len(transport.urls))

    def test_partial_errors_fail_visibly_without_post_search(self) -> None:
        transport = FakeTransport([ok([profile("IndiaToday", 2_000_000)],
                                     errors=[{"title": "Partial failure", "status": 503}])])
        with self.assertRaisesRegex(WatchError, "partial API errors"):
            run_watch(self.config, live=True, token="test", transport=transport, now=NOW)
        self.assertEqual(1, len(transport.urls))

    def test_malformed_metrics_fail_visibly(self) -> None:
        bad = profile("IndiaToday", 2_000_000)
        bad["public_metrics"] = {"followers_count": "2m"}
        transport = FakeTransport([ok([bad, profile("TheRundownAI", 220_000)])])
        with self.assertRaisesRegex(WatchError, "invalid followers_count"):
            run_watch(self.config, live=True, token="test", transport=transport, now=NOW)

    def test_excessive_configuration_cost_rejected_before_network(self) -> None:
        with self.assertRaisesRegex(WatchError, "exceeds configured cap"):
            run_watch(replace(self.config, max_cost_usd=0.001), live=False, now=NOW)


if __name__ == "__main__":
    unittest.main()
