"""Configuration and health checks for the X API integration."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlparse

from .x_api import (
    ApiResponse,
    ResponseStructureError,
    Transport,
    XApiClient,
    parse_x_response,
    public_api_errors,
    rate_limit_from_headers,
)


REPORT_SCHEMA_VERSION = "feed-forge/x-api-diagnostics/v2"
ALLOWED_API_HOSTS = {"api.x.com", "api.twitter.com"}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")
AUTH_MODES = {"auto", "app_only", "user_context"}


class ConfigurationError(ValueError):
    """Raised for invalid configuration or missing credentials."""


@dataclass(frozen=True)
class DiagnosticsConfig:
    base_url: str
    timeout_seconds: float
    auth_mode: str
    app_token_env: str
    user_token_env: str
    operator_username: str
    require_identity_match: bool
    enabled_checks: Mapping[str, bool]
    recent_posts_limit: int
    following_limit: int
    recent_search_limit: int
    search_query: str


@dataclass(frozen=True)
class Credential:
    mode: str
    environment_variable: str
    token: str


def load_config(path: Path) -> DiagnosticsConfig:
    try:
        with path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except FileNotFoundError as error:
        raise ConfigurationError(f"Configuration file not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"Invalid TOML in {path}: {error}") from error

    if raw.get("schema_version") != 1:
        raise ConfigurationError("schema_version must be 1")

    x_api = _mapping(raw, "x_api")
    checks = _mapping(raw, "checks")
    limits = _mapping(checks, "limits")
    search = _mapping(checks, "search")

    config = DiagnosticsConfig(
        base_url=_required_string(x_api, "base_url").rstrip("/"),
        timeout_seconds=_number(x_api, "timeout_seconds"),
        auth_mode=_required_string(x_api, "auth_mode"),
        app_token_env=_required_string(x_api, "app_token_env"),
        user_token_env=_required_string(x_api, "user_token_env"),
        operator_username=_required_string(x_api, "operator_username").lstrip("@"),
        require_identity_match=_boolean(x_api, "require_identity_match"),
        enabled_checks={
            name: _boolean(checks, name)
            for name in (
                "authenticated_user",
                "operator_lookup",
                "recent_posts",
                "following",
                "recent_search",
            )
        },
        recent_posts_limit=_integer(limits, "recent_posts"),
        following_limit=_integer(limits, "following"),
        recent_search_limit=_integer(limits, "recent_search"),
        search_query=_required_string(search, "query"),
    )
    _validate_config(config)
    return config


def resolve_credential(
    config: DiagnosticsConfig,
    environment: Mapping[str, str] | None = None,
) -> Credential:
    environment = environment if environment is not None else os.environ
    app_token = environment.get(config.app_token_env, "").strip()
    user_token = environment.get(config.user_token_env, "").strip()

    if config.auth_mode == "app_only":
        return _credential_or_error("app_only", config.app_token_env, app_token)
    if config.auth_mode == "user_context":
        return _credential_or_error("user_context", config.user_token_env, user_token)
    if user_token:
        return Credential("user_context", config.user_token_env, user_token)
    if app_token:
        return Credential("app_only", config.app_token_env, app_token)
    raise ConfigurationError(
        "No X API token found. Set either "
        f"{config.user_token_env} (OAuth user token) or "
        f"{config.app_token_env} (app-only bearer token)."
    )


def run_diagnostics(
    config: DiagnosticsConfig,
    credential: Credential,
    *,
    transport: Transport | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    client = XApiClient(
        base_url=config.base_url,
        token=credential.token,
        timeout_seconds=config.timeout_seconds,
        transport=transport,
    )
    checks: list[dict[str, Any]] = []
    operator_id: str | None = None

    if config.enabled_checks["authenticated_user"]:
        if credential.mode == "user_context":
            response = client.get(
                "/2/users/me",
                {"user.fields": "id,name,username,public_metrics"},
            )
            identity = _user_observation(response)
            result = _result(
                name="authenticated_user",
                endpoint="GET /2/users/me",
                response=response,
                observation=identity,
                data_kind="object",
            )
            authenticated_username = identity.get("username")
            if result["status"] == "passed" and not _has_user_identity(identity):
                _mark_unexpected_response(
                    result, "Expected string data.id and data.username fields."
                )
            if (
                result["status"] == "passed"
                and config.require_identity_match
                and isinstance(authenticated_username, str)
                and authenticated_username.casefold()
                != config.operator_username.casefold()
            ):
                result["status"] = "failed"
                result["summary"] = (
                    f"Authenticated as @{authenticated_username}, expected "
                    f"@{config.operator_username}."
                )
                result["error"] = {
                    "category": "identity_mismatch",
                    "detail": "The user access token belongs to a different account.",
                }
            checks.append(result)
        else:
            checks.append(
                _skipped(
                    "authenticated_user",
                    "GET /2/users/me",
                    "App-only bearer tokens have no authenticated user. Set the "
                    f"{config.user_token_env} secret to test user context.",
                )
            )

    if config.enabled_checks["operator_lookup"]:
        response = client.get(
            f"/2/users/by/username/{config.operator_username}",
            {
                "user.fields": (
                    "id,name,username,created_at,description,location,"
                    "protected,public_metrics,verified"
                )
            },
        )
        observation = _user_observation(response)
        result = _result(
            name="operator_lookup",
            endpoint="GET /2/users/by/username/:username",
            response=response,
            observation=observation,
            data_kind="object",
        )
        if result["status"] == "passed":
            observed_id = observation.get("id")
            if _has_user_identity(observation):
                assert isinstance(observed_id, str)
                operator_id = observed_id
            else:
                _mark_unexpected_response(
                    result, "Expected string data.id and data.username fields."
                )
        checks.append(result)

    dependent_checks = (
        (
            "recent_posts",
            "GET /2/users/:id/tweets",
            {
                "max_results": config.recent_posts_limit,
                "post.fields": "id,author_id,created_at,lang,public_metrics",
            },
        ),
        (
            "following",
            "GET /2/users/:id/following",
            {
                "max_results": config.following_limit,
                "user.fields": "id,name,username,location,public_metrics",
            },
        ),
    )
    for name, endpoint, params in dependent_checks:
        if not config.enabled_checks[name]:
            continue
        if operator_id is None:
            checks.append(
                _skipped(
                    name,
                    endpoint,
                    "Operator lookup did not yield a user ID, so this dependent "
                    "check could not run.",
                    dependency_failed=True,
                )
            )
            continue
        path = (
            f"/2/users/{operator_id}/tweets"
            if name == "recent_posts"
            else f"/2/users/{operator_id}/following"
        )
        response = client.get(path, params)
        checks.append(
            _result(
                name=name,
                endpoint=endpoint,
                response=response,
                observation=_collection_observation(response),
                data_kind="array",
            )
        )

    if config.enabled_checks["recent_search"]:
        response = client.get(
            "/2/tweets/search/recent",
            {
                "query": config.search_query,
                "max_results": config.recent_search_limit,
                "post.fields": "id,author_id,created_at,lang,public_metrics",
                "expansions": "author_id",
                "user.fields": "id,name,username,location,public_metrics",
            },
        )
        checks.append(
            _result(
                name="recent_search",
                endpoint="GET /2/tweets/search/recent",
                response=response,
                observation=_collection_observation(response),
                data_kind="array",
            )
        )

    failed = any(
        check["status"] == "failed"
        or (check["status"] == "skipped" and check.get("dependency_failed"))
        for check in checks
    )
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "overall_status": "failed" if failed else "passed",
        "api_base_url": config.base_url,
        "authentication": {
            "mode": credential.mode,
            "token_environment_variable": credential.environment_variable,
            "token_present": True,
        },
        "operator_username": config.operator_username,
        "summary": {
            "passed": sum(check["status"] == "passed" for check in checks),
            "failed": sum(check["status"] == "failed" for check in checks),
            "skipped": sum(check["status"] == "skipped" for check in checks),
        },
        "checks": checks,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    authentication = report["authentication"]
    summary = report["summary"]
    status_mark = "✅" if report["overall_status"] == "passed" else "❌"
    lines = [
        "# X API diagnostics",
        "",
        f"{status_mark} **Overall status:** {report['overall_status']}",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Operator: `@{report['operator_username']}`",
        f"- Authentication mode: `{authentication['mode']}`",
        f"- Token source: `{authentication['token_environment_variable']}`",
        (
            f"- Results: {summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['skipped']} skipped"
        ),
        "",
        "| Check | Status | HTTP | Rate remaining | Summary |",
        "|---|---:|---:|---:|---|",
    ]
    for check in report["checks"]:
        rate_limit = check.get("rate_limit", {})
        lines.append(
            "| {name} | {status} | {http} | {remaining} | {summary} |".format(
                name=_markdown_escape(check["name"]),
                status=check["status"],
                http=check.get("http_status") or "—",
                remaining=(
                    rate_limit.get("remaining")
                    if rate_limit.get("remaining") is not None
                    else "—"
                ),
                summary=_markdown_escape(check["summary"]),
            )
        )
    lines.extend(
        [
            "",
            "The report intentionally contains no token value, prefix, or fingerprint.",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_config(config: DiagnosticsConfig) -> None:
    parsed_url = urlparse(config.base_url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in ALLOWED_API_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_API_HOSTS))
        raise ConfigurationError(
            f"x_api.base_url must be HTTPS on an official X API host ({allowed})"
        )
    if (
        parsed_url.path not in {"", "/"}
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.username
        or parsed_url.password
    ):
        raise ConfigurationError(
            "x_api.base_url must not contain a path, credentials, query, or fragment"
        )
    if config.timeout_seconds <= 0 or config.timeout_seconds > 120:
        raise ConfigurationError("x_api.timeout_seconds must be between 0 and 120")
    if config.auth_mode not in AUTH_MODES:
        raise ConfigurationError(
            f"x_api.auth_mode must be one of: {', '.join(sorted(AUTH_MODES))}"
        )
    if not USERNAME_PATTERN.fullmatch(config.operator_username):
        raise ConfigurationError("x_api.operator_username is not a valid X username")
    if (
        not config.app_token_env.isidentifier()
        or not config.user_token_env.isidentifier()
    ):
        raise ConfigurationError("Token environment variable names must be identifiers")
    if not 5 <= config.recent_posts_limit <= 100:
        raise ConfigurationError("checks.limits.recent_posts must be between 5 and 100")
    if not 1 <= config.following_limit <= 1000:
        raise ConfigurationError("checks.limits.following must be between 1 and 1000")
    if not 10 <= config.recent_search_limit <= 100:
        raise ConfigurationError(
            "checks.limits.recent_search must be between 10 and 100"
        )
    if not 1 <= len(config.search_query) <= 4096:
        raise ConfigurationError(
            "checks.search.query must be between 1 and 4096 characters"
        )


def _credential_or_error(
    mode: str, environment_variable: str, token: str
) -> Credential:
    if not token:
        raise ConfigurationError(
            f"auth_mode is {mode}, but {environment_variable} is not set."
        )
    return Credential(mode, environment_variable, token)


def _result(
    *,
    name: str,
    endpoint: str,
    response: ApiResponse,
    observation: Mapping[str, Any],
    data_kind: Literal["object", "array"],
) -> dict[str, Any]:
    http_succeeded = response.status is not None and 200 <= response.status < 300
    structure_error: str | None = None
    api_errors: list[dict[str, Any]] = []
    if http_succeeded:
        try:
            envelope = parse_x_response(response, data_kind=data_kind)
            api_errors = public_api_errors(envelope.errors)
        except ResponseStructureError as error:
            structure_error = str(error)
    passed = http_succeeded and structure_error is None and not api_errors
    result: dict[str, Any] = {
        "name": name,
        "endpoint": endpoint,
        "status": "passed" if passed else "failed",
        "http_status": response.status,
        "duration_ms": response.duration_ms,
        "summary": (
            _success_summary(name, observation)
            if passed
            else _failure_summary(response)
        ),
        "rate_limit": rate_limit_from_headers(response.headers),
        "observation": dict(observation) if passed else {},
        "api_errors": api_errors,
    }
    if structure_error is not None:
        result["summary"] = "HTTP success with an invalid X response structure."
        result["error"] = {
            "category": "unexpected_response",
            "detail": structure_error,
        }
    elif api_errors:
        result["summary"] = (
            f"HTTP success with {len(api_errors)} API error(s) in the response."
        )
        result["error"] = {
            "category": "partial_response",
            "detail": "X returned one or more documented errors with the response.",
        }
    elif not passed:
        result["error"] = _error_details(response)
    return result


def _skipped(
    name: str,
    endpoint: str,
    reason: str,
    *,
    dependency_failed: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "endpoint": endpoint,
        "status": "skipped",
        "http_status": None,
        "duration_ms": 0,
        "summary": reason,
        "dependency_failed": dependency_failed,
        "rate_limit": {"limit": None, "remaining": None, "reset_epoch": None},
        "observation": {},
    }


def _success_summary(name: str, observation: Mapping[str, Any]) -> str:
    if name in {"authenticated_user", "operator_lookup"}:
        username = observation.get("username", "unknown")
        return f"Accessible; returned @{username}."
    count = observation.get("result_count", 0)
    return f"Accessible; returned {count} item(s)."


def _failure_summary(response: ApiResponse) -> str:
    details = _error_details(response)
    category = details["category"].replace("_", " ")
    if response.status is None:
        return f"Request failed before an HTTP response ({category})."
    return f"HTTP {response.status}: {category}."


def _error_details(response: ApiResponse) -> dict[str, Any]:
    if response.network_error:
        return {"category": "network", "detail": response.network_error}
    categories = {
        400: "invalid_request",
        401: "authentication",
        402: "billing_or_credits",
        403: "authorization_or_plan_access",
        404: "endpoint_or_resource_not_found",
        429: "rate_limited",
    }
    status = response.status
    category = categories.get(
        status, "x_api_server_error" if status and status >= 500 else "http_error"
    )
    error = _first_api_error(response.body)
    return {
        "category": category,
        "title": error.get("title"),
        "detail": error.get("detail") or error.get("message"),
        "type": error.get("type"),
    }


def _first_api_error(body: Any) -> Mapping[str, Any]:
    if not isinstance(body, Mapping):
        return {}
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], Mapping):
        return errors[0]
    return body


def _user_observation(response: ApiResponse) -> dict[str, Any]:
    if not isinstance(response.body, Mapping):
        return {}
    data = response.body.get("data")
    if not isinstance(data, Mapping):
        return {}
    public_metrics = data.get("public_metrics")
    return {
        "id": data.get("id"),
        "username": data.get("username"),
        "name": data.get("name"),
        "protected": data.get("protected"),
        "public_metrics": (
            dict(public_metrics) if isinstance(public_metrics, Mapping) else {}
        ),
    }


def _has_user_identity(observation: Mapping[str, Any]) -> bool:
    return all(
        isinstance(observation.get(field), str) and bool(observation.get(field))
        for field in ("id", "username")
    )


def _mark_unexpected_response(result: dict[str, Any], detail: str) -> None:
    result["status"] = "failed"
    result["summary"] = "The endpoint succeeded but returned incomplete user data."
    result["observation"] = {}
    result["error"] = {"category": "unexpected_response", "detail": detail}


def _collection_observation(response: ApiResponse) -> dict[str, Any]:
    if not isinstance(response.body, Mapping):
        return {}
    meta = response.body.get("meta")
    data = response.body.get("data")
    result_count = meta.get("result_count") if isinstance(meta, Mapping) else None
    if not isinstance(result_count, int):
        result_count = len(data) if isinstance(data, list) else 0
    return {"result_count": result_count}


def _mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Missing or invalid [{key}] configuration section")
    return value


def _required_string(parent: Mapping[str, Any], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def _boolean(parent: Mapping[str, Any], key: str) -> bool:
    value = parent.get(key)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{key} must be true or false")
    return value


def _integer(parent: Mapping[str, Any], key: str) -> int:
    value = parent.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"{key} must be an integer")
    return value


def _number(parent: Mapping[str, Any], key: str) -> float:
    value = parent.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"{key} must be a number")
    return float(value)


def _markdown_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
