# Feed Forge

Feed Forge is a human-in-the-loop X growth copilot for people starting with
little or no audience. It helps choose a niche, monitor useful sources and
accounts, prioritize reply opportunities, verify claims, draft in the user's
voice, and learn from what actually gets posted.

It does not post or engage automatically.

## Status

The repository is in the foundation phase. The project goal, operating
boundaries, and imported editorial reference material are documented. X API
diagnostics and the first cost-bounded account-discovery stage are executable;
reply and original-post recommendation stages have not been implemented yet.

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

## Discover accounts

Account discovery searches current posts, ranks their authors locally, looks up
only a shortlist of profiles, and inspects recent posts for the best finalists.
It never follows an account or writes to X.

The pilot configuration is in
[`config/account_discovery.toml`](config/account_discovery.toml). It contains
the query families, expanded keyword taxonomy, 100–1,000 peer band, topic mix,
individual-verification filters, scoring weights, and API prices. The loader
rejects a configuration whose worst-case returned resources would exceed the
configured US$0.50 run limit. The current envelope is US$0.475.

Account discovery uses user context when available so the profile lookup can
request relationship status and reject accounts the operator already follows.
For the GitHub workflow, use the OAuth 1.0a credentials generated in
the X Developer Console:

```bash
export X_API_KEY='...'
export X_API_KEY_SECRET='...'
export X_ACCESS_TOKEN='...'
export X_ACCESS_TOKEN_SECRET='...'
python3 scripts/discover_accounts.py
```

Add those same four names as GitHub Actions secrets. An OAuth 2.0
`X_USER_ACCESS_TOKEN` is also accepted for local or manual runs, but X documents
that it normally expires after two hours unless the authorization used the
`offline.access` scope and the application implements refresh-token handling.
The workflow therefore prefers the long-lived OAuth 1.0a credentials when
both forms are present.

For initial testing, the existing app-only `X_BEARER_TOKEN` is also accepted.
Public discovery and relevance checks still run, but X cannot return a
user-relative following relationship to an app-only token. Those candidates are
therefore labeled `needs_follow_check` instead of `recommended`; the script does
not pretend that their follow status is known.

The **Account discovery** workflow is manual-only during the initial experiment.
Run it from GitHub Actions only when a live test is requested. It publishes the
Markdown report to the job summary and retains the JSON and Markdown artifacts
for 90 days. The planned 06:00 Asia/Kolkata schedule remains deferred until the
recommendations and cost envelope have been validated.

The current stage remains stateless: retained artifacts provide a review
history but are not inputs to later runs. Durable cross-run deduplication,
accept/reject feedback, and outcome measurement require a persistent history
store and are deliberately deferred until the live recommendations have been
evaluated.
