# Critical Audit: Bot + Mini App Blueprint

Source analyzed: `PRODUCT_BLUEPRINT_BOT_MINIAPP.md`

## 1. Executive Assessment

| Axis | Score (0-10) | Summary |
| --- | ---: | --- |
| Product clarity | 7.5 | The `Bot = control`, `Mini App = workbench` split is strong, but v1/v2 boundaries are still too loose. |
| User value | 8.0 | Capture, find, and safe delete map to real user pain points, but the return loop after first use needs to be stronger. |
| UX quality | 6.5 | Core flows exist, yet there is too much bot-to-app ping-pong and not enough TTFV optimization. |
| Technical feasibility | 7.0 | P0 looks realistic, but advanced search, source confidence, and jobs state all at once increase delivery risk. |
| Operational readiness | 5.5 | Basic observability exists, but SLOs, incident ownership, and rollback policy are not defined. |
| Growth / monetization | 5.5 | Adoption mechanics exist, but pricing and monetization hypotheses are still vague. |

## 2. Structural Consistency Check

| Conflict ID | Area | Conflict | Risk | Fix |
| --- | --- | --- | --- | --- |
| C-01 | Goals vs features | D30 retention depends on loops that are mostly delayed to P1/P2 | High | Move one lightweight retention loop into Weeks 2-4 |
| C-02 | Goals vs KPIs | Mini App migration goal exists without direct CTR / open follow-up metrics | Medium | Add `bot_cta_click_rate` and `app_open_after_bot_cta_24h` |
| C-03 | Features vs roadmap | Summary quality with confidence and sources is not explicitly staged | High | Make it an explicit deliverable with quality gates |
| C-04 | Features vs roadmap | Jobs Center is present, but error taxonomy is not | High | Define error codes and retry policy before launch |
| C-05 | UX vs analytics | Onboarding completion is measured too early | Medium | Split bot-only completion from hybrid completion |
| C-06 | UX vs analytics | No session-level metric for “capture then retrieve” | Medium | Add a derived value-session metric |
| C-07 | Security vs UX | Undo and delete recovery states are underdefined | High | Add pending / partial / restore states |
| C-08 | Security vs UX | Jobs payload inspection may leak sensitive data | High | Add PII masking and access controls |
| C-09 | Bot / app split | Almost every flow ends in a Mini App CTA | Medium | Close small tasks inside the bot |
| C-10 | IA vs audience | KPI-heavy dashboard is too much for first-day users | Medium | Add a simplified first-run home screen |
| C-11 | Metrics vs decisions | Too many usage events, not enough quality metrics | Medium | Add answer quality and recovery latency metrics |
| C-12 | Monetization vs roadmap | Monetization experiments exist without package definition | Medium | Define pricing hypotheses before experiments |

## 3. Feature Review

| Feature | Value | Risk | Recommendation |
| --- | ---: | --- | --- |
| Smart Inbox Capture | 5 | Medium | Keep |
| One-tap Open in App | 5 | Low | Keep |
| Unified Search | 5 | High | Keep, but reduce initial scope |
| Summary + confidence | 4 | High | Keep, but require citation-backed confidence |
| Jobs Center | 4 | Medium | Keep |
| Safe Delete + Undo | 5 | High | Keep |
| Daily Briefing | 3 | Medium | Delay or ship as a lightweight version |
| Topic Clusters | 3 | High | Delay |
| Note Health Score | 2 | Medium | Delay |
| Saved Views | 3 | Medium | Keep as a limited v1 |
| Cross-note links | 3 | High | Delay |
| Quick Templates | 4 | Low | Keep |
| Shareable digest | 2 | Medium | Delay |
| Voice pipeline visibility | 3 | Medium | Delay |
| Weekly review | 4 | Medium | Keep as a lightweight version |

## 4. Bot vs Mini App Migration Audit

### Keep in Bot

- capture
- quick `/find`
- `/status`
- single-job retry
- small safe delete

### Move to Mini App

- multi-step triage
- advanced retrieval workflows
- bulk actions
- detailed jobs analysis

### Routing Rules

- `quick capture / find / status / retry-single / delete<=2 items -> Bot`
- `filtered search / batch actions / history review / >3 results -> Mini App`
- `summary in bot + source exploration -> Hybrid`
- `deterministic retry with <=2 failures -> Bot; otherwise -> Mini App Jobs`
- `destructive action on >2 items or older notes -> Mini App`

## 5. UX Critique

Main issues:

- onboarding pushes the Mini App too early
- status and recovery need clearer next actions
- delete flows need stronger confidence-building copy
- small tasks should finish in-chat instead of bouncing the user into the Mini App

Suggested copy examples:

- `Saved: "Q2 ideas". Add tags now? [#idea] [#meeting] [Open in App]`
- `Found 3 matches. Show 3 more here or open advanced search in the app?`
- `Summary ready (confidence: medium), based on 4 notes. [Sources] [Refine] [Open in App]`
- `Parser timeout on medium.com. [Retry] [Ignore] [Jobs]`

## 6. Mini App IA Critique

Recommended v1 information architecture:

- Bottom tabs: `Home`, `Search`, `Activity`
- `Home`: continue where left off, critical issues, recent notes
- `Search`: query, filters, results, detail deep-links
- `Activity`: jobs, retries, delete / restore history
- `Settings`: move into a side sheet or profile drawer

Remove for v1:

- KPI wall dashboard
- dedicated Jobs tab for all users

## 7. Metrics and Analytics Audit

Suggested north star:

`Weekly Successful Knowledge Tasks (WSKT)` = unique users over 7 days who completed capture plus a successful retrieval or accepted summary without an unresolved critical error in session.

Recommended guardrails:

1. Critical error rate per value session
2. P95 time to answer for find / summary
3. Cross-tenant incident count
4. Delete regret rate
5. Deep-link context mismatch rate

## 8. Security and Abuse Readiness

Priority controls before launch:

- enforce tenant filters in every query path
- redact payloads in Jobs views
- make delete undo atomic and versioned
- prevent replay on destructive actions
- add retry backoff and circuit breakers
- add quotas on bot and Mini App usage
- harden link parsing and content-type allowlists
- define incident alerts and ownership

## 9. Delivery Realism

Recommended roadmap:

- Week 1: `/start` v2, deep-link infrastructure, telemetry basics
- Weeks 2-4: core v1 with capture, lightweight search, jobs basics, safe delete, citation-backed summary
- Weeks 5-8: reliability hardening, saved views lite, weekly review lite
- Weeks 9-12: onboarding optimization, migration tuning, first monetization probe

## 10. Final Verdict

**Go with conditions**

### Top 12 Required Changes Before Active Implementation

1. Redefine onboarding completion for bot-only vs hybrid.
2. Add strict bot/app routing rules.
3. Reduce v1 search scope.
4. Require citations in the summary quality contract.
5. Make delete atomic and replay-safe.
6. Restrict Jobs payload inspection with redaction and RBAC.
7. Add quality and SLO metrics, not only usage metrics.
8. Move Settings out of the tab bar and simplify IA.
9. Define error taxonomy and retry policy before launch.
10. Push high-risk P1/P2 items after Week 8.
11. Define monetization hypotheses before experiments.
12. Assign incident ownership and alert thresholds.

### Open Questions

1. What is the acceptable P95 latency for `/find` and `/summary`?
2. What qualifies as an accepted summary?
3. What is the ranking fallback if semantic search is unavailable?
4. What is the maximum batch size for bot-only delete?
5. Where does undo state live and how is atomic restore guaranteed?
6. Who is allowed to inspect Jobs payloads?
7. Which tenant-isolation tests are mandatory in CI?
8. What deep-link context format and TTL will be used?
9. What minimum search quality is required for GA?
10. Which segments are the ICP for the first 90 days?
11. Is there a human-in-the-loop path for unknown errors?
12. What quota and rate-limit model applies by plan?
13. Which paid package is tested first?
14. What is the rollback plan if error rate rises?
15. Which onboarding experiments matter most in Weeks 9-12?

**Assumption:** this audit is based only on the blueprint contents. Current code constraints, team size, and real SLA expectations were not provided.
