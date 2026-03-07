# Bot + Mini App Product Blueprint

## 1) Strategy (90 Days)

### Goals

| Goal | KPI | Baseline (Assumption) | Target 90d |
|---|---|---:|---:|
| Increase value sessions | WAU with `>=1` value action (`find/summary/save`) | 100 | 350 |
| Shift UX to Mini App | Share of active users opening Mini App in 7 days | 5% | 45% |
| Improve retention | D30 retention | 12% | 28% |

### JTBD

1. Quickly capture ideas/links without losing context.
2. Find where a note was stored in 5-10 seconds.
3. Get short grounded answers from personal notes.
4. Understand processing/errors without technical noise.
5. Delete/restore safely without fear of data loss.

### Segments

| Segment | Main Pain | Bot Role | Mini App Role |
|---|---|---|---|
| Solo founder | Idea chaos | Fast inbox capture | Dashboard, topic overview, weekly review |
| Content creator | Many links/drafts | Quick capture + tags | Batch triage, content pipeline |
| Technical researcher | Complex retrieval | Fast commands + shortcuts | Deep search, graph, jobs panel |

## 2) Bot vs Mini App Principle

1. Bot = Control Plane (quick capture, status, emergency commands).
2. Mini App = Workbench (search/filter/bulk actions/graph).
3. Hybrid = bot replies + deep-link to exact Mini App screen.

## 3) Feature Matrix (15)

| Feature | Placement | Impact (1-5) | Effort (1-5) | Priority |
|---|---|---:|---:|---|
| Smart Inbox Capture | Bot | 5 | 2 | P0 |
| One-tap “Open in App” per result | Hybrid | 5 | 1 | P0 |
| Unified Search (semantic + keyword + filters) | Mini App | 5 | 3 | P0 |
| Summary with source confidence bar | Hybrid | 5 | 3 | P0 |
| Jobs Center (queue/errors/retry) | Mini App | 4 | 2 | P0 |
| Safe Delete (preview + undo window) | Hybrid | 5 | 3 | P0 |
| Daily Briefing card | Bot | 4 | 2 | P1 |
| Topic Clusters (auto-group notes) | Mini App | 4 | 3 | P1 |
| Note Health Score | Mini App | 4 | 2 | P1 |
| Saved Views | Mini App | 3 | 2 | P1 |
| Cross-note link suggestions | Mini App | 4 | 3 | P1 |
| Quick Templates (`idea/task/meeting`) | Bot | 3 | 1 | P1 |
| Shareable read-only digest | Mini App | 3 | 3 | P2 |
| Voice pipeline visibility | Mini App | 3 | 2 | P2 |
| Weekly review workflow | Mini App | 4 | 2 | P2 |

## 4) Telegram UX Flows

### A) Onboarding (0 -> first value <5 min)
- Trigger: `/start`
- Steps:
  1. Bot shows 3 buttons: `Capture`, `Search`, `Open App`.
  2. User sends first note.
  3. Bot confirms save and offers deep-link to note card.
- Done condition: first successful save + first open in app.

### B) Daily active flow
- Trigger: user sends text/link.
- Steps:
  1. Bot acknowledges intake.
  2. Processing completes.
  3. Bot offers `Open in App` for enrichment/tagging.
- Done condition: at least one retrieval or summary after capture.

### C) Power-user flow
- Trigger: `/find <query>`
- Steps:
  1. Bot returns top-3 short hits.
  2. CTA: `Open advanced search`.
  3. Mini App opens with prefilled query + filters.
- Done condition: result click + note open.

### D) Recovery flow
- Trigger: `/status` shows failures.
- Steps:
  1. Bot shows failed count.
  2. CTA: `Open Jobs`.
  3. User retries from Jobs panel.
- Done condition: failed job moved to done/retry state.

### E) Bot -> Mini App conversion
- Rule: Every long answer includes one actionable app CTA.
- Done condition: user opens Mini App at least once per week.

### Bot Message Examples

- Success: `✅ Saved. Title: "Q2 ideas". Open note card in Mini App?`
- Error: `⚠️ Could not parse link (timeout). Tap Retry or Open Jobs.`
- Delete safety: `🗑 You are deleting 12 notes. Undo available for 30s.`

## 5) Mini App IA + UI Spec (v1)

### Navigation
- Tabs: `Dashboard`, `Search`, `Jobs`, `Settings`
- Deep-linked screen: `Note Detail`

### Screen: Dashboard
- Top bar: workspace selector, date range, quick add.
- Section 1: KPI cards (`new notes`, `failed jobs`, `stale notes`).
- Section 2: Recent activity list.
- Section 3: Quick actions (`Retry failed`, `Run briefing`, `Open search`).
- Empty state: “No notes yet” + capture CTA.
- Error state: compact banner + retry.
- Loading: skeleton cards.

### Screen: Search
- Query bar + chips (date/tag/source).
- Result cards: title, snippet, confidence, source.
- Actions: open note, summarize, copy link.
- Empty state: suggestions + recent queries.
- Error state: fallback keyword search CTA.

### Screen: Note Detail
- Header: title, created, tags.
- Blocks: content, related notes, source references.
- Actions: retag, regenerate summary, delete, restore.
- Safety: destructive actions behind confirmation sheet.

### Screen: Jobs
- Tabs: `processing`, `retry`, `failed`, `done`.
- Row: job id, status, last error, timestamp.
- Actions: retry single, retry all failed, inspect payload.
- Empty state: “Queue healthy”.

### Screen: Settings
- Profile summary.
- Tenant mode visibility.
- Notification toggles.
- Data safety controls.

## 6) Command Redesign (Control Plane)

| Command | New Purpose | Response Style |
|---|---|---|
| `/start` | Onboarding launcher | Buttons: Capture / Search / Open App |
| `/status` | Ops snapshot | Uptime + failures + Jobs CTA |
| `/find q` | Quick top-3 retrieval | Compact result + advanced search CTA |
| `/summary q` | Short grounded answer | Answer + confidence + sources + app CTA |
| `/job id` | Exact job state | Status + retry action |
| `/retry id` | Operational fix | Confirmation + Jobs deep-link |
| `/delete ...` | Safe destructive action | Preview + token + undo window |

## 7) Analytics Plan

### Core Event Schema

`event_name | trigger | properties | purpose`

1. onboarding_started | `/start` opened | user_id, source | funnel start
2. onboarding_completed | first save | time_to_value | onboarding quality
3. command_start | `/start` | command, tenant | command usage
4. command_status | `/status` | command, failures_count | ops awareness
5. command_find | `/find` submit | query_len | retrieval demand
6. command_summary | `/summary` submit | query_len | answer demand
7. command_delete | delete requested | scope(single/all) | destructive intent
8. command_retry | retry requested | job_ref | error recovery
9. miniapp_opened | deep-link/open | entry_point | adoption
10. miniapp_dashboard_view | dashboard open | tenant | engagement
11. miniapp_search_view | search screen open | tenant | search usage
12. miniapp_jobs_view | jobs screen open | failed_count | reliability ops
13. miniapp_note_view | note opened | note_id | content engagement
14. search_submitted | search action | query, filters | retrieval behavior
15. search_result_clicked | result click | rank, score | relevance quality
16. summary_requested | summary action | mode | summary usage
17. summary_feedback_positive | thumbs up | query_id | quality loop
18. summary_feedback_negative | thumbs down | query_id | quality loop
19. job_failed_seen | failed row shown | error_code | visibility
20. job_retry_clicked | retry action | job_id | recovery action
21. delete_requested | delete initiated | count | risk tracking
22. delete_confirmed | delete confirmed | count, token_age | safety
23. delete_undo_used | undo pressed | latency | safety UX
24. capture_text_received | text intake | length | intake mix
25. capture_link_received | link intake | domain | parser mix
26. capture_voice_received | voice intake | duration | media mix
27. error_parser_timeout | parser timeout | parser, domain | parser reliability
28. error_auth_denied | auth reject | user_id | access anomalies
29. tenant_mismatch_detected | mismatch | queue_tenant,payload_tenant | isolation risk
30. session_ended | inactivity/session end | session_len | retention modeling

### North Star
- Weekly Value Sessions = unique users with `capture + (find or summary)` in 7 days.

### Guardrails
1. Failed jobs rate.
2. P95 summary latency.
3. Cross-tenant incident count.
4. Delete undo usage ratio.
5. Auth-deny false positives.

### Funnels
1. Bot onboarding funnel: `/start` -> first capture -> first retrieval.
2. Mini App adoption funnel: bot CTA shown -> app opened -> note/search action.
3. Retrieval-to-value funnel: query -> result click -> follow-up action.

## 8) Security/Abuse by Design

| Risk | UX Mitigation | Backend Mitigation | Monitoring Signal |
|---|---|---|---|
| Accidental mass delete | Preview + token + undo | TTL confirmation + tenant scope | delete_all spikes |
| Flood/burst | Debounced responses | per-user rate limit | commands/min/user |
| Cross-tenant leakage | No global views in UI | strict tenant filter | cross-tenant query count |
| Ambiguous errors | Human-readable errors | typed error codes | unknown_error ratio |
| Poison jobs | Jobs center + capped retries | quarantine + retry caps | retry storm metric |

## 9) Build Plan

### Week 1 (quick wins)
- Deep-links from bot replies to Mini App stubs.
- `/start` redesign with CTA buttons.
- `/status` cardized output with jobs CTA.
- Event tracking skeleton.

### Weeks 2-4 (v1 launch)
- Mini App: Dashboard, Search, Jobs, Note Detail.
- Hybrid command integration.
- Safe delete flow with undo window.

### Weeks 5-8 (stability + growth)
- Topic clusters.
- Note health score.
- Saved views and feedback loop.

### Weeks 9-12 (differentiation)
- Weekly briefing.
- Cross-note link suggestions.
- Retention and monetization experiments.

## 10) Top 3 Bets

1. Hybrid Search (`bot quick + app full`)
   - Why: highest frequency pain point.
   - Expected impact: WAU and retention lift.

2. Jobs Center + Error UX
   - Why: trust and reliability perception.
   - Expected impact: lower support load, faster recovery.

3. Safe Delete + Undo
   - Why: highest-risk destructive path.
   - Expected impact: safer adoption and less user anxiety.
