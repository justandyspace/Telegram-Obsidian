# PRD v1: Telegram Bot + Mini App

## 1. Product Frame

The product should not "move from the bot into the Mini App."

The correct model is:

- `Telegram Bot` = fast input, notifications, short commands
- `Mini App` = viewing, search, triage, management

Main value loop:

1. The user quickly saves a link, text snippet, or file into the bot.
2. The system processes it reliably in the background.
3. The user later finds, reads, or summarizes it via bot preview or the Mini App.
4. Errors and destructive actions remain transparent and safe.

## 2. Goals (90 Days)

### Goal 1: Speed up `capture -> first value`

- KPI: median `time_to_first_value < 2 min`

### Goal 2: Improve retrieval success

- KPI: `query_success_rate > 60%`
- Definition: the user gets a result and opens a note or source

### Goal 3: Make the Mini App a real work surface

- KPI: `30%+` of active users open the Mini App at least once in 7 days
- Condition: an open counts only if at least one action happens inside the app

### Goal 4: Reduce fear around failures and deletion

- KPI: `failed_job_resolution_p50 < 2 min`
- KPI: keep `delete_regret_rate` under control

## 3. ICP

Focus for the first 90 days:

- `Solo founder / knowledge worker`
- `Research-heavy user`

Not in scope for v1 focus:

- gamification for hoarders
- large-scale content management
- social or share-first flows

## 4. Core JTBD

1. Save a thought, link, or file quickly with minimal friction.
2. Find the right note by meaning within 5-10 seconds.
3. Get a short grounded answer from personal notes.
4. Understand what failed in processing and fix it fast.
5. Delete safely and still have a recovery path.

## 5. Routing Rules

### Keep in Bot

- capture
- `/start`
- `/status`
- `/find` as a quick preview
- `/summary` as a short answer
- single retry
- small delete

### Move to Mini App

- advanced search
- note reading and detail view
- jobs triage
- bulk delete and restore
- settings
- long multi-step workflows

### Routing Principle

- `simple / short / single-step -> Bot`
- `multi-result / multi-step / destructive / batch -> Mini App`

## 6. Scope v1

### P0

#### 1. Bot v2

- compact `/start`
- quiet intake confirmation
- compact `/status`
- `/find` returns top results + CTA into the app
- `/summary` returns a short grounded answer + sources + CTA
- clear error and retry responses
- deep-link into a specific Mini App screen

#### 2. Mini App v1

- `Search`
- `Note Detail`
- `Jobs`
- `Delete / Restore`
- no KPI wall
- no overloaded dashboard

#### 3. Trust Layer

- safe delete / soft delete
- undo / restore
- quality guardrails for summary and search
- clear error taxonomy
- tenant-safe routing

### P1

- weekly review lite
- saved views lite
- quick templates in bot

### Explicitly Out of Scope for v1

- tinder review
- topic clusters
- note health score
- “did you know” insights
- shareable digest
- complex graph features

## 7. Bot UX

### `/start`

- short introduction
- CTA to save the first note
- CTA to open the app, but not as the main path before first value

### `/status`

Show essentials only:

- queue state
- failed jobs count
- recent success
- CTA `Open Jobs`

### `/find <query>`

- top 3 results
- short snippet
- primary CTA: `Open advanced search`

### `/summary <query>`

- short grounded answer
- mandatory sources
- honest refusal when context is insufficient
- heavy / long queries constrained by guards

### `/retry <id>`

- single-job recovery
- if the issue is complex, add a CTA into `Jobs`

### `/delete`

- small delete is allowed in the bot
- bulk delete belongs to the Mini App only

## 8. Mini App IA v1

### Bottom Navigation

- `Home`
- `Search`
- `Activity`

### `Home`

- recent notes
- continue where left off
- failed jobs badge
- quick actions
- no KPI overload

### `Search`

- query
- basic filters
- results
- open note

### `Note Detail`

- title / meta
- summary
- source / original
- related notes only if cheap and high quality

### `Activity`

- jobs
- retry history
- delete / restore history

### `Settings`

- not a separate bottom tab
- drawer or sheet

## 9. Analytics

### North Star

`Weekly Successful Knowledge Tasks`

Definition:

- a unique user completes `capture`
- then completes `successful retrieval` or `accepted summary`

### Key Metrics

- `time_to_first_value_seconds`
- `query_success_rate`
- `summary_accept_rate`
- `deep_link_success_rate`
- `retry_resolution_time`
- `delete_undo_rate`
- `failed_job_rate`

### Critical Events

- `capture_received`
- `miniapp_opened`
- `search_submitted`
- `search_result_clicked`
- `summary_requested`
- `summary_accepted`
- `job_failed_seen`
- `job_retry_clicked`
- `delete_requested`
- `delete_confirmed`
- `delete_undo_used`
- `original_url_opened`

## 10. Acceptance Criteria

### Bot

- commands do not turn into long message walls
- every long answer includes an app CTA
- `/find` and `/summary` do not break chat UX
- all errors are user-readable

### Mini App

- Search opens with prefilled context from the bot
- Note Detail opens via deep link without losing context
- Jobs shows actionable status instead of raw internals
- delete / restore is atomic

### Quality

- a summary without sources is never shown as a confident answer
- query latency stays within a reasonable budget
- tenant leakage = 0
- destructive actions are audit-logged

## 11. Roadmap

### Week 1

- deep-link infrastructure
- `/start` v2
- `/status` v2
- telemetry skeleton
- command cleanup

### Weeks 2-4

- Mini App: Search, Note Detail, Activity / Jobs basic
- `/find` hybrid flow
- `/summary` hybrid flow
- safe delete basic
- citations and quality gates

### Weeks 5-8

- recovery UX hardening
- saved views lite
- weekly review lite
- ranking / search improvements

### Weeks 9-12

- onboarding experiments
- migration optimization from bot to app
- first monetization hypothesis test

## 12. What to Cut Now

Do not include these without a separate decision:

- clusters
- swipe review
- note health
- insight cards
- heavy dashboard metrics
- export / share flows

## 13. Final Product Thesis

The strongest current product version is:

- not “a smart bot”
- not “another second-brain app”
- but `reliable capture + fast retrieval + safe operations`
