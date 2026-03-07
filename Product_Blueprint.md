# Detailed Product Blueprint: Telegram Bot Transition to a Hybrid Bot + Mini App Model

This document is intentionally pragmatic and optimized for a small team working toward measurable product outcomes.

## 1. Product Strategy

### 90-Day Product Goals

| Goal | KPI | Baseline | 90-Day Target |
| --- | --- | ---: | ---: |
| Successful audience migration | Share of bot DAU opening the Mini App at least once per day | 0% | > 60% |
| Deeper engagement | Average number of viewed entities per session | 1.2 | 3.5 |
| Lower interaction frustration | Share of commands ending in syntax errors or empty results | 15% | < 3% |

### Core Jobs To Be Done

1. **Capture:** Drop a link or note in one place in one second and move on.
2. **Retrieve:** Find remembered ideas by meaning, not exact quote.
3. **Consume:** Get value from saved material in small time windows.
4. **Manage:** Triage accumulated information quickly.
5. **Recover:** Understand failed processing and retry without console-driven workflows.

### Segment Positioning

| Segment | Main Pain | Bot Role | Mini App Role |
| --- | --- | --- | --- |
| Information hoarder | Saves endlessly, rarely reads | Silent inbox capture | AI briefing feed and review UI |
| Researcher / student | Retrieval quality is poor | Quick `/find` | Full semantic search workspace |
| Task / job manager | Background processing is opaque | Push notifier | Queue and jobs dashboard |

## 2. Feature Matrix

| Feature | Placement | Impact | Effort | Priority |
| --- | --- | ---: | ---: | --- |
| Quick Append (Silent) | Bot | 5 | 1 | P0 |
| Global Semantic Search | Mini App | 5 | 3 | P0 |
| Native Article Reader | Mini App | 4 | 2 | P0 |
| Active Jobs & Queue UI | Mini App | 4 | 2 | P0 |
| Magic `/find` shortcut | Hybrid | 3 | 1 | P1 |
| Tinder-style Review | Mini App | 4 | 3 | P1 |
| AI Briefing Digest | Hybrid | 5 | 4 | P1 |
| Bulk Delete Dashboard | Mini App | 3 | 2 | P1 |
| One-tap Visual Retry | Mini App | 3 | 2 | P2 |
| Semantic Cluster Views | Mini App | 4 | 5 | P2 |
| Recycle Bin (Soft Delete) | Mini App | 2 | 2 | P2 |
| Source-Type Filters | Mini App | 3 | 2 | P2 |
| “Did you know?” insights | Mini App | 3 | 3 | P3 |
| Note Health Score | Mini App | 2 | 3 | P3 |
| Multi-selection Export | Mini App | 1 | 2 | P3 |

## 3. Telegram UX Flows

### A. New User Onboarding

- Trigger: `/start`
- Bot explains what to send first
- User sends a YouTube link
- Bot acknowledges processing and later offers `Open My Base (Mini App)`
- Mini App opens on a dashboard or note card
- Done condition: first successful save plus first open in app

### B. Daily Active User Flow

- Trigger: user shares a link from the browser into the bot
- Bot gives a quiet acknowledgment
- Later retrieval happens through a “My Base” entrypoint or deep link into search

### C. Power User Flow

- Trigger: user sends a large archive of files
- Bot acknowledges queue placement
- Mini App shows progress states and failures

### D. Recovery Flow

- Trigger: parsing fails
- Bot sends a short notification
- Mini App opens a retry / alternative-processing flow with context

### E. Conversion Flow from Old Bot Commands

- Trigger: `/find metrics`
- Bot shows top results and a CTA for full search in the Mini App with prefilled query state

## 4. Mini App IA + UI Spec (v1)

### Navigation Model

- Bottom tabs: `Home`, `Search`, `Queue`, `Settings`

### Home

- greeting
- daily briefing card
- recent additions
- processing / status badges

### Search

- sticky input
- horizontal filter chips
- recent searches
- semantic suggestions

### Note Detail

- title and metadata
- AI summary
- transcript / full text
- related notes

### Jobs / Queue

- active processes
- progress bars
- failed jobs with retry and delete actions

## 5. Command Redesign

- `/start`: short intro plus Mini App button
- `/status`: compact health and queue summary plus queue CTA
- `/find {query}`: best result plus CTA into the app
- `/summary`: teaser or compact summary plus “read full briefing”
- `/job`: hidden or power-user-only
- `/retry`: mostly replaced by inline retry actions
- `/delete {id}`: soft delete plus `[Undo]`

## 6. Data and Analytics Plan

### North Star Metric

Successful Retrieval Rate:

- a search or view session ends with value extraction
- example signals: source click, meaningful note read, copy-like follow-up behavior

### Guardrail Metrics

1. Bot unsubscribe / block rate
2. Failed jobs percentage
3. P95 parsing time
4. Mini App bounce under 3 seconds
5. Support volume / angry feedback

### Example Events

- `bot_message_sent`
- `bot_command_used`
- `miniapp_opened`
- `miniapp_search_performed`
- `miniapp_search_result_clicked`
- `miniapp_note_viewed`
- `miniapp_action_delete`
- `miniapp_action_undo`
- `job_retry_invoked`
- `briefing_push_opened`

## 7. Security and Abuse by UX Design

| Risk | UX Mitigation | Backend Mitigation | Monitoring |
| --- | --- | --- | --- |
| Accidental deletion | Soft delete + snackbar undo | Delayed hard delete | Undo spikes |
| Command flood / abuse | Hide heavy actions from the visible menu | Rate limiting | 429 spikes |
| Multi-tenant leakage | Non-guessable IDs and scoped routes | UUIDs and row-level access controls | 403 mismatch alerts |
| Malicious parsing input | Scanning indicators and timeout expectations | Isolation, strict timeouts, SSRF protection | Failure clustering |

## 8. Build Plan (12 Weeks)

### Week 1: Fast Wins and Hygiene

- reduce bot spam
- clean command responses
- establish a Mini App skeleton

### Weeks 2-4: v1 Launch

- Home dashboard view
- full-screen search
- note detail read view
- authenticated API endpoints
- app entrypoints from bot buttons

### Weeks 5-8: Stabilization and Growth

- queue / jobs UI
- retry actions
- soft delete
- front-end caching

### Weeks 9-12: Differentiation

- inbox review interactions
- daily briefing generation
- richer push campaigns

## 9. Top 3 Bets

1. **Silent Append in the Bot**
2. **Global Semantic Search in the Mini App**
3. **AI Briefing Digest**

## 10. Open Questions

1. Can the current backend expose secure REST / GraphQL APIs for Telegram Web App auth?
2. Is there budget for proactive LLM-generated briefings?
3. What is the current semantic-search latency?
4. Should the Mini App support offline caching?
5. How often do jobs fail in production-like use?
