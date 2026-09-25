# Feed Forge Content Studio setup

This pack configures a ChatGPT project that turns Feed Forge repository changes
and GitHub Actions outputs into human-reviewed X content packages. It is an
editorial layer above Feed Forge, not a replacement for the repository pipeline.

The project may research, extract evidence, draft posts, generate images, and
prepare video production material. It must not publish, reply, follow, like, or
send direct messages.

## Recommended project

Name the ChatGPT project **Feed Forge Content Studio**.

Use a regular ChatGPT project when you want the studio available across devices.
Connect the GitHub plugin so a project chat can retrieve current repository
content. A project does not automatically read GitHub on every request, so the
project instructions explicitly require a fresh GitHub check when a task depends
on current repository state.

The ChatGPT desktop app also supports a local project attached to the repository
folder. That is useful for direct access to the local checkout, but the shared
ChatGPT project plus GitHub plugin is the better default for this editorial
workflow.

## Create and configure it

1. In ChatGPT, open **Projects** and create **Feed Forge Content Studio**.
2. Open the project settings and paste the complete contents of
   `PROJECT_INSTRUCTIONS.md` into the project instructions field.
3. Add these repository files to the project's Sources section:
   - `docs/PROJECT_GOAL.md`
   - `docs/CONTENT_EXECUTION_BACKLOG.md`
   - `docs/SOURCE_LIBRARY.md`
   - `docs/reference/02-voice.md`
   - `docs/reference/03-topics.md`
   - `docs/reference/05-great-posts.md`
   - `docs/reference/07-long-posts.md`
   - `docs/chatgpt-project/CONTENT_PACKAGE_SPEC.md`
   - `docs/chatgpt-project/DAILY_EDITORIAL_RUN.md`
   - `docs/chatgpt-project/TRACTION_PLAYBOOK.md`
4. Install and connect the GitHub plugin in ChatGPT. Grant access only to the
   `madhugogineni/feed-forge` repository unless broader access is genuinely
   needed. If the account belongs to a GitHub organization, an organization
   owner may need to approve the connection.
   The project instructions require this connector on every run that uses Feed
   Forge state. An uploaded repository file is not a substitute for checking the
   current repository and workflow output.
5. Do not add GitHub tokens, X credentials, `.env` files, Actions secrets, or
   unredacted logs containing secret values to project sources.
6. Start a new project chat called **Connection test** and run the connection
   test prompt in `STARTER_PROMPTS.md`.
7. Run prompt 11 from `STARTER_PROMPTS.md` manually. Review the source access,
   15-idea mix, factual verification, voice, and top-five packages before
   enabling any recurring task.
8. After the acceptance run passes, create a recurring editorial automation for
   06:05, 09:05, 12:05, 15:05, 18:05, and 21:05 Asia/Kolkata using the exact
   prompt from prompt 11. Topic Radar runs at 06:00, 09:00, 12:00, 15:00,
   18:00, and 21:00 IST; its 00:00 and 03:00 slots are intentionally skipped.
   The editorial automation is time-triggered, so each run must validate the
   repository's latest Topic Radar snapshot against the newest successful
   relevant run instead of assuming the immediately preceding run finished on
   schedule.
9. Start a separate chat for each ad hoc outcome, such as **Weekly build story**,
   **Topic radar posts**, **Image concepts**, or **Video scripts**. This keeps
   the evidence and revisions for one deliverable together while retaining the
   shared project context.

Project sources are snapshots. When one of the uploaded editorial files changes
in GitHub, replace its project copy or ask the project to use the newer GitHub
version explicitly.

Most `docs/reference/` files are preserved historical snapshots.
`docs/reference/05-great-posts.md` is the exception: MG explicitly replaced it
on 23 September 2026, and it is the living authority for editorial formats and
preferences. Use `CONTENT_EXECUTION_BACKLOG.md` and `SOURCE_LIBRARY.md` as the
living authorities for executable ideas and recurring source requirements.

## What “GitHub logs” means in this workflow

Use the narrowest useful source:

1. Git commits and pull requests for what changed in the product.
2. The validated `artifacts/topic-radar/latest.json` repository snapshot for
   what the newest successful Topic Radar run found.
3. GitHub Actions artifacts and job summaries as the fallback when that
   snapshot is missing, stale, or mismatched.
4. Raw Actions logs only to diagnose a run, not as the main editorial input.

Raw logs are noisy and may expose operational details. A passing log also does
not prove that a social claim is true. The direct JSON snapshot and its source
provenance are the preferred editorial input.

If the direct snapshot cannot be validated, retrieve the matching Actions
artifact through the GitHub connector. If that surface cannot download the
artifact, download it from GitHub and upload the JSON or Markdown file to the
relevant project chat. Do not upload the whole log bundle unless a failure must
be diagnosed.

## Operating flow

```text
GitHub commits, PRs, and Actions outputs
                 |
                 v
       extract candidate stories
                 |
                 v
      verify claims and provenance
                 |
                 v
        draft text and choose media
                 |
                 v
     generate image or video package
                 |
                 v
          human edit and approval
                 |
                 v
             manual posting
```

## Initial acceptance test

The setup is ready when the project can:

- identify the latest repository commit and at least one recent workflow;
- explain the difference between a commit, job summary, artifact, and raw log;
- cite the exact GitHub source behind every claimed product change;
- produce one post package that follows `CONTENT_PACKAGE_SPEC.md`;
- produce 15 ranked original-content ideas across the configured lanes and
  develop the top five without turning the list into a posting quota;
- enumerate every link in the chosen Topic Radar output, visit every unique
  canonical URL, and retain all occurrences and failures in the Markdown/JSON
  report plus a downloadable `source-audit.csv`;
- research a historical or financial comparison without waiting for a separate
  user prompt and preserve comparable definitions, inputs, and calculations;
- mark unsupported claims as unverified instead of filling gaps;
- generate an image when one materially improves the post, including alt text;
- provide a video storyboard and captions when video is the better format;
- produce a downloadable execution-idea file when a real build, test, trip,
  recording, or personal input must happen before the post; and
- stop before publishing or taking any action on X.

## Phase boundary

Publishing and engagement remain manual, but research and ideation become
proactive after the acceptance run. The scheduled automation produces an
editorial report at each configured slot; it does not post or interact on X. A
later implementation phase can add a stable
`social-source.json` artifact to GitHub Actions so the scheduled task has a
compact, consistent handoff instead of interpreting general-purpose logs.
