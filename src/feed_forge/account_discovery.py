"""Cost-bounded X account discovery for the Feed Forge pilot."""

from __future__ import annotations

import math
import os
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .x_api import (
    ApiResponse,
    OAuth1Transport,
    Transport,
    XApiClient,
    rate_limit_from_headers,
)
from .x_diagnostics import ALLOWED_API_HOSTS, ConfigurationError


REPORT_SCHEMA_VERSION = "feed-forge/account-discovery/v1"
WORD_PATTERN = re.compile(r"[a-z0-9+#]+")


@dataclass(frozen=True)
class QueryConfig:
    name: str
    topic: str
    query: str


@dataclass(frozen=True)
class PoolConfig:
    name: str
    minimum_followers: int
    maximum_followers: int | None
    target_count: int


@dataclass(frozen=True)
class DiscoveryConfig:
    base_url: str
    timeout_seconds: float
    app_token_env: str
    user_token_env: str
    oauth1_consumer_key_env: str
    oauth1_consumer_secret_env: str
    oauth1_access_token_env: str
    oauth1_access_token_secret_env: str
    operator_username: str
    timezone: str
    max_cost_usd: float
    post_read_usd: float
    user_read_usd: float
    search_results_per_query: int
    profile_lookup_limit: int
    timeline_finalist_limit: int
    timeline_posts_per_finalist: int
    require_verified: bool
    excluded_verified_types: frozenset[str]
    exclude_organization_accounts: bool
    exclude_already_followed: bool
    minimum_recent_relevant_posts: int
    pools: tuple[PoolConfig, ...]
    topic_mix: Mapping[str, int]
    scoring_weights: Mapping[str, float]
    negative_keywords: tuple[str, ...]
    organization_keywords: tuple[str, ...]
    queries: tuple[QueryConfig, ...]
    keywords: Mapping[str, tuple[str, ...]]
    india_signals: tuple[str, ...]


class DiscoveryError(RuntimeError):
    """Raised when live discovery cannot safely produce a report."""


@dataclass(frozen=True)
class DiscoveryAuthentication:
    mode: str
    token: str
    transport: Transport | None


class CostBudget:
    def __init__(self, maximum_usd: float) -> None:
        self.maximum_usd = maximum_usd
        self.projected_usd = 0.0
        self.actual_estimate_usd = 0.0
        self.entries: list[dict[str, Any]] = []

    def reserve(
        self,
        *,
        operation: str,
        resource_type: str,
        maximum_resources: int,
        unit_cost_usd: float,
    ) -> None:
        projected = maximum_resources * unit_cost_usd
        if self.projected_usd + projected > self.maximum_usd + 1e-9:
            raise DiscoveryError(
                f"Cost budget would be exceeded by {operation}: "
                f"${self.projected_usd + projected:.3f} > ${self.maximum_usd:.2f}"
            )
        self.projected_usd += projected
        self.entries.append(
            {
                "operation": operation,
                "resource_type": resource_type,
                "maximum_resources": maximum_resources,
                "returned_resources": None,
                "unit_cost_usd": unit_cost_usd,
                "projected_cost_usd": round(projected, 4),
                "estimated_returned_cost_usd": None,
            }
        )

    def record_returned(self, returned_resources: int) -> None:
        entry = self.entries[-1]
        entry["returned_resources"] = returned_resources
        actual = returned_resources * float(entry["unit_cost_usd"])
        entry["estimated_returned_cost_usd"] = round(actual, 4)
        self.actual_estimate_usd += actual

    def as_dict(self) -> dict[str, Any]:
        return {
            "maximum_usd": self.maximum_usd,
            "projected_usd": round(self.projected_usd, 4),
            "estimated_returned_cost_usd": round(self.actual_estimate_usd, 4),
            "entries": self.entries,
            "note": (
                "Returned-resource cost is an estimate from configured rates; "
                "the X Developer Console is authoritative."
            ),
        }


def load_discovery_config(path: Path) -> DiscoveryConfig:
    try:
        with path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except FileNotFoundError as error:
        raise ConfigurationError(f"Configuration file not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"Invalid TOML in {path}: {error}") from error

    if raw.get("schema_version") != 1:
        raise ConfigurationError("schema_version must be 1")

    operator = _table(raw, "operator")
    x_api = _table(raw, "x_api")
    budget = _table(raw, "budget")
    discovery = _table(raw, "discovery")
    pools_raw = _table(raw, "pools")
    filters = _table(raw, "filters")
    keywords_raw = _table(raw, "keywords")
    india = _table(raw, "india_signals")
    queries_raw = raw.get("queries")
    if not isinstance(queries_raw, list) or not queries_raw:
        raise ConfigurationError("At least one [[queries]] entry is required")

    pools: list[PoolConfig] = []
    for name, value in pools_raw.items():
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"pools.{name} must be a table")
        pools.append(
            PoolConfig(
                name=name,
                minimum_followers=_integer(value, "minimum_followers"),
                maximum_followers=_optional_integer(value, "maximum_followers"),
                target_count=_integer(value, "target_count"),
            )
        )

    queries = tuple(
        QueryConfig(
            name=_string(value, "name"),
            topic=_string(value, "topic"),
            query=_string(value, "query"),
        )
        for value in queries_raw
        if isinstance(value, Mapping)
    )
    if len(queries) != len(queries_raw):
        raise ConfigurationError("Every [[queries]] entry must be a table")

    config = DiscoveryConfig(
        base_url=_string(x_api, "base_url").rstrip("/"),
        timeout_seconds=_number(x_api, "timeout_seconds"),
        app_token_env=_string(x_api, "app_token_env"),
        user_token_env=_string(x_api, "user_token_env"),
        oauth1_consumer_key_env=_string(x_api, "oauth1_consumer_key_env"),
        oauth1_consumer_secret_env=_string(x_api, "oauth1_consumer_secret_env"),
        oauth1_access_token_env=_string(x_api, "oauth1_access_token_env"),
        oauth1_access_token_secret_env=_string(
            x_api, "oauth1_access_token_secret_env"
        ),
        operator_username=_string(operator, "username").lstrip("@"),
        timezone=_string(operator, "timezone"),
        max_cost_usd=_number(budget, "max_estimated_cost_usd"),
        post_read_usd=_number(budget, "post_read_usd"),
        user_read_usd=_number(budget, "user_read_usd"),
        search_results_per_query=_integer(discovery, "search_results_per_query"),
        profile_lookup_limit=_integer(discovery, "profile_lookup_limit"),
        timeline_finalist_limit=_integer(discovery, "timeline_finalist_limit"),
        timeline_posts_per_finalist=_integer(
            discovery, "timeline_posts_per_finalist"
        ),
        require_verified=_boolean(discovery, "require_verified"),
        excluded_verified_types=frozenset(
            value.casefold()
            for value in _string_list(discovery, "excluded_verified_types")
        ),
        exclude_organization_accounts=_boolean(
            discovery, "exclude_organization_accounts"
        ),
        exclude_already_followed=_boolean(discovery, "exclude_already_followed"),
        minimum_recent_relevant_posts=_integer(
            discovery, "minimum_recent_relevant_posts"
        ),
        pools=tuple(pools),
        topic_mix=_integer_mapping(_table(raw, "topic_mix"), "topic_mix"),
        scoring_weights=_number_mapping(_table(raw, "scoring"), "scoring"),
        negative_keywords=_string_list(filters, "negative_keywords"),
        organization_keywords=_string_list(filters, "organization_keywords"),
        queries=queries,
        keywords={
            name: _string_list(value, "terms")
            for name, value in keywords_raw.items()
            if isinstance(value, Mapping)
        },
        india_signals=_string_list(india, "terms"),
    )
    _validate_config(config)
    return config


def resolve_discovery_authentication(
    config: DiscoveryConfig,
    environment: Mapping[str, str] | None = None,
    *,
    transport: Transport | None = None,
) -> DiscoveryAuthentication:
    environment = environment if environment is not None else os.environ
    oauth_names = (
        config.oauth1_consumer_key_env,
        config.oauth1_consumer_secret_env,
        config.oauth1_access_token_env,
        config.oauth1_access_token_secret_env,
    )
    oauth_values = tuple(environment.get(name, "").strip() for name in oauth_names)
    if any(oauth_values) and not all(oauth_values):
        missing = ", ".join(
            name for name, value in zip(oauth_names, oauth_values) if not value
        )
        raise ConfigurationError(f"Incomplete OAuth 1.0a credentials; missing {missing}")
    if all(oauth_values):
        return DiscoveryAuthentication(
            mode="oauth1_user_context",
            token="oauth1-signed-request",
            transport=OAuth1Transport(
                consumer_key=oauth_values[0],
                consumer_secret=oauth_values[1],
                access_token=oauth_values[2],
                access_token_secret=oauth_values[3],
                transport=transport,
            ),
        )

    user_token = environment.get(config.user_token_env, "").strip()
    if user_token:
        return DiscoveryAuthentication(
            mode="oauth2_user_context", token=user_token, transport=transport
        )
    app_token = environment.get(config.app_token_env, "").strip()
    if app_token:
        return DiscoveryAuthentication(
            mode="app_only", token=app_token, transport=transport
        )
    raise ConfigurationError(
        "No X credential is available. Set all four OAuth 1.0a variables, set "
        f"{config.user_token_env}, or set {config.app_token_env}."
    )


def run_account_discovery(
    config: DiscoveryConfig,
    token: str,
    *,
    transport: Transport | None = None,
    now: datetime | None = None,
    authentication_mode: str = "user_context",
) -> dict[str, Any]:
    if not token.strip():
        raise ConfigurationError("A user-context X credential is required")
    client = XApiClient(
        base_url=config.base_url,
        token=token,
        timeout_seconds=config.timeout_seconds,
        transport=transport,
    )
    budget = CostBudget(config.max_cost_usd)
    search_candidates: dict[str, dict[str, Any]] = {}
    requests: list[dict[str, Any]] = []

    for query in config.queries:
        budget.reserve(
            operation=f"search:{query.name}",
            resource_type="post",
            maximum_resources=config.search_results_per_query,
            unit_cost_usd=config.post_read_usd,
        )
        response = client.get(
            "/2/tweets/search/recent",
            {
                "query": query.query,
                "max_results": config.search_results_per_query,
                "post.fields": (
                    "id,text,author_id,created_at,lang,public_metrics,"
                    "conversation_id,referenced_posts"
                ),
            },
        )
        posts = _response_items(response, f"search:{query.name}")
        budget.record_returned(len(posts))
        requests.append(_request_record(f"search:{query.name}", response, len(posts)))
        for post in posts:
            author_id = post.get("author_id")
            if not isinstance(author_id, str) or not author_id:
                continue
            selected_topic = _best_topic(str(post.get("text", "")), query.topic, config)
            score = _score_post(post, selected_topic, config, now=now)
            if score["rejected"]:
                continue
            candidate = search_candidates.setdefault(
                author_id,
                {
                    "id": author_id,
                    "topic": selected_topic,
                    "discovery_posts": [],
                    "search_score": 0.0,
                    "score_components": {},
                },
            )
            candidate["discovery_posts"].append(_public_post(post))
            if score["total"] > candidate["search_score"]:
                candidate["topic"] = selected_topic
                candidate["search_score"] = score["total"]
                candidate["score_components"] = score["components"]

    shortlist = _select_by_topic_mix(
        tuple(search_candidates.values()),
        config.profile_lookup_limit,
        config.topic_mix,
    )

    profiles: dict[str, Mapping[str, Any]] = {}
    if shortlist:
        budget.reserve(
            operation="profile_lookup",
            resource_type="user",
            maximum_resources=len(shortlist),
            unit_cost_usd=config.user_read_usd,
        )
        response = client.get(
            "/2/users",
            {
                "ids": ",".join(item["id"] for item in shortlist),
                "user.fields": (
                    "id,name,username,created_at,description,location,protected,"
                    "public_metrics,verified,verified_type,connection_status"
                ),
            },
        )
        users = _response_items(response, "profile_lookup")
        budget.record_returned(len(users))
        requests.append(_request_record("profile_lookup", response, len(users)))
        profiles = {
            str(user.get("id")): user for user in users if isinstance(user.get("id"), str)
        }

    rejected: list[dict[str, Any]] = []
    qualified: list[dict[str, Any]] = []
    for candidate in shortlist:
        profile = profiles.get(candidate["id"])
        if profile is None:
            rejected.append(_rejection(candidate, "profile_not_returned"))
            continue
        result, reason = _qualify_profile(candidate, profile, config)
        if result is None:
            rejected.append(_rejection(candidate, reason or "profile_rejected", profile))
            continue
        qualified.append(result)

    qualified.sort(key=lambda item: (-item["search_score"], item["username"].casefold()))
    finalists = _select_by_topic_mix(
        tuple(qualified), config.timeline_finalist_limit, config.topic_mix
    )
    for candidate in finalists:
        budget.reserve(
            operation=f"timeline:@{candidate['username']}",
            resource_type="post",
            maximum_resources=config.timeline_posts_per_finalist,
            unit_cost_usd=config.post_read_usd,
        )
        response = client.get(
            f"/2/users/{candidate['id']}/tweets",
            {
                "max_results": config.timeline_posts_per_finalist,
                "exclude": "retweets",
                "tweet.fields": "id,text,author_id,created_at,lang,public_metrics",
            },
        )
        posts = _response_items(response, f"timeline:@{candidate['username']}")
        budget.record_returned(len(posts))
        requests.append(
            _request_record(f"timeline:@{candidate['username']}", response, len(posts))
        )
        relevant_posts = [
            post
            for post in posts
            if _topic_match_count(str(post.get("text", "")), candidate["topic"], config)
            > 0
        ]
        candidate["timeline"] = {
            "posts_checked": len(posts),
            "relevant_posts": len(relevant_posts),
            "minimum_required": config.minimum_recent_relevant_posts,
        }
        if len(relevant_posts) < config.minimum_recent_relevant_posts:
            candidate["status"] = "needs_review"
        elif candidate["follow_status"] == "not_following":
            candidate["status"] = "recommended"
        else:
            candidate["status"] = "needs_follow_check"
        candidate["recent_posts"] = [_public_post(post) for post in posts]

    finalist_ids = {candidate["id"] for candidate in finalists}
    for candidate in qualified:
        if candidate["id"] in finalist_ids:
            continue
        candidate["status"] = "profile_qualified"
        candidate["timeline"] = None
        candidate["recent_posts"] = []

    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "operator_username": config.operator_username,
        "authentication": {"mode": authentication_mode},
        "schedule": {"cadence": "daily", "local_time": "06:00", "timezone": config.timezone},
        "policy": {
            "verified_required": config.require_verified,
            "excluded_verified_types": sorted(config.excluded_verified_types),
            "organizations_excluded": config.exclude_organization_accounts,
            "already_followed_excluded": config.exclude_already_followed,
            "topic_mix_per_20": dict(config.topic_mix),
            "pools": [pool.__dict__ for pool in config.pools],
        },
        "summary": {
            "posts_examined": sum(
                entry["returned_resources"] or 0
                for entry in budget.entries
                if entry["operation"].startswith("search:")
            ),
            "authors_shortlisted": len(shortlist),
            "profiles_qualified": len(qualified),
            "recommended": sum(item["status"] == "recommended" for item in qualified),
            "needs_review": sum(item["status"] == "needs_review" for item in qualified),
            "needs_follow_check": sum(
                item["status"] == "needs_follow_check" for item in qualified
            ),
            "profile_qualified": sum(
                item["status"] == "profile_qualified" for item in qualified
            ),
            "rejected": len(rejected),
        },
        "candidates": qualified,
        "rejections": rejected,
        "cost": budget.as_dict(),
        "requests": requests,
    }


def render_discovery_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    cost = report["cost"]
    lines = [
        "# Daily X account discovery",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Operator: `@{report['operator_username']}`",
        "- Schedule: `06:00 Asia/Kolkata` daily",
        (
            f"- Result: {summary['recommended']} recommended, "
            f"{summary['needs_review']} needs review, "
            f"{summary['needs_follow_check']} needs follow check, "
            f"{summary['profile_qualified']} profile-qualified"
        ),
        (
            f"- Estimated returned-resource cost: "
            f"`${cost['estimated_returned_cost_usd']:.3f}` "
            f"(worst-case reserved `${cost['projected_usd']:.3f}` / "
            f"`${cost['maximum_usd']:.2f}` cap)"
        ),
        "",
        "## Candidates",
        "",
        "| Handle | Pool | Topic | Followers | Follow status | Verification | Score | Status |",
        "|---|---|---|---:|---|---|---:|---|",
    ]
    candidates = report.get("candidates", [])
    if not candidates:
        lines.append("| — | — | — | — | — | — | — | No qualified candidates |")
    for candidate in candidates:
        lines.append(
            "| @{username} | {pool} | {topic} | {followers} | {follow} | "
            "{verified} | {score:.1f} | {status} |".format(
                username=_escape(candidate["username"]),
                pool=_escape(candidate["pool"]),
                topic=_escape(candidate["topic"]),
                followers=candidate["followers_count"],
                follow=_escape(candidate["follow_status"]),
                verified=_escape(candidate.get("verified_type") or "verified"),
                score=candidate["search_score"],
                status=_escape(candidate["status"]),
            )
        )

    lines.extend(
        [
            "",
            "## Cost ledger",
            "",
            "| Operation | Max resources | Returned | Estimated cost |",
            "|---|---:|---:|---:|",
        ]
    )
    for entry in cost["entries"]:
        lines.append(
            "| {operation} | {maximum} | {returned} | ${actual:.3f} |".format(
                operation=_escape(entry["operation"]),
                maximum=entry["maximum_resources"],
                returned=entry["returned_resources"],
                actual=entry["estimated_returned_cost_usd"] or 0,
            )
        )
    lines.extend(
        [
            "",
            "Costs are estimates from configured per-resource rates. "
            "The X Developer Console is authoritative.",
            "No account was followed and no post was created, liked, or replied to.",
            "",
        ]
    )
    return "\n".join(lines)


def _score_post(
    post: Mapping[str, Any],
    topic: str,
    config: DiscoveryConfig,
    *,
    now: datetime | None,
) -> dict[str, Any]:
    text = str(post.get("text", ""))
    lowered = text.casefold()
    if any(term.casefold() in lowered for term in config.negative_keywords):
        return {"rejected": True, "total": 0.0, "components": {}}

    topic_matches = _topic_match_count(text, topic, config)
    all_matches = sum(
        _topic_match_count(text, name, config) for name in config.keywords
    )
    public_metrics = post.get("public_metrics")
    metrics = public_metrics if isinstance(public_metrics, Mapping) else {}
    engagement = sum(
        int(metrics.get(name, 0) or 0)
        for name in (
            "reply_count",
            "like_count",
            "quote_count",
            "repost_count",
            "retweet_count",
        )
    )
    india_matches = _match_count(text, config.india_signals)
    freshness = _freshness_score(post.get("created_at"), now)
    components = {
        "topic_fit": min(100.0, 45.0 + topic_matches * 15.0),
        "keyword_depth": min(100.0, all_matches * 18.0),
        "freshness": freshness,
        "conversation_potential": min(100.0, math.log2(engagement + 1) * 15.0),
        "india_signal": min(100.0, india_matches * 35.0),
        "quality": 100.0 if len(text.strip()) >= 40 else 55.0,
    }
    total = sum(
        components[name] * config.scoring_weights[name]
        for name in config.scoring_weights
    )
    return {
        "rejected": False,
        "total": round(total, 2),
        "components": {name: round(value, 2) for name, value in components.items()},
    }


def _qualify_profile(
    candidate: Mapping[str, Any],
    profile: Mapping[str, Any],
    config: DiscoveryConfig,
) -> tuple[dict[str, Any] | None, str | None]:
    if config.require_verified and profile.get("verified") is not True:
        return None, "not_verified"
    verified_type = str(profile.get("verified_type") or "").casefold()
    if verified_type in config.excluded_verified_types:
        return None, f"excluded_verification_type:{verified_type}"
    if profile.get("protected") is True:
        return None, "protected_account"

    description = str(profile.get("description") or "")
    name = str(profile.get("name") or "")
    if config.exclude_organization_accounts and _looks_like_organization(
        name, description, profile, config.organization_keywords
    ):
        return None, "organization_account"

    metrics = profile.get("public_metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    followers = int(metrics.get("followers_count", 0) or 0)
    pool = _pool_for_followers(followers, config.pools)
    if pool is None:
        return None, "outside_follower_pools"

    statuses = profile.get("connection_status")
    relationship_known = isinstance(statuses, list)
    status_values = {
        str(value).casefold()
        for value in statuses
        if isinstance(statuses, list) and isinstance(value, str)
    }
    already_followed = bool({"following", "following_requested"} & status_values)
    if config.exclude_already_followed and already_followed:
        return None, "already_followed"
    follow_status = (
        "not_following" if relationship_known and not already_followed else "unknown"
    )

    return (
        {
            "id": str(profile.get("id")),
            "username": str(profile.get("username") or ""),
            "name": name,
            "description": description,
            "location": profile.get("location"),
            "followers_count": followers,
            "following_count": int(metrics.get("following_count", 0) or 0),
            "verified": profile.get("verified") is True,
            "verified_type": profile.get("verified_type"),
            "follow_status": follow_status,
            "pool": pool,
            "topic": candidate["topic"],
            "search_score": candidate["search_score"],
            "score_components": candidate["score_components"],
            "discovery_posts": candidate["discovery_posts"],
        },
        None,
    )


def _looks_like_organization(
    name: str,
    description: str,
    profile: Mapping[str, Any],
    keywords: Sequence[str],
) -> bool:
    verified_type = str(profile.get("verified_type") or "").casefold()
    if verified_type in {"business", "government"}:
        return True
    text = f"{name} {description}".casefold()
    return any(keyword.casefold() in text for keyword in keywords)


def _response_items(response: ApiResponse, operation: str) -> list[Mapping[str, Any]]:
    if response.status is None or not 200 <= response.status < 300:
        detail = "network error" if response.status is None else f"HTTP {response.status}"
        raise DiscoveryError(f"{operation} failed: {detail}")
    if not isinstance(response.body, Mapping):
        raise DiscoveryError(f"{operation} returned a non-object response")
    data = response.body.get("data", [])
    if data is None:
        return []
    if not isinstance(data, list):
        raise DiscoveryError(f"{operation} returned invalid data")
    return [item for item in data if isinstance(item, Mapping)]


def _request_record(operation: str, response: ApiResponse, count: int) -> dict[str, Any]:
    return {
        "operation": operation,
        "http_status": response.status,
        "duration_ms": response.duration_ms,
        "returned_resources": count,
        "rate_limit": rate_limit_from_headers(response.headers),
    }


def _public_post(post: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: post.get(key)
        for key in ("id", "author_id", "created_at", "text", "public_metrics")
        if key in post
    }


def _rejection(
    candidate: Mapping[str, Any],
    reason: str,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "username": profile.get("username") if profile else None,
        "reason": reason,
    }


def _topic_match_count(text: str, topic: str, config: DiscoveryConfig) -> int:
    return _match_count(text, config.keywords.get(topic, ()))


def _best_topic(text: str, fallback: str, config: DiscoveryConfig) -> str:
    scores = {
        topic: _topic_match_count(text, topic, config) for topic in config.topic_mix
    }
    best_score = max(scores.values(), default=0)
    if best_score == 0:
        return fallback
    winners = [topic for topic in config.topic_mix if scores.get(topic) == best_score]
    return fallback if fallback in winners else winners[0]


def _select_by_topic_mix(
    candidates: Sequence[Mapping[str, Any]],
    limit: int,
    topic_mix: Mapping[str, int],
) -> list[dict[str, Any]]:
    ordered = sorted(
        (candidate if isinstance(candidate, dict) else dict(candidate) for candidate in candidates),
        key=lambda item: (-float(item["search_score"]), str(item["id"])),
    )
    if len(ordered) <= limit:
        return ordered

    total_weight = sum(topic_mix.values())
    raw_quotas = {
        topic: limit * weight / total_weight for topic, weight in topic_mix.items()
    }
    quotas = {topic: math.floor(value) for topic, value in raw_quotas.items()}
    remainder = limit - sum(quotas.values())
    remainder_order = sorted(
        topic_mix,
        key=lambda topic: (-(raw_quotas[topic] - quotas[topic]), -topic_mix[topic], topic),
    )
    for topic in remainder_order[:remainder]:
        quotas[topic] += 1

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for topic in topic_mix:
        topic_candidates = [item for item in ordered if item["topic"] == topic]
        for item in topic_candidates[: quotas[topic]]:
            selected.append(item)
            selected_ids.add(str(item["id"]))
    for item in ordered:
        if len(selected) >= limit:
            break
        if str(item["id"]) not in selected_ids:
            selected.append(item)
            selected_ids.add(str(item["id"]))
    return selected


def _match_count(text: str, terms: Sequence[str]) -> int:
    lowered = text.casefold()
    words = set(WORD_PATTERN.findall(lowered))
    count = 0
    for term in terms:
        folded = term.casefold()
        if " " in folded or "#" in folded or "+" in folded:
            count += folded in lowered
        else:
            count += folded in words
    return count


def _freshness_score(created_at: Any, now: datetime | None) -> float:
    if not isinstance(created_at, str):
        return 0.0
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    current = now or datetime.now(UTC)
    age_hours = max(0.0, (current.astimezone(UTC) - created.astimezone(UTC)).total_seconds() / 3600)
    return max(0.0, 100.0 - age_hours * 4.0)


def _pool_for_followers(followers: int, pools: Sequence[PoolConfig]) -> str | None:
    for pool in pools:
        if followers < pool.minimum_followers:
            continue
        if pool.maximum_followers is None or followers <= pool.maximum_followers:
            return pool.name
    return None


def _validate_config(config: DiscoveryConfig) -> None:
    parsed = urlparse(config.base_url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_API_HOSTS:
        raise ConfigurationError("x_api.base_url must be an official HTTPS X API host")
    environment_names = (
        config.app_token_env,
        config.user_token_env,
        config.oauth1_consumer_key_env,
        config.oauth1_consumer_secret_env,
        config.oauth1_access_token_env,
        config.oauth1_access_token_secret_env,
    )
    if any(not name.isidentifier() for name in environment_names):
        raise ConfigurationError("X credential environment names must be identifiers")
    if not 0 < config.max_cost_usd <= 10:
        raise ConfigurationError("budget.max_estimated_cost_usd must be between 0 and 10")
    if config.search_results_per_query < 10 or config.search_results_per_query > 100:
        raise ConfigurationError("search_results_per_query must be between 10 and 100")
    if not 1 <= config.profile_lookup_limit <= 100:
        raise ConfigurationError("profile_lookup_limit must be between 1 and 100")
    if not 1 <= config.timeline_finalist_limit <= config.profile_lookup_limit:
        raise ConfigurationError("timeline_finalist_limit must not exceed profile_lookup_limit")
    if not 5 <= config.timeline_posts_per_finalist <= 100:
        raise ConfigurationError("timeline_posts_per_finalist must be between 5 and 100")
    if not config.pools:
        raise ConfigurationError("At least one follower pool is required")
    if sum(config.topic_mix.values()) != 20:
        raise ConfigurationError("topic_mix must allocate exactly 20 accounts")
    if set(config.topic_mix) != set(config.keywords):
        raise ConfigurationError("topic_mix and keywords must define the same topics")
    for query in config.queries:
        if len(query.query) > 512:
            raise ConfigurationError(f"Query {query.name} exceeds the 512 character limit")
        if query.topic not in config.keywords:
            raise ConfigurationError(f"Query {query.name} references unknown topic {query.topic}")
        if config.require_verified and "is:verified" not in query.query:
            raise ConfigurationError(f"Query {query.name} must include is:verified")
    if not math.isclose(sum(config.scoring_weights.values()), 1.0, abs_tol=1e-9):
        raise ConfigurationError("scoring weights must sum to 1.0")
    required_scores = {
        "topic_fit",
        "keyword_depth",
        "freshness",
        "conversation_potential",
        "india_signal",
        "quality",
    }
    if set(config.scoring_weights) != required_scores:
        raise ConfigurationError("scoring must define exactly the supported components")
    projected = (
        len(config.queries) * config.search_results_per_query * config.post_read_usd
        + config.profile_lookup_limit * config.user_read_usd
        + config.timeline_finalist_limit
        * config.timeline_posts_per_finalist
        * config.post_read_usd
    )
    if projected > config.max_cost_usd + 1e-9:
        raise ConfigurationError(
            f"Configured worst-case cost ${projected:.3f} exceeds "
            f"the ${config.max_cost_usd:.2f} run cap"
        )


def _table(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Missing or invalid [{key}] section")
    return value


def _string(parent: Mapping[str, Any], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def _integer(parent: Mapping[str, Any], key: str) -> int:
    value = parent.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"{key} must be an integer")
    return value


def _optional_integer(parent: Mapping[str, Any], key: str) -> int | None:
    value = parent.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"{key} must be an integer")
    return value


def _number(parent: Mapping[str, Any], key: str) -> float:
    value = parent.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"{key} must be a number")
    return float(value)


def _boolean(parent: Mapping[str, Any], key: str) -> bool:
    value = parent.get(key)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{key} must be true or false")
    return value


def _string_list(parent: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = parent.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ConfigurationError(f"{key} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _integer_mapping(parent: Mapping[str, Any], name: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, value in parent.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ConfigurationError(f"{name}.{key} must be a non-negative integer")
        result[key] = value
    return result


def _number_mapping(parent: Mapping[str, Any], name: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in parent.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ConfigurationError(f"{name}.{key} must be a non-negative number")
        result[key] = float(value)
    return result


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
