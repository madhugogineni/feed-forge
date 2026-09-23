"""Cost-bounded, human-review watch of verified high-reach X accounts."""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .x_api import (
    ApiResponse, ResponseStructureError, Transport, XApiClient,
    parse_x_response, public_api_errors,
)


class WatchError(ValueError):
    """Invalid configuration or an unsafe/incomplete live response."""


@dataclass(frozen=True)
class Lane:
    name: str
    handles: tuple[str, ...]
    minimum_followers: int
    maximum_followers: int | None


@dataclass(frozen=True)
class WatchConfig:
    base_url: str
    timeout_seconds: float
    token_env: str
    max_cost_usd: float
    user_read_usd: float
    post_read_usd: float
    batch_size: int
    posts_per_batch: int
    maximum_post_age_minutes: int
    priority_age_minutes: int
    output_limit: int
    language: str
    lanes: tuple[Lane, ...]
    phrases: tuple[str, ...]
    excluded_phrases: tuple[str, ...]

    @property
    def handles(self) -> tuple[str, ...]:
        return tuple(handle for lane in self.lanes for handle in lane.handles)

    @property
    def projected_cost_usd(self) -> float:
        batches = (len(self.handles) + self.batch_size - 1) // self.batch_size
        return round(
            len(self.handles) * self.user_read_usd
            + batches * self.posts_per_batch * self.post_read_usd, 4
        )


def load_watch_config(path: Path) -> WatchConfig:
    try:
        with path.open("rb") as source:
            raw = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise WatchError(f"Cannot load {path}: {error}") from error
    if raw.get("schema_version") != 1:
        raise WatchError("schema_version must be 1")
    x_api, budget, scan, relevance, lanes_raw = (
        _table(raw, key) for key in ("x_api", "budget", "scan", "relevance", "lanes")
    )
    base_url = _str(x_api, "base_url").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or parsed.hostname not in {"api.x.com", "api.twitter.com"} or parsed.path:
        raise WatchError("x_api.base_url must be the official HTTPS X API origin")
    lanes: list[Lane] = []
    seen: set[str] = set()
    for name, value in lanes_raw.items():
        if not isinstance(value, Mapping):
            raise WatchError(f"lanes.{name} must be a table")
        handles = _strings(value, "handles")
        for handle in handles:
            if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
                raise WatchError(f"Invalid X handle: {handle}")
            if handle.casefold() in seen:
                raise WatchError(f"Duplicate handle: {handle}")
            seen.add(handle.casefold())
        minimum = _int(value, "minimum_followers", minimum=1)
        maximum = value.get("maximum_followers")
        if maximum is not None and (type(maximum) is not int or maximum < minimum):
            raise WatchError(f"lanes.{name}.maximum_followers must be >= minimum")
        lanes.append(Lane(name, handles, minimum, maximum))
    if not lanes or not seen or len(seen) > 100:
        raise WatchError("Configure 1–100 unique handles across lanes")
    config = WatchConfig(
        base_url=base_url,
        timeout_seconds=_float(x_api, "timeout_seconds"),
        token_env=_str(x_api, "token_env"),
        max_cost_usd=_float(budget, "max_estimated_cost_usd"),
        user_read_usd=_float(budget, "user_read_usd"),
        post_read_usd=_float(budget, "post_read_usd"),
        batch_size=_int(scan, "batch_size", minimum=1),
        posts_per_batch=_int(scan, "posts_per_batch", minimum=10),
        maximum_post_age_minutes=_int(scan, "maximum_post_age_minutes", minimum=1),
        priority_age_minutes=_int(scan, "priority_age_minutes", minimum=1),
        output_limit=_int(scan, "output_limit", minimum=1),
        language=_str(scan, "language"),
        lanes=tuple(lanes),
        phrases=_strings(relevance, "phrases"),
        excluded_phrases=_strings(relevance, "excluded_phrases"),
    )
    if config.batch_size > 10 or config.posts_per_batch > 100:
        raise WatchError("batch_size must be <= 10 and posts_per_batch <= 100")
    if config.priority_age_minutes > config.maximum_post_age_minutes:
        raise WatchError("priority_age_minutes must not exceed maximum_post_age_minutes")
    if config.language != "en":
        raise WatchError("The pilot currently supports English original posts only")
    if config.projected_cost_usd > config.max_cost_usd + 1e-9:
        raise WatchError(
            f"Projected maximum ${config.projected_cost_usd:.3f} exceeds "
            f"configured cap ${config.max_cost_usd:.2f}; no API calls made"
        )
    return config


def run_watch(
    config: WatchConfig,
    *,
    live: bool,
    token: str | None = None,
    transport: Transport | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if config.projected_cost_usd > config.max_cost_usd + 1e-9:
        raise WatchError(
            f"Projected maximum ${config.projected_cost_usd:.3f} exceeds "
            f"configured cap ${config.max_cost_usd:.2f}; no API calls made"
        )
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise WatchError("now must include a timezone")
    report: dict[str, Any] = {
        "schema_version": "feed-forge/high-reach-watch/v1",
        "generated_at": now.isoformat(),
        "status": "preview" if not live else "ok",
        "live": live,
        "cost": {
            "maximum_usd": config.max_cost_usd,
            "projected_maximum_usd": config.projected_cost_usd,
            "estimated_returned_usd": 0.0,
            "note": "Configured per-resource estimate; X Developer Console is authoritative.",
        },
        "lanes": [
            {"name": lane.name, "minimum_followers": lane.minimum_followers,
             "maximum_followers": lane.maximum_followers, "seed_handles": list(lane.handles)}
            for lane in config.lanes
        ],
        "accounts": [],
        "posts": [],
        "warnings": [],
    }
    if not live:
        report["warnings"].append("Preview only: account eligibility and posts not checked")
        return report
    if not token:
        raise WatchError(f"Live run requires {config.token_env}")
    client = XApiClient(base_url=config.base_url, token=token,
                        timeout_seconds=config.timeout_seconds, transport=transport)
    profiles = _get_array(client, "/2/users/by", {
        "usernames": ",".join(config.handles),
        "user.fields": "public_metrics,verified,verified_type,description",
    })
    report["cost"]["estimated_returned_usd"] += len(profiles) * config.user_read_usd
    by_handle = {_required_str(item, "username").casefold(): item for item in profiles}
    qualified: list[dict[str, Any]] = []
    for lane in config.lanes:
        for handle in lane.handles:
            profile = by_handle.get(handle.casefold())
            if profile is None:
                report["warnings"].append(f"@{handle}: no profile returned; not searched")
                continue
            user_id = _required_str(profile, "id")
            metrics = profile.get("public_metrics")
            if not isinstance(metrics, Mapping):
                raise WatchError(f"@{handle}: missing public_metrics")
            followers = metrics.get("followers_count")
            if type(followers) is not int or followers < 0:
                raise WatchError(f"@{handle}: invalid followers_count")
            verified = profile.get("verified")
            if type(verified) is not bool:
                raise WatchError(f"@{handle}: missing or invalid verified")
            eligible = verified and followers >= lane.minimum_followers and (
                lane.maximum_followers is None or followers <= lane.maximum_followers
            )
            account = {
                "id": user_id, "handle": _required_str(profile, "username"),
                "lane": lane.name, "followers_count": followers,
                "verified": verified, "verified_type": profile.get("verified_type"),
                "follow_status": "unknown",
                "eligible": eligible,
                "url": f"https://x.com/{_required_str(profile, 'username')}",
            }
            report["accounts"].append(account)
            if eligible:
                qualified.append(account)
            else:
                report["warnings"].append(f"@{handle}: below/above follower band or unverified")
    # Search only qualified accounts. Each request is bounded to 10–100 returned posts.
    seen: set[str] = set()
    for offset in range(0, len(qualified), config.batch_size):
        batch = qualified[offset:offset + config.batch_size]
        query = "(" + " OR ".join(f"from:{account['handle']}" for account in batch) + ") "
        query += f"lang:{config.language} -is:retweet -is:reply"
        if len(query) > 512:
            raise WatchError("Search query exceeds X's 512-character limit")
        posts = _get_array(client, "/2/tweets/search/recent", {
            "query": query,
            "max_results": config.posts_per_batch,
            "tweet.fields": "author_id,created_at,lang,public_metrics,conversation_id",
        })
        report["cost"]["estimated_returned_usd"] += len(posts) * config.post_read_usd
        eligible_by_id = {account["id"]: account for account in batch}
        for post in posts:
            parsed = _post_candidate(post, eligible_by_id, config, now)
            if parsed is not None and parsed["id"] not in seen:
                seen.add(parsed["id"])
                report["posts"].append(parsed)
    report["posts"].sort(key=lambda item: (-item["score"], item["id"]))
    report["posts"] = report["posts"][:config.output_limit]
    report["cost"]["estimated_returned_usd"] = round(
        report["cost"]["estimated_returned_usd"], 4
    )
    if not qualified:
        report["status"] = "no_eligible_accounts"
    elif not report["posts"]:
        report["status"] = "no_relevant_fresh_posts"
    return report


def _post_candidate(
    post: Mapping[str, Any], accounts: Mapping[str, Mapping[str, Any]],
    config: WatchConfig, now: datetime,
) -> dict[str, Any] | None:
    post_id = _required_str(post, "id")
    author_id = _required_str(post, "author_id")
    text = _required_str(post, "text")
    created_raw = _required_str(post, "created_at")
    try:
        created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise WatchError(f"Post {post_id}: invalid created_at") from error
    if created.tzinfo is None:
        raise WatchError(f"Post {post_id}: created_at has no timezone")
    language = _required_str(post, "lang")
    if author_id not in accounts or language != config.language:
        return None
    age_minutes = (now - created).total_seconds() / 60
    if age_minutes < 0 or age_minutes > config.maximum_post_age_minutes:
        return None
    if any(_contains(text, phrase) for phrase in config.excluded_phrases):
        return None
    matches = [phrase for phrase in config.phrases if _contains(text, phrase)]
    if not matches:
        return None
    metrics = post.get("public_metrics")
    if not isinstance(metrics, Mapping):
        raise WatchError(f"Post {post_id}: missing public_metrics")
    replies = metrics.get("reply_count")
    if type(replies) is not int or replies < 0:
        raise WatchError(f"Post {post_id}: invalid reply_count")
    freshness = (15 * (1 - age_minutes / config.maximum_post_age_minutes)
                 + (15 if age_minutes <= config.priority_age_minutes else 0))
    score = round(min(60, 20 * len(matches)) + freshness
                  + min(10, replies / 10), 2)
    account = accounts[author_id]
    return {
        "id": post_id, "author_id": author_id, "handle": account["handle"],
        "lane": account["lane"], "url": f"https://x.com/{account['handle']}/status/{post_id}",
        "created_at": created.isoformat(), "age_minutes": round(age_minutes, 1),
        "language": language, "text": text, "matched_phrases": matches,
        "reply_count": replies, "score": score,
        "score_components": {"relevance": min(60, 20 * len(matches)),
                             "freshness": round(freshness, 2),
                             "conversation": min(10, replies / 10)},
        "review_state": "needs_human_review",
        "fact_state": "unverified",
    }


def _get_array(client: XApiClient, path: str, params: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    response: ApiResponse = client.get(path, params)
    if response.status is None or not 200 <= response.status < 300:
        raise WatchError(f"{path}: HTTP {response.status or 'network error'}: "
                         f"{_safe_error(response)}")
    try:
        envelope = parse_x_response(response, data_kind="array")
    except ResponseStructureError as error:
        raise WatchError(f"{path}: invalid X response: {error}") from error
    if envelope.errors:
        raise WatchError(f"{path}: partial API errors: {public_api_errors(envelope.errors)}")
    return envelope.data  # type: ignore[return-value]


def _safe_error(response: ApiResponse) -> str:
    if response.network_error:
        return response.network_error[:200]
    if isinstance(response.body, Mapping):
        return str({key: response.body.get(key) for key in ("title", "detail", "type")
                    if key in response.body})[:300]
    return "no structured error detail"


def _contains(text: str, phrase: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.IGNORECASE) is not None


def _required_str(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise WatchError(f"Missing or invalid {key} in X response")
    return result


def _table(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise WatchError(f"{key} must be a TOML table")
    return result


def _str(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise WatchError(f"{key} must be a non-empty string")
    return result


def _strings(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    result = value.get(key)
    if not isinstance(result, list) or not result or any(not isinstance(item, str) or not item.strip() for item in result):
        raise WatchError(f"{key} must be a non-empty string array")
    return tuple(result)


def _int(value: Mapping[str, Any], key: str, *, minimum: int) -> int:
    result = value.get(key)
    if type(result) is not int or result < minimum:
        raise WatchError(f"{key} must be an integer >= {minimum}")
    return result


def _float(value: Mapping[str, Any], key: str) -> float:
    result = value.get(key)
    if type(result) not in (int, float) or not math.isfinite(result) or result <= 0:
        raise WatchError(f"{key} must be a positive number")
    return float(result)


def render_watch_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# High-reach watch", "", f"Status: **{report['status']}**", "",
             f"Projected maximum X read cost: ${report['cost']['projected_maximum_usd']:.3f} "
             f"(cap ${report['cost']['maximum_usd']:.2f}).", ""]
    if report["live"]:
        lines.append(f"Estimated returned-resource cost: ${report['cost']['estimated_returned_usd']:.3f}.")
        lines.extend(["", "## Eligible accounts", ""])
        for account in report["accounts"]:
            if account["eligible"]:
                lines.append(f"- [@{account['handle']}]({account['url']}) — {account['lane']}, "
                             f"{account['followers_count']:,} followers, verified")
        lines.extend(["", "## Fresh posts to review", ""])
        for post in report["posts"]:
            lines.append(f"- [@{post['handle']} post]({post['url']}) — {post['age_minutes']} min old; "
                         f"score {post['score']}; cues: {', '.join(post['matched_phrases'])}. "
                         "Review before replying; claims unverified.")
    else:
        lines.extend(["Preview only; no X API calls or charges were made.", "", "## Seed accounts", ""])
        for lane in report["lanes"]:
            lines.append(f"- {lane['name']}: " + ", ".join("@" + h for h in lane["seed_handles"]))
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"
