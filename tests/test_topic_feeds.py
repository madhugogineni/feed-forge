from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from feed_forge.topic_feeds import (
    Feed,
    Topic,
    TopicFeedConfig,
    TopicFeedError,
    collect_topics,
    load_topic_feed_config,
    match_topic,
    parse_feed,
    render_topics_markdown,
)


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Frido launches a new ergonomic chair</title>
<link>https://example.com/frido?utm_source=rss</link>
<pubDate>Wed, 23 Sep 2026 06:00:00 GMT</pubDate>
<description>Indian consumer brand news.</description></item>
<item><title>Old brand story</title><link>https://example.com/old</link>
<pubDate>Wed, 01 Jul 2026 06:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Apple Music adds a new feature</title>
<link rel="alternate" href="https://example.com/music"/>
<updated>2026-09-23T07:00:00Z</updated><summary>Product update</summary></entry>
</feed>"""


class TopicFeedTests(unittest.TestCase):
    def test_pilot_config_loads_and_has_requested_topics(self) -> None:
        config = load_topic_feed_config(Path("config/topic_feeds.toml"))
        topics = {topic.id: topic for topic in config.topics}
        self.assertIn("Frido", topics["indian_brands"].match_any)
        self.assertTrue(topics["indian_brands"].diversify_by_terms)
        self.assertEqual("context_only", topics["crime"].lane)
        self.assertEqual("context_only", topics["india_geopolitics"].lane)
        self.assertIn("local_practical", topics)
        self.assertGreater(len(config.feeds), 15)

    def test_parses_rss_and_atom_and_rejects_other_xml(self) -> None:
        feed = Feed("test", "Test", "https://example.com/feed")
        rss_items = parse_feed(RSS, feed, 10)
        atom_items = parse_feed(ATOM, feed, 10)
        self.assertEqual("https://example.com/frido", rss_items[0]["url"])
        self.assertEqual("Apple Music adds a new feature", atom_items[0]["title"])
        with self.assertRaises(TopicFeedError):
            parse_feed(b"<html></html>", feed, 10)

    def test_topic_matching_uses_boundaries_and_all_groups(self) -> None:
        brand = Topic("brand", "Brands", "review", ("Frido",), (), frozenset())
        geopolitical = Topic("geo", "Geo", "context_only", (), (("India", "Indian"), ("border", "summit")), frozenset())
        item = {"title": "Frido grows in India", "summary": "No politics", "feed_id": "test"}
        self.assertEqual(["Frido"], match_topic(item, brand))
        self.assertEqual([], match_topic(item, geopolitical))
        item["title"] = "India and Nepal hold a border summit"
        self.assertEqual(["India", "border"], match_topic(item, geopolitical))
        item["title"] = "Fridolin launches a chair"
        self.assertEqual([], match_topic(item, brand))
        boat = Topic("boat", "Brands", "review", ("boAt",), (), frozenset(), frozenset({"boAt"}))
        item["title"] = "Cargo boat crashes near Singapore"
        self.assertEqual([], match_topic(item, boat))
        item["title"] = "boAt launches new earphones"
        self.assertEqual(["boAt"], match_topic(item, boat))

    def test_collection_reports_matches_staleness_and_failures(self) -> None:
        config = TopicFeedConfig(
            timezone="Asia/Kolkata",
            max_age_hours=48,
            max_items_per_feed=10,
            max_items_per_topic=5,
            timeout_seconds=3,
            max_feed_bytes=10000,
            topics=(Topic("brands", "Indian brands", "review", ("Frido",), (), frozenset()),),
            feeds=(Feed("first", "First", "https://example.com/one"), Feed("duplicate", "Duplicate", "https://example.com/two"), Feed("bad", "Bad", "https://example.com/bad")),
        )

        def fetcher(feed: Feed, _config: TopicFeedConfig) -> bytes:
            if feed.id == "bad":
                raise TopicFeedError("Unavailable")
            return RSS

        report = collect_topics(config, now=datetime(2026, 9, 23, 12, tzinfo=UTC), fetcher=fetcher)
        self.assertEqual("partial", report["status"])
        self.assertEqual(1, report["unique_matched_stories"])
        self.assertEqual(["duplicate", "first"], report["topics"][0]["items"][0]["source_ids"])
        self.assertEqual("failed", report["source_health"][2]["status"])
        self.assertIn("Frido", render_topics_markdown(report))

    def test_empty_and_stale_are_visible(self) -> None:
        config = TopicFeedConfig("UTC", 24, 10, 5, 3, 10000,
                                 (Topic("brands", "Brands", "review", ("Frido",), (), frozenset()),),
                                 (Feed("old", "Old", "https://example.com/old"),))
        report = collect_topics(config, now=datetime(2026, 10, 1, tzinfo=UTC), fetcher=lambda _feed, _config: RSS)
        self.assertEqual("stale", report["source_health"][0]["status"])
        self.assertEqual(0, report["unique_matched_stories"])

    def test_brand_headlines_are_diversified(self) -> None:
        rss = b"""<rss><channel>
        <item><title>Zepto raises funding</title><link>https://example.com/z1</link><pubDate>Wed, 23 Sep 2026 10:00:00 GMT</pubDate></item>
        <item><title>Zepto raises more funding</title><link>https://example.com/z2</link><pubDate>Wed, 23 Sep 2026 09:00:00 GMT</pubDate></item>
        <item><title>Frido launches chair</title><link>https://example.com/f</link><pubDate>Wed, 23 Sep 2026 08:00:00 GMT</pubDate></item>
        </channel></rss>"""
        config = TopicFeedConfig("UTC", 24, 10, 2, 3, 10000,
                                 (Topic("brands", "Brands", "review", ("Zepto", "Frido"), (), frozenset(), diversify_by_terms=True),),
                                 (Feed("brand", "Brand", "https://example.com/brand"),))
        report = collect_topics(config, now=datetime(2026, 9, 23, 12, tzinfo=UTC), fetcher=lambda _feed, _config: rss)
        titles = [story["title"] for story in report["topics"][0]["items"]]
        self.assertEqual(["Zepto raises funding", "Frido launches chair"], titles)

    def test_future_dated_story_is_not_reported(self) -> None:
        config = TopicFeedConfig("UTC", 48, 10, 5, 3, 10000,
                                 (Topic("brands", "Brands", "review", ("Frido",), (), frozenset()),),
                                 (Feed("feed", "Feed", "https://example.com/feed"),))
        report = collect_topics(config, now=datetime(2026, 9, 23, 5, tzinfo=UTC), fetcher=lambda _feed, _config: RSS)
        self.assertEqual(0, report["unique_matched_stories"])
        self.assertEqual("stale", report["source_health"][0]["status"])

    def test_invalid_config_fails_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text('schema_version = 1\n[collection]\ntimezone = "UTC"\n', encoding="utf-8")
            with self.assertRaisesRegex(TopicFeedError, "At least one"):
                load_topic_feed_config(path)


if __name__ == "__main__":
    unittest.main()
