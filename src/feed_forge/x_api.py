"""Small, dependency-free X API v2 client used by pipeline stages."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


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


def _decode_body(raw_body: bytes) -> Any:
    if not raw_body:
        return None
    text = raw_body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"non_json_response": text[:500]}


def _normalize_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
