"""Small, dependency-free X API v2 client used by pipeline stages."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Protocol


RATE_LIMIT_HEADERS = (
    "x-rate-limit-limit",
    "x-rate-limit-remaining",
    "x-rate-limit-reset",
)


@dataclass(frozen=True)
class ApiResponse:
    status: int | None
    body: Any
    headers: Mapping[str, str]
    duration_ms: int
    network_error: str | None = None


class ResponseStructureError(ValueError):
    """Raised when a successful X response violates its documented envelope."""


@dataclass(frozen=True)
class XResponseEnvelope:
    data: Mapping[str, Any] | tuple[Mapping[str, Any], ...]
    errors: tuple[Mapping[str, Any], ...]
    includes: Mapping[str, Any]
    meta: Mapping[str, Any]


class Transport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> ApiResponse: ...


class UrllibTransport:
    """HTTP transport that returns HTTP failures as data for diagnosis."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> ApiResponse:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw_body = response.read()
                return ApiResponse(
                    status=response.status,
                    body=_decode_body(raw_body),
                    headers=_normalize_headers(response.headers),
                    duration_ms=_elapsed_ms(started),
                )
        except urllib.error.HTTPError as error:
            raw_body = error.read()
            return ApiResponse(
                status=error.code,
                body=_decode_body(raw_body),
                headers=_normalize_headers(error.headers),
                duration_ms=_elapsed_ms(started),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            return ApiResponse(
                status=None,
                body=None,
                headers={},
                duration_ms=_elapsed_ms(started),
                network_error=f"{type(reason).__name__}: {reason}",
            )


class OAuth1Transport:
    """Sign GET requests with OAuth 1.0a HMAC-SHA1 user context."""

    def __init__(
        self,
        *,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_token_secret: str,
        transport: Transport | None = None,
        timestamp: Callable[[], int] | None = None,
        nonce: Callable[[], str] | None = None,
    ) -> None:
        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret
        self._access_token = access_token
        self._access_token_secret = access_token_secret
        self._transport = transport or UrllibTransport()
        self._timestamp = timestamp or (lambda: int(time.time()))
        self._nonce = nonce or (lambda: secrets.token_hex(16))

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> ApiResponse:
        signed_headers = dict(headers)
        signed_headers["Authorization"] = self.authorization_header("GET", url)
        return self._transport.get(
            url, headers=signed_headers, timeout_seconds=timeout_seconds
        )

    def authorization_header(self, method: str, url: str) -> str:
        oauth_parameters = {
            "oauth_consumer_key": self._consumer_key,
            "oauth_nonce": self._nonce(),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(self._timestamp()),
            "oauth_token": self._access_token,
            "oauth_version": "1.0",
        }
        parsed = urllib.parse.urlsplit(url)
        signature_parameters = list(
            urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        )
        signature_parameters.extend(oauth_parameters.items())
        normalized_parameters = "&".join(
            f"{_oauth_quote(key)}={_oauth_quote(value)}"
            for key, value in sorted(
                signature_parameters,
                key=lambda pair: (_oauth_quote(pair[0]), _oauth_quote(pair[1])),
            )
        )
        base_url = urllib.parse.urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", "")
        )
        signature_base = "&".join(
            (
                _oauth_quote(method.upper()),
                _oauth_quote(base_url),
                _oauth_quote(normalized_parameters),
            )
        )
        signing_key = (
            f"{_oauth_quote(self._consumer_secret)}&"
            f"{_oauth_quote(self._access_token_secret)}"
        )
        digest = hmac.new(
            signing_key.encode("utf-8"),
            signature_base.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        oauth_parameters["oauth_signature"] = base64.b64encode(digest).decode("ascii")
        return "OAuth " + ", ".join(
            f'{_oauth_quote(key)}="{_oauth_quote(value)}"'
            for key, value in sorted(oauth_parameters.items())
        )


class XApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport or UrllibTransport()

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> ApiResponse:
        encoded_params = urllib.parse.urlencode(params or {}, doseq=True)
        url = f"{self._base_url}{path}"
        if encoded_params:
            url = f"{url}?{encoded_params}"
        return self._transport.get(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": "feed-forge-x-diagnostics/0.1",
            },
            timeout_seconds=self._timeout_seconds,
        )


def rate_limit_from_headers(headers: Mapping[str, str]) -> dict[str, int | None]:
    values: dict[str, int | None] = {}
    keys = {
        "x-rate-limit-limit": "limit",
        "x-rate-limit-remaining": "remaining",
        "x-rate-limit-reset": "reset_epoch",
    }
    for header, output_key in keys.items():
        raw_value = headers.get(header)
        try:
            values[output_key] = int(raw_value) if raw_value is not None else None
        except ValueError:
            values[output_key] = None
    return values


def parse_x_response(
    response: ApiResponse,
    *,
    data_kind: Literal["object", "array"],
) -> XResponseEnvelope:
    """Validate and normalize a successful X API v2 response envelope.

    X documents primary-resource lookup responses as ``data: object`` and
    collection responses as ``data: object[]``. Both forms may also contain an
    ``errors`` array, an ``includes`` object, and a ``meta`` object. Collection
    endpoints can omit or null ``data`` when no resources were returned.
    """

    if response.status is None or not 200 <= response.status < 300:
        raise ResponseStructureError("cannot parse a non-successful response")
    if not isinstance(response.body, Mapping):
        raise ResponseStructureError("response body must be a JSON object")

    errors = _object_array(response.body.get("errors"), "errors")
    includes = _optional_object(response.body.get("includes"), "includes")
    meta = _optional_object(response.body.get("meta"), "meta")
    result_count = meta.get("result_count")
    if result_count is not None and (
        not isinstance(result_count, int)
        or isinstance(result_count, bool)
        or result_count < 0
    ):
        raise ResponseStructureError("meta.result_count must be a non-negative integer")

    raw_data = response.body.get("data")
    if data_kind == "object":
        if not isinstance(raw_data, Mapping):
            raise ResponseStructureError("data must be a JSON object")
        data: Mapping[str, Any] | tuple[Mapping[str, Any], ...] = raw_data
    else:
        if raw_data is None:
            if result_count not in {None, 0}:
                raise ResponseStructureError(
                    "data is missing but meta.result_count is not zero"
                )
            if result_count is None and not errors:
                raise ResponseStructureError(
                    "collection response must contain data, errors, or meta.result_count"
                )
            items: tuple[Mapping[str, Any], ...] = ()
        elif isinstance(raw_data, list):
            if any(not isinstance(item, Mapping) for item in raw_data):
                raise ResponseStructureError("every data item must be a JSON object")
            items = tuple(raw_data)
        else:
            raise ResponseStructureError("data must be a JSON array")
        if result_count is not None and result_count != len(items):
            raise ResponseStructureError(
                "meta.result_count must match the number of returned data items"
            )
        data = items

    return XResponseEnvelope(
        data=data,
        errors=errors,
        includes=includes,
        meta=meta,
    )


def public_api_errors(
    errors: tuple[Mapping[str, Any], ...],
) -> list[dict[str, Any]]:
    """Retain documented error provenance without copying arbitrary payloads."""

    allowed = (
        "status",
        "title",
        "detail",
        "type",
        "resource_type",
        "resource_id",
        "parameter",
        "value",
    )
    return [
        {key: error.get(key) for key in allowed if key in error}
        for error in errors
    ]


def _decode_body(raw_body: bytes) -> Any:
    if not raw_body:
        return None
    text = raw_body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"non_json_response": text[:500]}


def _object_array(value: Any, field: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ResponseStructureError(f"{field} must be a JSON array of objects")
    return tuple(value)


def _optional_object(value: Any, field: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ResponseStructureError(f"{field} must be a JSON object")
    return value


def _normalize_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _oauth_quote(value: Any) -> str:
    return urllib.parse.quote(str(value), safe="~-._")
