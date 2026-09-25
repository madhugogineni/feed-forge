# Starter prompts

Use one chat per outcome. Replace bracketed text before sending.

## 1. Connection test

```text
Use the GitHub plugin to inspect madhugogineni/feed-forge. Read only. Tell me the
default branch, latest commit with its date, available GitHub Actions workflows,
and the most recent run you can access for each workflow. Cite every result.
Do not draft content yet. If you cannot access workflow artifacts or job
summaries, say exactly what is unavailable and tell me which Markdown or JSON
artifact to upload instead. Do not ask for or expose any secret.
```

## 2. Turn repository progress into a build update

```text
Use the GitHub plugin to inspect commits and pull requests in
madhugogineni/feed-forge from [START DATE] through [END DATE]. Identify the one
change that creates the clearest audience value. Verify it against the changed
files and tests, then create one X content package using the project
specification. Write for a general audience, not as a changelog. Do not claim a
feature is live unless the evidence shows that it ran successfully. Recommend
and generate an image only if it makes the post clearer.
```

## 3. Turn a Feed Forge run into post ideas

```text
Use the attached Feed Forge run artifact from [RUN DATE] as the candidate source.
Treat secondary articles and social posts as leads. Verify every factual claim
that would appear in a draft against the closest primary source. Produce up to
five original-post content packages, ranked by relevance and freshness. Report
a shortfall instead of filler. Use the project's voice and media rules.
```

## 4. Produce a reply-led review queue

```text
Use the attached run artifact and any permitted current GitHub source. Produce a
human-review queue with approximately twelve reply opportunities and five
original-post ideas. Apply the 70/30 strategy across the ranked queue, but keep
quality as a hard gate. For every reply include the target URL, author, age,
reason MG can add value, concise draft, and evidence state. Replies must sound
casual and must not use a hook or restate the original post.
```

## 5. Generate the image for an approved draft

```text
The approved post text is below. First decide whether a generated image, a real
screenshot/photo, a chart, or no image best supports it. Explain the decision in
one sentence. If a generated image is best, create one original, mobile-readable
asset at 1:1 unless 16:9 is clearly better. Keep in-image text minimal and exact.
Then provide concise objective alt text and a source note. Do not imitate an
artist or fabricate a product interface.

[APPROVED POST]
```

## 6. Build a short-video package

```text
Turn the approved post below into a short X video package. Aim for one idea and a
strong first two seconds. Provide duration, aspect ratio, narration, timestamped
shot list, exact on-screen text, captions, thumbnail, rights/source notes, and a
video-generation prompt. If video generation is available, create and inspect
the clip. If it is not available, do not pretend a file was produced.

[APPROVED POST]
```

## 7. Learn from results without overfitting

```text
Analyze the attached X analytics export for [DATE RANGE]. Compare formats using
relevant follows, substantive replies, profile visits, saves, shares, and repeat
interactions where available. Separate observation from inference. Recommend at
most three changes to voice, format, timing, or media. Do not treat one viral or
failed post as a general rule. Output proposed edits to the voice or traction
guide for my approval, but do not change project sources automatically.
```

## 8. Find something useful to build and showcase

```text
Review current AI-tool releases, the Feed Forge repository, and the content
execution backlog. Propose up to three small tools, skills, or workflows I could
genuinely use and then demonstrate on X. Rank them by usefulness independent of
social reach, implementation effort, demo clarity, and fit with my audience.
For the strongest idea, create an execution-idea Markdown file using the project
specification. Do not write a launch post or imply that I built it yet. Ask me
for only the one decision needed to begin.
```

## 9. React to a new AI model release

```text
Research [MODEL NAME AND VERSION] using the source library. Separate the
provider's claims from independent results. Trace every benchmark to its owner
and methodology, compare equivalent variants and reasoning settings, include
price or latency only when the units are comparable, and state what the numbers
do not prove. Then produce one original-post package and up to three timely
reply opportunities. Every draft must contain my take or a clear conclusion.
```

## 10. Generate human question posts

```text
Generate twelve question-post candidates that do not depend on today's news:
two broad curiosity questions, two constrained trade-offs, two hypotheticals,
two nostalgia prompts, two questions for the Indian cards or technology
community, and two light rage-bait-style questions. Keep them easy to answer
and natural enough to say aloud. Do not use a fabricated premise, politics,
tragedy, medical misinformation, or attacks on a private person. Rank the best
five and explain in one short line what kind of replies each should invite.
```

## 11. Test the proactive scheduled editorial run

Run this manually and review the output before enabling its schedule.

```text
Execute the scheduled editorial workflow in
docs/chatgpt-project/DAILY_EDITORIAL_RUN.md for today. Inspect the live
madhugogineni/feed-forge repository, confirm its default branch, latest commit,
and newest successful relevant Topic Radar run, then fetch
artifacts/topic-radar/latest.json directly through the GitHub connector.
Validate its workflow_run_id, commit_sha, and generated_at against that run and
record the result. Use the matching Actions artifact ZIP only as a visibly
labeled fallback when the direct snapshot is missing, stale, or mismatched. Do
not use an old uploaded copy as a substitute for current repository state.
Enumerate every URL in the selected pipeline output, visit every unique
canonical URL, and retain every occurrence in the required source-audit sheet.
Include failed, blocked, stale, rejected, and unused links with their status and
reason. Return the audit in Markdown, JSON, and a downloadable source-audit.csv.
Research all approved lanes proactively, including historical or then-versus-now
comparisons, financial facts, interesting numbers, questions, light
rage-bait-style prompts, and GitHub build stories. Verify factual premises with
primary sources and run calculations in code.

Return exactly 15 ranked original-content ideas using the configured lane mix.
Develop the top five into complete content packages and keep the remaining ten
compact. Keep reply opportunities in a separate section. Do not post, reply,
follow, like, message, or schedule social content. If a source is missing or
stale, show that failure rather than pretending it was read.
```
