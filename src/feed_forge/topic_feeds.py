"""Collect public RSS/Atom headlines into a reviewable topic radar."""

from __future__ import annotations

import hashlib
import html
import re
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ATOM = "{http://www.w3.org/2005/Atom}"
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")


class TopicFeedError(ValueError):
    """Invalid topic config or unrecoverable collection failure."""


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    lane: str
    match_any: tuple[str, ...]
    match_all: tuple[tuple[str, ...], ...]
    feed_ids: frozenset[str]
    case_sensitive: frozenset[str] = frozenset()
    show_term_counts: bool = False
    diversify_by_terms: bool = False


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    url: str


@dataclass(frozen=True)
class TopicFeedConfig:
    timezone: str
    max_age_hours: int
    max_items_per_feed: int
    max_items_per_topic: int
    timeout_seconds: int
    max_feed_bytes: int
    topics: tuple[Topic, ...]
    feeds: tuple[Feed, ...]


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise TopicFeedError(f"{name} must be a positive integer")
    return value


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TopicFeedError(f"{name} must be a nonempty string")
    return value.strip()


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TopicFeedError(f"{name} must be an array of strings")
    return tuple(_nonempty_string(item, name) for item in value)


def load_topic_feed_config(path: Path) -> TopicFeedConfig:
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise TopicFeedError(f"Cannot read topic feed config: {error}") from error
    if raw.get("schema_version") != 1:
        raise TopicFeedError("topic feed config requires schema_version = 1")
    settings = raw.get("collection")
    if not isinstance(settings, dict):
        raise TopicFeedError("[collection] is required")
    timezone = _nonempty_string(settings.get("timezone"), "collection.timezone")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise TopicFeedError(f"Unknown timezone: {timezone}") from error
    raw_feeds = raw.get("feeds")
    raw_topics = raw.get("topics")
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise TopicFeedError("At least one [[feeds]] entry is required")
    if not isinstance(raw_topics, list) or not raw_topics:
        raise TopicFeedError("At least one [[topics]] entry is required")
    feeds = []
    feed_ids: set[str] = set()
    for index, entry in enumerate(raw_feeds):
        if not isinstance(entry, dict):
            raise TopicFeedError(f"feeds[{index}] must be a table")
        feed_id = _nonempty_string(entry.get("id"), f"feeds[{index}].id")
        name = _nonempty_string(entry.get("name"), f"feeds[{index}].name")
        url = _nonempty_string(entry.get("url"), f"feeds[{index}].url")
        if feed_id in feed_ids:
            raise TopicFeedError(f"Duplicate feed id: {feed_id}")
        if urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
            raise TopicFeedError(f"Feed {feed_id} needs an HTTPS URL")
        feed_ids.add(feed_id)
        feeds.append(Feed(feed_id, name, url))
    topics = []
    topic_ids: set[str] = set()
    for index, entry in enumerate(raw_topics):
        if not isinstance(entry, dict):
            raise TopicFeedError(f"topics[{index}] must be a table")
        topic_id = _nonempty_string(entry.get("id"), f"topics[{index}].id")
        label = _nonempty_string(entry.get("label"), f"topics[{index}].label")
        lane = _nonempty_string(entry.get("lane"), f"topics[{index}].lane")
        if lane not in {"review", "context_only"}:
            raise TopicFeedError(f"Invalid editorial lane for {topic_id}: {lane}")
        if topic_id in topic_ids:
            raise TopicFeedError(f"Duplicate topic id: {topic_id}")
        match_any = _strings(entry.get("match_any"), f"topics[{index}].match_any")
        raw_match_all = _strings(entry.get("match_all", []), f"topics[{index}].match_all")
        match_all = tuple(tuple(part.strip() for part in group.split("|")) for group in raw_match_all)
        if any(not part for group in match_all for part in group):
            raise TopicFeedError(f"Empty match_all alternative for {topic_id}")
        assigned_feeds = frozenset(_strings(entry.get("feed_ids"), f"topics[{index}].feed_ids"))
        case_sensitive = frozenset(_strings(entry.get("case_sensitive", []), f"topics[{index}].case_sensitive"))
        show_term_counts = entry.get("show_term_counts", False)
        if type(show_term_counts) is not bool:
            raise TopicFeedError(f"show_term_counts must be boolean for {topic_id}")
        diversify_by_terms = entry.get("diversify_by_terms", False)
        if type(diversify_by_terms) is not bool:
            raise TopicFeedError(f"diversify_by_terms must be boolean for {topic_id}")
        if assigned_feeds - feed_ids:
            raise TopicFeedError(f"Unknown feed IDs for {topic_id}: {sorted(assigned_feeds - feed_ids)}")
        if case_sensitive - set(match_any):
            raise TopicFeedError(f"case_sensitive terms must be in match_any for {topic_id}")
        if not (match_any or match_all or assigned_feeds):
            raise TopicFeedError(f"Topic {topic_id} has no matching rule")
        topic_ids.add(topic_id)
        topics.append(Topic(topic_id, label, lane, match_any, match_all, assigned_feeds, case_sensitive, show_term_counts, diversify_by_terms))
    return TopicFeedConfig(
        timezone=timezone,
        max_age_hours=_positive_int(settings.get("max_age_hours"), "collection.max_age_hours"),
        max_items_per_feed=_positive_int(settings.get("max_items_per_feed"), "collection.max_items_per_feed"),
        max_items_per_topic=_positive_int(settings.get("max_items_per_topic"), "collection.max_items_per_topic"),
        timeout_seconds=_positive_int(settings.get("timeout_seconds"), "collection.timeout_seconds"),
        max_feed_bytes=_positive_int(settings.get("max_feed_bytes"), "collection.max_feed_bytes"),
        topics=tuple(topics),
        feeds=tuple(feeds),
    )


def _clean_text(value: str | None) -> str:
    return SPACE_PATTERN.sub(" ", html.unescape(TAG_PATTERN.sub(" ", value or ""))).strip()


def _text(element: ET.Element, path: str) -> str:
    child = element.find(path)
    return "" if child is None else "".join(child.itertext()).strip()


def _published(value: str) -> datetime | None:
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return result.astimezone(UTC) if result.tzinfo else None


def _canonical_url(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    query = urlencode([
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ])
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def parse_feed(body: bytes, feed: Feed, max_items: int) -> list[dict]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise TopicFeedError(f"Invalid XML: {error}") from error
    kind = root.tag.rsplit("}", 1)[-1].lower()
    if kind == "rss":
        elements = root.findall("./channel/item")
    elif kind == "feed":
        elements = root.findall(f"./{ATOM}entry")
    elif kind == "rdf":
        elements = [item for item in root if item.tag.rsplit("}", 1)[-1] == "item"]
    else:
        raise TopicFeedError(f"Unsupported feed root: {root.tag}")
    items = []
    for entry in elements[:max_items]:
        if kind == "feed":
            title = _clean_text(_text(entry, f"{ATOM}title"))
            link = next((el.attrib.get("href", "") for el in entry.findall(f"{ATOM}link") if el.attrib.get("rel", "alternate") == "alternate"), "")
            summary = _clean_text(_text(entry, f"{ATOM}summary") or _text(entry, f"{ATOM}content"))
            date = _text(entry, f"{ATOM}published") or _text(entry, f"{ATOM}updated")
        else:
            title = _clean_text(_text(entry, "title"))
            link = _text(entry, "link")
            summary = _clean_text(_text(entry, "description"))
            date = _text(entry, "pubDate") or _text(entry, "{http://purl.org/dc/elements/1.1/}date")
        url = _canonical_url(link)
        published = _published(date)
        if title and url and published:
            items.append({"title": title, "url": url, "summary": summary[:1000], "published_at": published, "feed_id": feed.id})
    return items


def fetch_feed(feed: Feed, config: TopicFeedConfig) -> bytes:
    request = urllib.request.Request(
        feed.url,
        headers={"User-Agent": "FeedForge/0.1 (public RSS reader)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    )
    with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
        if urlsplit(response.url).scheme != "https":
            raise TopicFeedError("Feed redirected away from HTTPS")
        body = response.read(config.max_feed_bytes + 1)
    if len(body) > config.max_feed_bytes:
        raise TopicFeedError(f"Feed exceeds {config.max_feed_bytes} bytes")
    return body


def _has_term(text: str, term: str, *, case_sensitive: bool = False) -> bool:
    flags = 0 if case_sensitive else re.IGNORECASE
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, flags=flags))


def match_topic(item: dict, topic: Topic) -> list[str]:
    # Many feeds embed entire articles or unrelated-story links in descriptions.
    # Match the headline only to keep brand and safety labels precise.
    text = item["title"]
    any_hits = [term for term in topic.match_any if _has_term(text, term, case_sensitive=term in topic.case_sensitive)]
    all_hits = []
    for alternatives in topic.match_all:
        hit = next((term for term in alternatives if _has_term(text, term)), None)
        if hit is None:
            return []
        all_hits.append(hit)
    if topic.match_all:
        return all_hits + any_hits
    if item["feed_id"] in topic.feed_ids:
        return [f"source:{item['feed_id']}"] + any_hits
    return any_hits


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def collect_topics(config: TopicFeedConfig, *, now: datetime | None = None, fetcher=fetch_feed) -> dict:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise TopicFeedError("now must include a timezone")
    cutoff = now - timedelta(hours=config.max_age_hours)
    results: dict[str, tuple[list[dict] | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(config.feeds))) as executor:
        futures = {executor.submit(fetcher, feed, config): feed for feed in config.feeds}
        for future in as_completed(futures):
            feed = futures[future]
            try:
                items = parse_feed(future.result(), feed, config.max_items_per_feed)
                results[feed.id] = (items, None)
            except (OSError, urllib.error.URLError, TopicFeedError, ValueError) as error:
                results[feed.id] = (None, f"{type(error).__name__}: {error}")
    health = []
    stories: dict[str, dict] = {}
    for feed in config.feeds:
        items, error = results[feed.id]
        if error is not None:
            health.append({"id": feed.id, "name": feed.name, "url": feed.url, "status": "failed", "items_seen": 0, "recent_items": 0, "latest_at": None, "error": error})
            continue
        assert items is not None
        # Do not present feed entries dated in the future as already published.
        recent = [item for item in items if cutoff <= item["published_at"] <= now]
        latest = max((item["published_at"] for item in items), default=None)
        status = (
            "ok" if recent else
            "future_dated" if items and all(item["published_at"] > now for item in items) else
            "stale" if items else "empty"
        )
        health.append({"id": feed.id, "name": feed.name, "url": feed.url, "status": status, "items_seen": len(items), "recent_items": len(recent), "latest_at": _iso(latest) if latest else None, "error": None})
        for item in recent:
            key = item["url"]
            matched = {topic.id: match_topic(item, topic) for topic in config.topics}
            matched = {topic_id: reasons for topic_id, reasons in matched.items() if reasons}
            if not matched:
                continue
            if key not in stories:
                stories[key] = {"id": hashlib.sha256(key.encode()).hexdigest()[:16], "title": item["title"], "url": key, "published_at": _iso(item["published_at"]), "source_ids": [feed.id], "topic_matches": matched}
            else:
                story = stories[key]
                if feed.id not in story["source_ids"]:
                    story["source_ids"].append(feed.id)
                for topic_id, reasons in matched.items():
                    story["topic_matches"].setdefault(topic_id, [])
                    story["topic_matches"][topic_id] = sorted(set(story["topic_matches"][topic_id] + reasons))
    ordered = sorted(stories.values(), key=lambda story: (story["published_at"], story["id"]), reverse=True)
    for story in ordered:
        story["source_ids"].sort()
    topic_results = []
    for topic in config.topics:
        candidates = [story for story in ordered if topic.id in story["topic_matches"]]
        term_counts = ({term: sum(term in story["topic_matches"][topic.id] for story in candidates) for term in topic.match_any} if topic.show_term_counts else None)
        selected = []
        if topic.diversify_by_terms:
            covered: set[str] = set()
            for story in candidates:
                terms = set(story["topic_matches"][topic.id]) - {f"source:{source_id}" for source_id in story["source_ids"]}
                if terms - covered:
                    selected.append(story)
                    covered.update(terms)
                if len(selected) == config.max_items_per_topic:
                    break
        if len(selected) < config.max_items_per_topic:
            selected_ids = {story["id"] for story in selected}
            selected.extend(story for story in candidates if story["id"] not in selected_ids)
        topic_results.append({"id": topic.id, "label": topic.label, "lane": topic.lane, "total_recent": len(candidates), "term_counts": term_counts, "selection": "new_terms_first" if topic.diversify_by_terms else "newest_first", "items": selected[:config.max_items_per_topic]})
    failed_count = sum(row["status"] == "failed" for row in health)
    status = "failed" if failed_count == len(health) else "partial" if failed_count else "ok"
    return {"schema_version": "feed-forge/topic-radar/v1", "generated_at": _iso(now), "timezone": config.timezone, "max_age_hours": config.max_age_hours, "status": status, "source_health": health, "topics": topic_results, "unique_matched_stories": len(ordered), "note": "Headlines are leads, not verified facts or publication-ready drafts. Crime and India geopolitics are context-only. No X write actions occur."}


def _md(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")


def render_topics_markdown(report: dict) -> str:
    zone = ZoneInfo(report["timezone"])
    local_time = datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00")).astimezone(zone)
    lines = ["# Feed Forge topic radar", "", f"Generated: {local_time:%Y-%m-%d %H:%M %Z} · Status: **{report['status']}** · Window: {report['max_age_hours']} hours", "", report["note"], "", "## Known topics", "", "| Topic | Editorial lane | Recent matches |", "| --- | --- | ---: |"]
    for topic in report["topics"]:
        lines.append(f"| {_md(topic['label'])} | `{topic['lane']}` | {topic['total_recent']} |")
    lines.extend(["", "## Recent headlines by topic", ""])
    for topic in report["topics"]:
        lines.extend([f"### {_md(topic['label'])} ({topic['total_recent']})", ""])
        if topic["term_counts"] is not None:
            counts = ", ".join(f"{_md(term)}: {count}" for term, count in topic["term_counts"].items())
            lines.extend([f"Watchlist matches — {counts}.", ""])
        if topic["selection"] == "new_terms_first":
            lines.extend(["Headlines are diversified across matched watchlist names before filling remaining slots by recency.", ""])
        if not topic["items"]:
            lines.extend(["No matching recent headlines in the configured feeds.", ""])
            continue
        for story in topic["items"]:
            timestamp = datetime.fromisoformat(story["published_at"].replace("Z", "+00:00")).astimezone(zone)
            sources = ", ".join(story["source_ids"])
            reasons = ", ".join(story["topic_matches"][topic["id"]])
            lines.append(f"- [{_md(story['title'])}](<{story['url']}>) — {timestamp:%d %b %H:%M %Z}; {sources}; matched: {_md(reasons)}")
        lines.append("")
    lines.extend(["## Source health", "", "| Feed | Status | Recent / seen | Latest item | Detail |", "| --- | --- | ---: | --- | --- |"])
    for source in report["source_health"]:
        lines.append(f"| [{_md(source['name'])}](<{source['url']}>) | `{source['status']}` | {source['recent_items']} / {source['items_seen']} | {source['latest_at'] or '—'} | {_md(source['error'] or '')} |")
    lines.append("")
    return "\n".join(lines)
