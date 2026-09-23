# Content package specification

Produce one package per proposed post or reply. Keep the visible output compact,
but retain enough provenance for review.

## Required fields

### Status

One of:

- `ready_for_human_review`
- `needs_verification`
- `needs_user_input`
- `not_recommended`

### Recommendation

- Type: original post, reply, quote-post, long post, or thread.
- Topic and intended audience.
- Why now.
- The one idea the item communicates.
- Why this is worth publishing instead of being merely true.

### Draft

- Final recommended wording.
- Character count.
- For a reply, the target post URL and author.
- For a quote-post, the post to quote.
- For a long post, an under-280 teaser and `[needs Premium]` label.
- Optional alternate only when a materially different angle is useful or the
  user asks for alternatives.

### Evidence

For each claim used in the draft:

- claim text;
- state: observed, calculated, opinion, or unverified;
- primary source or repository reference;
- source date and observation time;
- calculation inputs and formula when applicable.

Do not mark a draft ready when a factual claim in the posted text is unverified.

### Media decision

Choose one:

- `none`: state why text alone is stronger;
- `image`: attach the generated or supplied asset and include its purpose,
  dimensions, source note, exact in-image text, and alt text; or
- `video`: attach the generated clip when available, otherwise provide the
  production package below.

The video production package contains:

- target duration and aspect ratio;
- opening hook for the first two seconds;
- narration;
- shot-by-shot plan with timestamps;
- exact on-screen text;
- burned-in caption text or subtitle file content;
- thumbnail concept and title;
- source/rights notes; and
- a generation or editing prompt.

### Review checklist

- One clear idea.
- MG's take is visible.
- The hook precedes background.
- No invented experience or metrics.
- No em dash.
- No unsupported factual claim.
- Source provenance is retained.
- Character count is correct.
- Media adds value and is readable on mobile.
- Image alt text or video captions are present.
- No political persuasion or affiliate link.
- No automatic posting or engagement action is proposed.

## Queue-level output

When producing multiple recommendations, start with a compact table containing:

- rank;
- type;
- topic;
- freshness;
- evidence state;
- media choice; and
- status.

Then show the individual packages. Maintain approximately a 70/30 reply-to-post
mix when the request includes both. Quality is a hard gate, so explicitly report
when there are not enough strong candidates.

For the proactive daily editorial run, use the lane counts, fields, and
shortfall rules in `DAILY_EDITORIAL_RUN.md`. Its 15-item original-content bank
is separate from the reply queue. Develop only the top five into the full
package above; represent the other ten with compact idea records. Precede the
idea bank with the complete source-audit sheet, and retain the same records in
the JSON output and `source-audit.csv`.

## Execution-idea package

Use this package when the best content opportunity requires MG to build, test,
record, travel, supply a real experience, or create an asset before a truthful
post can exist.

- **Status:** ready to implement, needs research, needs MG input, parked, or
  rejected.
- **Idea:** the concrete thing to build, test, capture, or do.
- **Why it is useful:** value independent of social engagement.
- **Content payoff:** the post, demo, reply, guide, or media story it can support.
- **Smallest useful scope:** the minimum version that creates a real result.
- **Required inputs:** accounts, tools, data, user experience, or source material.
- **Evidence plan:** how the result and any factual claim will be verified.
- **Media plan:** what to record or generate, including aspect ratio and mobile
  readability when known.
- **Next decision for MG:** one specific choice or action, only when required.

Return execution ideas in a downloadable Markdown file. When repository write
access is available, also preserve durable ideas in
`docs/CONTENT_EXECUTION_BACKLOG.md` so they do not exist only in chat.
