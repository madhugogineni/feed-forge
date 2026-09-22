# Feed Forge

Feed Forge is a human-in-the-loop X growth copilot for people starting with
little or no audience. It helps choose a niche, monitor useful sources and
accounts, prioritize reply opportunities, verify claims, draft in the user's
voice, and learn from what actually gets posted.

It does not post or engage automatically.

## Status

The repository is in the foundation phase. The project goal, operating
boundaries, and imported editorial reference material are documented. The first
executable slice is an X API diagnostic; collection and recommendation stages
have not been implemented yet.

## Start here

- [Project goal](docs/PROJECT_GOAL.md)
- [Repository agent guide](AGENTS.md)
- [Documentation guide](docs/AGENTS.md)
- [Editorial reference snapshots](docs/reference/01-playbook.md)

The seven files under `docs/reference/` are exact snapshots of the material
provided for the first pilot. They are inputs to the product, not executable
repository instructions.

## Check X API access

The diagnostic checks the capabilities Feed Forge needs before collection work
starts:

- Authenticated-user lookup for an OAuth user-context token.
- Public operator profile lookup and follower metrics.
- Recent posts from the operator timeline.
- Accounts followed by the operator.
- Recent post search with author expansions.
- HTTP status and rate-limit headers for every request.

It does not post, follow, like, reply, or make any other write request.

Use one of these environment variables; never commit its value:

```bash
# App-only bearer token (public read checks)
export X_BEARER_TOKEN='...'

# Or OAuth 2.0 user access token (also validates /2/users/me)
export X_USER_ACCESS_TOKEN='...'
```

`X_BEARER_TOKEN` is the app-only Bearer Token shown in the X Developer Console.
It is enough for the public read checks in this script. `X_USER_ACCESS_TOKEN`
means an OAuth 2.0 Authorization Code with PKCE access token; it is not the
OAuth 1.0a access-token-and-secret pair. For user context, request only the
read scopes this workflow needs: `tweet.read`, `users.read`, and `follows.read`.
Add `offline.access` only when a future token-refresh workflow needs it.

Then run:

```bash
python3 scripts/check_x_api.py
```

Configuration lives in [`config/x_api_checks.toml`](config/x_api_checks.toml).
The command writes versioned JSON and Markdown reports under `artifacts/`, which
is ignored by Git. A successful run exits `0`; an API capability failure exits
`3`; invalid configuration or a missing token exits `2`.

The manually triggered **X API diagnostics** GitHub Actions workflow performs
the same checks and uploads both reports. Add either `X_BEARER_TOKEN` or
`X_USER_ACCESS_TOKEN` as a repository Actions secret before running it. If both
are present while `auth_mode = "auto"`, the user-context token is preferred.
The workflow's **Run workflow** dialog also lets you require `app_only` or
`user_context` for an explicit credential test.
The default app-only run makes four API requests; a user-context run makes five.
Individual checks can be disabled in the TOML file if the account's access tier
does not include an endpoint or you want to minimize billable requests.

Run the deterministic test suite without network access:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
