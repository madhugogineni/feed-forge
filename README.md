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
the public-feed topic radar is executable. Reply and original-post
recommendation stages have not been implemented yet. A separate high-reach
watch can preview candidate accounts or make a manual, cost-capped live scan
for recent posts to review.

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

Successful X responses are validated against the documented API v2 envelope
before their data is used. Single-user lookups require a `data` object;
searches, timelines, following lists, and batch user lookups require a `data`
array or a documented empty-result form. Optional `errors`, `includes`, and
`meta` members are type-checked, partial errors are retained in the report, and
malformed successful responses stop the run instead of being mistaken for an
empty result. HTTP and network failures remain visible failures rather than
fabricated data.

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
not pretend that their follow status is known. It also skips paid timeline reads
for any candidate whose relationship status is unknown, because that candidate
cannot become review-ready until the follow check is resolved.

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

## Collect the topic radar

The topic radar reads public RSS/Atom feeds, classifies recent headlines into
the known topics, and writes JSON and Markdown reports. It makes no X API
requests, needs no X credentials, and does not post to X. Run it locally with:

```bash
python3 scripts/collect_topics.py
```

Its versioned configuration is
[`config/topic_feeds.toml`](config/topic_feeds.toml): feed URLs, a seven-day
freshness window, topic names, match rules, editorial lanes, and report limits
are editable there. The topics include AI development, major technology
companies, Indian consumer brands (including Frido), software, music apps,
cards/payments, India and Hyderabad/Telangana developments, practical local
updates, consumer safety, travel, fitness, and personal finance. Crime and
India-related geopolitics are collected as `context_only` and are not
publication recommendations. Topic matching is applied to headlines, because
many feeds include unrelated-story links in their descriptions.

Frido's public blog at [myfrido.com/blogs](https://myfrido.com/blogs) did not
expose a working Atom URL in our check, so a Google News RSS search and Indian
startup/publication feeds monitor mentions of Frido. The report shows a
per-brand match count, including zero if no recent Frido headline exists.
Google News and publisher feeds are discovery leads; a human must verify a
claim against the closest primary source before a factual draft is ready.
The report keeps article links, timestamps, match reasons, and per-feed health.
An unavailable or malformed feed is shown as failed; old or empty feeds are
shown separately. Any source failure exits nonzero after writing the reports.
Indian Express feeds were excluded after returning HTTP 403 from a GitHub
Actions runner; the workflow does not try to bypass publisher access controls.
Card Insider likewise returned HTTP 415 on the hosted runner and was replaced
with a Google News RSS search for Indian credit-card coverage.

The **Topic radar** GitHub Actions workflow runs every three hours, anchored at
approximately 06:00 Asia/Kolkata, on changes to topic-radar code/configuration,
and can also be started manually. It places the known-topic
table and recent headlines in the job summary and uploads both reports as
run artifacts for 30 days. Its workflow is independent of the manual-only,
cost-bounded account-discovery workflow. GitHub's scheduled jobs may run a
little later than the configured time.

## Watch high-reach accounts and fresh posts

The high-reach watch is separate from individual account discovery. It seeds
English-language Indian news accounts and global tech/AI publications. A live
run first checks each account's current verification status and follower count,
then searches recent posts from qualifying accounts. The Indian news lane
requires 100,000+ followers; the global tech/AI lane is configured for
150,000–750,000 followers, including accounts near 200,000. Seed handles are
candidates, not claims of current eligibility. Follow status remains unknown
without user-context access.

Run a free preview first:

```bash
python3 scripts/watch_high_reach.py
```

To make paid read requests, set `X_BEARER_TOKEN` and explicitly use `--live`.
Use `--lane global_tech_ai` or `--lane india_news` to scan only one lane. With
current configuration, those worst-case estimates are US$0.14 and US$0.23,
respectively. The GitHub workflow defaults to the lower-cost global lane;
select `all` to scan both.
The **High-reach watch** GitHub Actions workflow is manual-only; its `live`
input defaults to false. With the current 12 handles, the configured
worst-case estimate is US$0.32 under a US$0.50 cap: 12 user resources and up
to 40 post resources. These are estimates based on the configured per-resource
rates in [X's pay-per-use pricing](https://docs.x.com/x-api/getting-started/pricing);
the X Developer Console is authoritative. Malformed or partial API
responses stop the run visibly. A failed run can still incur charges for
resources already returned, so there is no zero-cost guarantee for live mode.

The report includes qualifying account links, current follower counts,
verification flags, search-coverage/rejection counts, and a ranked list of
fresh English original posts with post URL, age, text, relevance cues,
engagement metrics, and score components. Curated technology publications can
produce lower-confidence candidates without a literal phrase match; those are
explicitly marked as requiring a topic-fit check. This is a review
queue, not verified news or a ready-to-publish reply. It never follows or
replies automatically. Political and tragic posts are excluded by initial
phrase filters, but the user must still review every suggestion for fit.
Searches use X's documented [recent-search `from:` and `lang:` operators](https://docs.x.com/x-api/posts/search/integrate/operators).
They are grouped to limit cost, so a high-volume account can crowd out
another account in the same group; that is a known MVP limitation.

Configuration is in
[`config/high_reach_watch.toml`](config/high_reach_watch.toml). The stage is
stateless and its JSON/Markdown artifacts are retained for 90 days.
