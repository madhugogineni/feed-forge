from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from feed_forge.x_api import ApiResponse, OAuth1Transport
from feed_forge.x_diagnostics import (
    ConfigurationError,
    Credential,
    load_config,
    render_markdown,
    resolve_credential,
    run_diagnostics,
)


FIXED_NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
SECRET = "not-for-output-super-secret-token"


class FakeTransport:
    def __init__(self, responses: list[ApiResponse]) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []
        self.authorization_headers: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> ApiResponse:
        self.urls.append(url)
        self.authorization_headers.append(headers["Authorization"])
        if not self.responses:
            raise AssertionError(f"No fake response configured for {url}")
        return self.responses.pop(0)


def response(status: int, body: object, remaining: int = 99) -> ApiResponse:
    return ApiResponse(
        status=status,
        body=body,
        headers={
            "x-rate-limit-limit": "100",
            "x-rate-limit-remaining": str(remaining),
            "x-rate-limit-reset": "1790082000",
        },
        duration_ms=7,
    )


class XDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(Path("config/x_api_checks.toml"))

    def test_auto_auth_prefers_user_token(self) -> None:
        credential = resolve_credential(
            self.config,
            {
                "X_BEARER_TOKEN": "app-token",
                "X_USER_ACCESS_TOKEN": "user-token",
            },
        )
        self.assertEqual("user_context", credential.mode)
        self.assertEqual("X_USER_ACCESS_TOKEN", credential.environment_variable)

    def test_missing_token_is_a_configuration_error(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "No X API token found"):
            resolve_credential(self.config, {})

    def test_app_only_runs_public_read_checks_and_skips_me(self) -> None:
        transport = FakeTransport(
            [
                response(
                    200,
                    {
                        "data": {
                            "id": "123",
                            "username": "madhugogineni97",
                            "name": "Madhu",
                        }
                    },
                    98,
                ),
                response(200, {"data": [], "meta": {"result_count": 0}}, 97),
                response(200, {"data": [{"id": "1"}], "meta": {"result_count": 1}}, 96),
                response(200, {"data": [], "meta": {"result_count": 0}}, 95),
            ]
        )
        report = run_diagnostics(
            self.config,
            Credential("app_only", "X_BEARER_TOKEN", SECRET),
            transport=transport,
            now=FIXED_NOW,
        )

        self.assertEqual("passed", report["overall_status"])
        self.assertEqual({"passed": 4, "failed": 0, "skipped": 1}, report["summary"])
        self.assertNotIn(SECRET, str(report))
        self.assertTrue(
            transport.urls[0].startswith("https://api.x.com/2/users/by/username/")
        )
        self.assertIn("post.fields=", transport.urls[1])
        self.assertNotIn("tweet.fields=", transport.urls[1])
        self.assertIn("query=AI", transport.urls[3])
        self.assertTrue(
            all(
                value == f"Bearer {SECRET}" for value in transport.authorization_headers
            )
        )

    def test_user_context_verifies_identity(self) -> None:
        transport = FakeTransport(
            [
                response(200, {"data": {"id": "123", "username": "madhugogineni97"}}),
                response(200, {"data": {"id": "123", "username": "madhugogineni97"}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
            ]
        )
        report = run_diagnostics(
            self.config,
            Credential("user_context", "X_USER_ACCESS_TOKEN", SECRET),
            transport=transport,
            now=FIXED_NOW,
        )
        self.assertEqual("passed", report["overall_status"])
        self.assertIn("/2/users/me", transport.urls[0])
        self.assertEqual(5, report["summary"]["passed"])

    def test_wrong_user_token_fails_identity_check(self) -> None:
        transport = FakeTransport(
            [
                response(200, {"data": {"id": "999", "username": "someone_else"}}),
                response(200, {"data": {"id": "123", "username": "madhugogineni97"}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
            ]
        )
        report = run_diagnostics(
            self.config,
            Credential("user_context", "X_USER_ACCESS_TOKEN", SECRET),
            transport=transport,
            now=FIXED_NOW,
        )
        identity = report["checks"][0]
        self.assertEqual("failed", report["overall_status"])
        self.assertEqual("identity_mismatch", identity["error"]["category"])

    def test_plan_access_failure_is_classified_and_dependents_skip(self) -> None:
        transport = FakeTransport(
            [
                response(
                    403,
                    {
                        "title": "Forbidden",
                        "detail": "Client Forbidden",
                        "type": "about:blank",
                    },
                ),
                response(200, {"data": [], "meta": {"result_count": 0}}),
            ]
        )
        report = run_diagnostics(
            self.config,
            Credential("app_only", "X_BEARER_TOKEN", SECRET),
            transport=transport,
            now=FIXED_NOW,
        )
        lookup = report["checks"][1]
        self.assertEqual("failed", report["overall_status"])
        self.assertEqual("authorization_or_plan_access", lookup["error"]["category"])
        self.assertTrue(report["checks"][2]["dependency_failed"])
        self.assertTrue(report["checks"][3]["dependency_failed"])

    def test_markdown_contains_results_but_not_secret(self) -> None:
        transport = FakeTransport(
            [
                response(200, {"data": {"id": "123", "username": "madhugogineni97"}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
                response(200, {"data": [], "meta": {"result_count": 0}}),
            ]
        )
        report = run_diagnostics(
            self.config,
            Credential("app_only", "X_BEARER_TOKEN", SECRET),
            transport=transport,
            now=FIXED_NOW,
        )
        markdown = render_markdown(report)
        self.assertIn("X API diagnostics", markdown)
        self.assertIn("operator_lookup", markdown)
        self.assertNotIn(SECRET, markdown)

    def test_rejects_non_x_api_host_to_protect_token(self) -> None:
        source = Path("config/x_api_checks.toml").read_text(encoding="utf-8")
        source = source.replace("https://api.x.com", "https://example.com")
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "official X API host"):
                load_config(config_path)

    def test_oauth1_signer_matches_rfc_5849_example(self) -> None:
        signer = OAuth1Transport(
            consumer_key="dpf43f3p2l4k3l03",
            consumer_secret="kd94hf93k423kf44",
            access_token="nnch734d00sl2jdk",
            access_token_secret="pfkkdhi9sl3r4s00",
            timestamp=lambda: 1191242096,
            nonce=lambda: "kllo9940pd9333jh",
        )
        header = signer.authorization_header(
            "GET",
            "http://photos.example.net/photos?file=vacation.jpg&size=original",
        )
        self.assertIn("oauth_signature=\"tR3%2BTy81lMeYAr%2FFid0kMTYa%2FWM%3D\"", header)


if __name__ == "__main__":
    unittest.main()
