# FeedForge content guide

Grounding truth for post creation. Condensed from MG's voice guide and his
23 September 2026 review of 50 posts; updated with his 26 September decisions.
Apply new direct feedback here. Keep one guide and use Git history for old versions.

## What MG likes and why

Give the reader one reason to care and one thing worth taking away. An
announcement needs a take. A number needs a conclusion. A reply needs an
addition. A personal claim needs actual experience. Not every post must teach:
a blunt reaction, plain question, or relatable observation can be the best post.

| Form | Why it works |
| --- | --- |
| News plus the consequence or catch | Explains what changes for the reader, including caps, fees, exclusions, deadlines, or missing features. |
| Conclusion supported by one number | Makes a point with a decisive fact instead of a pile of statistics. |
| Price, time, or product comparison | Reveals a useful choice, trade-off, or surprising change using comparable evidence. |
| Emotion followed by concrete causes | Makes a specific frustration or delight relatable without inventing experience. |
| Familiar analogy or corrected framing | Explains the mechanism simply, with an honest practical limit. No forced contrarian opening. |
| Short reaction, hot take, or dry humor | Sounds specific and natural enough to say aloud. Serious news does not need a joke. |
| Question, hypothetical, nostalgia, or constrained choice | Invites an easy, real answer without a fabricated premise. |
| Reply or quote post | Adds an opinion, fact, correction, implication, comparison, or genuine question. |
| Real tool observation, demo, or milestone | Shows what actually happened and why it helps. A green workflow alone is not a milestone. |
| Compact practical reference | Gives people something useful to save or send without a crowded table or long guide. |

These are options, not quotas. MG especially liked concise RSS-derived posts,
specific builder frustrations, clear demonstrations, and verified milestones.

## Voice and editorial judgment

- Write conversationally, in first person where natural, to the affected reader.
  Use ordinary words and explain necessary jargon inside the sentence.
- Lead with the interesting change, conclusion, or reaction before backstory.
  Plain questions and quick thoughts do not need an engineered hook.
- Preserve MG's wording, point, and bluntness when editing. Return one strong
  version; offer alternatives only for distinct angles or when requested.
- Prefer concrete behavior, names, conditions, and amounts to vague excitement.
  Use Indian context when it helps. Appreciation posts start with appreciation;
  before actual use, frame the reaction as anticipation.
- Use a few natural emojis when they add tone. No em dashes, colon-stacked prose,
  corporate launch language, generic AI phrasing, or inflated enthusiasm.
- Replies are usually one or two casual lines: no hook, recap, generic praise,
  or self-promotion. Keep evidence outside the copy unless a link is useful.
- End where the point lands: verdict, limit, action, or answerable question.
  Do not append an engagement question to every post.
- Default to at most 280 X-weighted characters. Long posts and threads are out
  of the normal workflow. Compute counts with a tool; if only a plain character
  count is available, disclose that it does not establish platform fit.

Combine MG's supplied or documented view with an evidence-grounded proposed
take when it sharpens the post. Identify the take in the review note as
`mg_supplied`, `proposed_take`, or `combined`, outside the copy for X. Proposed
first-person judgments are drafts for approval, not claims about prior beliefs.
Never invent use, purchases, trips, meals, holdings, work, results, or personal
experience. Surface factual corrections or disagreements rather than pretending
agreement. Ask one precise question only when a personal detail is essential.

Favor the missing implication over another summary. Rank by reader value,
distinctiveness, timeliness, evidence, voice fit, and potential for useful
conversation, saves, shares, and relevant profile visits. These are editorial
hypotheses, not traffic guarantees. Deduplicate angles as well as URLs. Reject
unsupported claims, disguised promotion, orphan statistics, repetitive transfer
tables, giant video lists, generic visual comparisons, and medical experiments.

## On-demand pipeline run

"Run FeedForge" means audit the latest Topic Radar output and return the best
10 short original-post drafts, fewer if evidence or quality falls short. The
feed supplies the topics. Research its leads; do not add separate topic sweeps,
idea quotas, saved-backlog work, or an editorial schedule.

1. **Identify the input.** Inspect the live GitHub repository from the remote
   (pilot: `madhugogineni/feed-forge`) and newest successful default-branch Topic
   Radar run. Disclose newer failed/running jobs. Pin one repository revision
   for all file reads. Use available GitHub tools, API, or git; no specific
   connector is required. A local checkout alone does not prove freshness.
2. **Load everything.** Fetch `artifacts/topic-radar/latest/manifest.json` and
   every listed topic, source-health, occurrence, and URL shard at that revision.
   Require schema `feed-forge/editorial-input/v1`; match `workflow_run_id` to
   the identified run and `commit_sha` to its source `head_sha`, not the later
   snapshot-publishing commit. Check paths, IDs, counts, mappings, and available
   checksums. Locally use `python3 scripts/validate_editorial_snapshot.py
   <snapshot-directory>`; it validates integrity, not live provenance/freshness.
3. **Check freshness and fallbacks.** Report actual age against the workflow's
   configured slots, allowing the overnight gap and scheduling delays. The
   article lookback is not a freshness guarantee. If the shard input fails, try
   matching `latest.json`, then the matching Actions `topic-radar.json` artifact,
   then matching `latest.md`/job summary. Reconstruct all occurrences and source
   records from JSON fallbacks; never mix runs. Markdown or unavailable live
   provenance means partial/offline coverage, which must be labeled honestly.
4. **Inspect every URL.** Open each unique canonical article URL, even weak,
   duplicate-story, and context-only items. Read page content, not just headlines
   or search snippets. Preserve all occurrence IDs and original item/topic/feed
   provenance. A duplicate URL can be opened once; repeated occurrences stay in
   the audit. Review every source-health record, including zero-item, stale, and
   failed feeds. Retain their reported counts/errors separately from your own
   access observations. Scope covers the selected pipeline output, not unseen
   raw-feed entries or a recursive crawl of every linked page.
5. **Record every outcome.** For each URL retain ID, canonical URL, occurrence
   IDs, access status/time, publisher/title, short finding, outcome/reason,
   evidence references, and draft IDs. Preserve redirects and publication/HTTP
   details when observed. Choose `candidate`, `rejected`, `duplicate`,
   `inaccessible`, `context_only`, or `needs_verification`. Explain exclusions;
   duplicates name the retained story. Alternate evidence never erases an
   access failure. Context-only items do not become drafts.
6. **Reconcile before finishing.** Programmatically match manifest counts and
   expected IDs to fetched records, attempted URL inspections, all covered
   occurrences, and all reviewed source-health entries. Missing or invented IDs
   fail completeness. Blocked/rejected items count as accounted for, not verified.
   Report coverage, access success, and verification separately. If interrupted,
   save remaining IDs and label the run partial. Finding 10 posts is not a reason
   to stop inspecting inputs.
7. **Research and select.** Group the same story, verify the claims below, find
   the strongest consequence or take, and draft the best distinct opportunities.
   An unperformed build/test/trip can be a URL `candidate` with draft status
   `needs_user_input`, or a reasoned rejection. Keep it outside the ready queue
   and do not add it to the saved backlog during the run.

## Evidence and media

News, RSS, social posts, and forums are leads. Inspect the closest primary
source for every factual claim used in a ready draft: issuer terms, regulator
or embassy notices, official documentation, original reports/data. An official
announcement proves what the provider says, not independent performance.
Keep source links, dates/observation times, and claim mappings. Distinguish facts,
calculations, inference, and opinion; show conflicts and unverifiable claims.
Never mark a factual draft ready while an important claim remains unverified.

Run calculations in a tool and retain sourced inputs, formula, units, and result.
Comparisons need equivalent periods, geography, definitions, and configurations.
Market share must distinguish shipments, sales, and installed base. Model scores
need benchmark owner/methodology, exact variant, effort, task set, date, and cost
basis. Offer claims need eligibility, fees, caps, exclusions, and effective dates.

Find existing media only when it proves or clarifies the point. Link the asset
or source page, identify its creator/source and what it shows, and flag unclear
reuse permission. Text alone is fine. Do not generate, edit, enhance, storyboard,
or prescribe media production as part of a content run.

## Deliver the result

Lead with up to 10 ranked, ready original-post drafts. Each gets a stable ID,
final copy, computed character count/method, one-line reason it deserves
attention, take origin, claim/evidence links, status, and useful existing media.
Keep notes outside the copy. Statuses are `ready_for_human_review`,
`needs_verification`, `needs_user_input`, or `not_recommended`. Ready does not
mean approved/published. Show blocked items and essential questions separately;
never count them toward the 10 or fill the queue with weaker duplicates.

For requested replies/quote posts, include an observed target URL, author,
timestamp/context, and useful addition; leave unknown metrics unknown. Apply
the 70/30 reply strategy only to a requested combined action plan, never as a
quota for the default 10-post run. Do not start paid scans without authorization.

Save under ignored `artifacts/editorial/<UTC-run-timestamp>/`: `report.md`
(drafts first, coverage/freshness summary, source health, full audit and working),
`report.json` (schema `feed-forge/editorial-run/v1`, input provenance, expected/
processed counts and IDs, completion state, sources, URLs, occurrences, evidence,
and drafts), and `source-audit.csv` (one row per occurrence with provenance,
access, outcome/reason, evidence, and draft IDs). Return file links. This is the
agent's output contract; the current CLI validates inputs, not these reports.

## Optional interests for off-feed requests

Use only when MG asks for inspiration beyond the feed: AI/tools/coding agents,
Indian builders and IT careers; gadgets/Apple/telecom/music apps; Indian cards,
payments/deals/fine print; consumer brands/quick commerce/ergonomics; fitness,
food and walking; travel/visas/forex; personal finance and investing (no buy/sell
calls); Hyderabad life/weather/commutes/events; entertainment/Marvel/TV,
nostalgia, and everyday questions. Interests prove no personal experience or
current holding. A supplied thought or single-link request uses this guide's
style/evidence rules without triggering a full pipeline audit.
