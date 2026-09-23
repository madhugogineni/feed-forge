# Feed Forge project goal

## Goal

Grow `@madhugogineni97` from 130 followers on 22 September 2026 to 1,000
relevant followers by 22 November 2026 through a repeatable, reply-led workflow.
That requires 870 net new followers in 61 days, or an average pace of about 100
per week. This is an aggressive operating target, not a guaranteed outcome.

Feed Forge is a human-in-the-loop X growth copilot. It should discover the right
people and conversations, collect current information, and prepare useful
replies and posts. The user retains control of following, editing, publishing,
replying, liking, and messaging.

## Goal 1: discover accounts worth following

Start with 10 recommendations in each of three discovery pools, for 30 total:

| Pool | Initial follower range | Purpose |
|---|---:|---|
| Peers | Approximately 100–1,000 | Build reciprocal relationships with people at a similar stage |
| Growing creators | Approximately 1,000–10,000, centered near 5,000 | Find active niche creators who are still likely to notice thoughtful replies |
| Beasts | 100,000+ | Join high-reach conversations early and earn discovery |

The system must prioritize accounts the user does not already follow. Discovery
recommendations must be verified individual accounts; exclude organizations,
government accounts, publications, and brand accounts. Each
suggestion must include:

- Handle, display name, follower count, and follow status.
- Primary topic and why the account fits the user's interests.
- Recent activity and evidence that it receives genuine engagement.
- Which pool it belongs to and why it is worth following or monitoring.
- Discovery date and last-checked time so stale accounts can be retired.

Within each 10-account pool, target four accounts focused on AI, coding agents,
or Indian AI builders; two focused on consumer technology, gadgets, or telecom;
two focused on Indian credit cards, payments, or fintech; one focused on Indian
fitness; and one crossover account. Consumer technology, gadgets, and telecom
accounts need not be India-specific. Do not weaken relevance or verification
requirements to fill a quota.

Follower ranges are starting filters, not permanent labels. Refresh counts and
reclassify accounts when they cross a boundary. Exclude inactive, low-quality,
spammy, heavily political, or engagement-bait accounts.

## Goal 2: find posts worth replying to

Monitor both:

- Relevant accounts the user already follows.
- New accounts suggested by Feed Forge, whether or not the user has followed
  them yet.

Prioritize topics in this order:

1. AI with clear relevance to India, including models, tools, coding agents,
   jobs, launches, and practical use.
2. Consumer technology, gadgets, and telecom; these need not be India-specific.
3. Fitness creators and conversations in India.
4. The Indian credit-card, rewards, deals, and payments community.
5. Current events in India that fit the account and are nonpolitical.
6. Secondary interests from the reference documents, including travel,
   Hyderabad, personal finance, Indian IT, investing, telecom, and lifestyle.

Every reply opportunity must contain the post URL, author, account pool, follow
status, post age, topic, engagement context, a one-line explanation of why the
user can add value, and a concise suggested reply in the user's voice.

Freshness matters. Rank beast-account posts most aggressively in their first
45 minutes, peer and growing-creator posts in their first two hours, and known
relationship targets within six hours. These are ranking preferences rather
than reasons to invent weak replies when no strong opportunity exists.

A useful reply adds at least one of the following: a specific reaction, a
relevant fact, a correction, a practical India-specific angle, simple verified
maths, a genuine question, or personal experience explicitly supplied by the
user. Do not generate generic praise, restate the post, or fabricate experience.

## Goal 3: generate original post ideas from current information

Run the opportunity pipeline once daily at 06:00 Asia/Kolkata. Each run should
produce five new, non-duplicative original post ideas using RSS/Atom feeds,
official newsrooms, regulators, first-party product pages, and other permitted
sources.

Post ideas should favor AI, technology, Indian current events, fitness, and the
Indian credit-card community while still using the broader interests in the
reference documents. Posts may be very short. A quick reaction, observation,
question, or one-line take is as valid as a crafted explainer.

Across each run's recommendation queue:

- Approximately 70% should be reply opportunities.
- Approximately 30% should be original post ideas.

With five post ideas, a typical run therefore targets about twelve reply
opportunities. Quality and relevance remain hard gates; the system must report a
shortfall rather than fill the queue with generic content.

Each post idea must include the topic, format, why it is timely, a draft or
clear angle, character count when drafted, and evidence status. Factual drafts
must link to the closest available primary source. Secondary sources and social
posts are leads, not proof.

## Core hypothesis

At the beginning, thoughtful distribution is the main growth engine. Early,
specific replies in relevant conversations create profile discovery. A smaller
number of useful original posts then gives profile visitors a reason to follow.

The 70/30 recommendation mix intentionally favors replies. The system should
also favor repeated, genuine interaction with peer and growing accounts over
one-off comments on only the largest accounts.

## Daily run output

Each run should produce one compact, reviewable artifact containing:

1. **Right now:** the important developments across the priority topics.
2. **Reply opportunities:** approximately twelve ranked posts drawn from both
   followed and suggested accounts.
3. **Post ideas:** five new ideas with a mix of quick and crafted formats.
4. **Evidence:** primary sources, verification state, and calculation working
   where applicable.
5. **Account discoveries:** new handles or material updates to the three account
   pools.
6. **Needs input:** only questions that require the user's actual experience or
   a meaningful editorial choice.

The initial experiment does not persist follow, reply, post, or outcome state.
Every run is a fresh recommendation snapshot based on current configuration and
live data.

## Success measures

### Growth outcome

- Reach 1,000 relevant followers by 22 November 2026.
- Track the required pace of approximately 100 net new followers per week.
- Measure whether new followers interact again, not only the raw total.

### Discovery quality

- Maintain 10 active, not-already-followed candidates in each account pool
  initially, for 30 recommendations total.
- Track suggestion acceptance, subsequent follows, follow-backs, and repeat
  conversations.
- Track how often suggested accounts or posts are duplicates, stale, or outside
  the user's interests.

### Recommendation quality

- Maintain an approximate 70/30 reply-to-post recommendation mix.
- Track reply and post acceptance/edit rates as a measure of voice fit.
- Track opportunity freshness when presented to the user.
- Track reply impressions, substantive responses, profile visits, follows,
  bookmarks, and shares when those metrics are available.
- Maintain 100% provenance for factual drafts and zero invented personal
  experience.

### Operational quality

- Complete a run daily at 06:00 Asia/Kolkata or surface a visible failure.
- Deduplicate post ideas, profiles, source items, and reply targets within each
  run. Cross-run repetition is acceptable during the stateless experiment.
- Preserve a traceable path from source to opportunity and draft inside each
  generated artifact.
- During the experiment, evaluate time saved and recommendation usefulness
  manually rather than persisting those measurements.

## Non-goals and boundaries

- Guaranteed growth, engagement, or follower conversion.
- Automated posting, replying, following, liking, or direct messaging.
- Bulk, spammy, deceptive, or generic engagement.
- Political persuasion, outrage farming, or tragedy commentary.
- Circumventing platform access controls, rate limits, or safeguards.
- Unverified deal, financial, travel, visa, health, or product claims.
- Inventing personal experience, account activity, metrics, URLs, or timestamps.
- Affiliate monetization during the initial trust-building phase.

## Build sequence

All phases are configuration-first and script-first. The automation must not
depend on a user interface. Scripts should expose reusable pipeline operations
and stable machine-readable output so a future application can wrap the same
logic without a rewrite.

The initial execution target is GitHub Actions. Runs are stateless: repository
configuration and GitHub Secrets are inputs; versioned JSON, rendered Markdown,
and the GitHub job summary are outputs. There is no database, migration layer,
or dependency on a previous run's artifact.

### Phase 1: configuration and data model

- Normalize the pilot profile, priority topics, secondary interests, voice,
  sources, known accounts, and boundaries into editable configuration.
- Make targets, account bands, schedules, freshness windows, source lists,
  scoring weights, recommendation ratios, output counts, and lookback windows
  configurable rather than embedding the pilot's values in code.
- Define a validated, versioned configuration schema with documented defaults
  and per-operator overrides.
- Define in-memory and output records for accounts, current follow status,
  source items, social posts, evidence, opportunities, and drafts.
- Produce versioned JSON records as the canonical output; render Markdown from
  those records for human review.
- Search current posts first, shortlist their authors locally, and look up only
  the shortlisted profiles and finalist timelines. Use authenticated
  relationship fields when available to exclude already-followed candidates
  without downloading the entire following list on every run.
- Enforce a configurable projected X API read-cost ceiling of US$0.50 per run.
  Stop before a request that would exceed the ceiling and report partial
  results rather than overspending.

### Phase 2: discovery and collection

- Build RSS/Atom and first-party page collectors with freshness checks,
  normalization, canonical URLs, and deduplication.
- Add the permitted X data path for account discovery and recent-post lookup.
- Classify accounts into the three pools and score them for topic fit, activity,
  engagement quality, novelty, and relationship value.

### Phase 3: recommendation engine

- Rank fresh reply opportunities from followed and suggested accounts.
- Generate five post ideas per run and assemble the 70/30 review queue.
- Attach verification state, evidence, score explanations, and voice checks.
- Produce the first Markdown review artifact from a local CLI.
- Keep discovery, collection, ranking, drafting, and rendering available as
  separate commands as well as one end-to-end command.

### Phase 4: scheduling and learning

- Schedule the pipeline daily at 06:00 Asia/Kolkata with visible failure
  reporting.
- Add manual `workflow_dispatch` inputs for testing different configuration
  values without changing code.
- Use GitHub artifacts and job summaries for review while the workflow is being
  tuned.
- Defer persistent feedback, outcome tracking, and weekly learning until the
  recommendations are consistently useful.

### Phase 5: interface

- Add a lightweight review interface only after the collection, ranking, and
  feedback loops work reliably from scripts and the CLI. The interface must
  consume the existing configuration and versioned outputs rather than contain
  separate business logic.

## Required implementation decision

The account-discovery and reply-opportunity goals require a reliable view of
the user's current follows and recent X posts. Before implementing that part, we
must choose the permitted data path: official X API, user-controlled browser
access, an account-data export, or a combination. RSS and first-party news
collection can be built independently of this decision.
