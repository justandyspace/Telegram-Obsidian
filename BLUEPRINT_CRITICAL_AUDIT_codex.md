# Critical Audit: Bot + Mini App Blueprint

Источник анализа: [PRODUCT_BLUEPRINT_BOT_MINIAPP.md](C:\Users\Desktop\Desktop\telegram-obsidian-local\PRODUCT_BLUEPRINT_BOT_MINIAPP.md)

## 1) Executive Assessment

| Axis | Score (0-10) | Why |
|---|---:|---|
| Product clarity | 7.5 | 1) Хорошо сформулирован split `Bot=control`, `MiniApp=workbench`. 2) Есть JTBD и сегменты. 3) Не хватает четкой product boundary v1 vs v2 (слишком много P1/P2 уже в 90d). |
| User value | 8.0 | 1) Попадает в реальные боли: capture/find/safe-delete. 2) Есть ценность для разных сегментов. 3) Нужна более явная “wow-loop” для регулярного возврата кроме `/find`. |
| UX quality | 6.5 | 1) Флоу описаны, но есть лишние переходы bot↔app. 2) Нет жесткой оптимизации Time-to-First-Value (TTFV) в 1-2 действия. 3) Recovery/delete есть, но microcopy и прогресс-индикаторы недоопределены. |
| Technical feasibility | 7.0 | 1) P0 реалистичен. 2) Есть риск переоценки для `semantic+keyword+filters+confidence+sources` одновременно. 3) Много stateful вещей (undo TTL, jobs, tenant safety) требуют сильной backend дисциплины. |
| Operational readiness | 5.5 | 1) Есть `/status`, Jobs, базовая observability. 2) Нет SLO/SLA и runbook ownership. 3) Нет четкого incident matrix и rollback policy. |
| Growth/monetization potential | 5.5 | 1) Есть adoption funnel в Mini App. 2) Monetization формулировка слишком общая (“experiments”). 3) Нет pricing hypothesis по сегментам и paywall placement. |

## 2) Structural Consistency Check

| Conflict ID | Где найдено | В чем конфликт | Риск | Как исправить |
|---|---|---|---|---|
| C-01 | Goals vs Features | Цель D30=28%, но фичи retention в основном P1/P2 (weekly review/briefing поздно) | Retention не вырастет в первые 30-45 дней | Перенести 1 retention loop (weekly briefing lite) в Weeks 2-4 |
| C-02 | Goals vs KPI schema | Goal “shift UX to Mini App 45%”, но нет KPI “7-day deep-link CTR per user cohort” | Невозможно управлять миграцией | Добавить KPI: `bot_cta_click_rate`, `app_open_after_bot_cta_24h` |
| C-03 | Features vs Roadmap | P0 “Summary with confidence bar + sources” в matrix, но в build plan не выделено явно | Срыв качества ответа/доверия | Явно включить в Weeks 2-4 как отдельный deliverable с quality gates |
| C-04 | Features vs Roadmap | P0 “Jobs Center” есть, но в Week1 только статус/CTA, без error taxonomy | Recovery flow формально есть, фактически слабый | До запуска v1 зафиксировать error codes + retry policies |
| C-05 | UX Flows vs Analytics | Flow done condition onboarding включает “first open in app”, но event `onboarding_completed=first save` | Ложноположительное “completed” | Разделить `onboarding_completed_bot` и `onboarding_completed_hybrid` |
| C-06 | UX Flows vs Analytics | Daily flow done condition: retrieval/summary после capture, но нет события “value_session_completed” | North Star считается косвенно и шумно | Добавить композитный event/derived metric на сессию |
| C-07 | Security vs UX promises | “Undo 30s” обещан, но нет UX для long-running delete/partial failures | Потеря доверия при race conditions | Добавить state: `deletion_pending`, `partially_deleted`, `restore_status` |
| C-08 | Security vs UX promises | “Inspect payload” в Jobs может раскрыть чувствительные данные | Data leakage | Маскирование PII + RBAC для payload inspect |
| C-09 | Bot/Mini split vs complexity | Почти каждый flow заканчивается CTA в Mini App | UX ping-pong, падает completion | Ввести routing rules: короткие задачи закрывать в bot полностью |
| C-10 | IA vs сегменты | Dashboard KPI-heavy для новых пользователей | Когнитивная перегрузка в day-1 | Ввести simplified first-run dashboard (“3 actions only”) |
| C-11 | Metrics vs decisions | Много событий usage-level, мало quality-level (answer correctness, failed recovery resolution time) | Команда оптимизирует шум | Добавить quality метрики и decision thresholds |
| C-12 | Monetization vs roadmap | “Monetization experiments” без package definition | Эксперименты без learning | Определить 2 pricing hypotheses и trigger metrics до Week 8 |

## 3) Feature Quality Review

| Feature | Value score (1-5) | Complexity risk | Hidden dependency | Cut/Keep/Delay | Why |
|---|---:|---|---|---|---|
| Smart Inbox Capture | 5 | Medium | Parser quality, dedupe, idempotency | Keep | Core value loop |
| One-tap Open in App | 5 | Low | Deep-link reliability in Telegram | Keep | Ключ к migration |
| Unified Search (semantic+keyword+filters) | 5 | High | Index freshness, ranking, embeddings infra | Keep (scope cut) | В v1: keyword+basic semantic, без сложных фильтров |
| Summary + confidence bar | 4 | High | Citation grounding, latency budget | Keep (scope cut) | Confidence только с source coverage, не “магический score” |
| Jobs Center | 4 | Medium | Queue observability, error taxonomy | Keep | Trust/recovery |
| Safe Delete + undo | 5 | High | Soft-delete store, TTL, restore atomicity | Keep | Safety must-have |
| Daily Briefing card | 3 | Medium | Scheduling, relevance ranking | Delay | Не критично для v1 activation |
| Topic Clusters | 3 | High | NLP clustering quality | Delay | High effort, uncertain ROI early |
| Note Health Score | 2 | Medium | Scoring model explainability | Delay | Риск vanity |
| Saved Views | 3 | Medium | Query persistence + UX discoverability | Keep (lite) | 1-2 preset views only |
| Cross-note link suggestions | 3 | High | Graph quality + false positives | Delay | Better post-PMF |
| Quick Templates | 4 | Low | Template UX in bot | Keep | Быстрый прирост capture quality |
| Shareable read-only digest | 2 | Medium | Access control/public token safety | Delay | Security-sensitive |
| Voice pipeline visibility | 3 | Medium | ASR job states, media handling | Delay | Нишево для v1 |
| Weekly review workflow | 4 | Medium | Cadence notifications + summaries | Keep (lite) | Retention lever, but lite checklist only |

## 4) Bot vs Mini App Migration Audit

### Что верно оставлено в Bot
- Capture, быстрый `/find`, `/status`, подтверждения destructive действий.
- Retry single-job по ID и короткие operational ответы.

### Что надо унести в Mini App
- Любой multi-step triage: batch retry, filter+sort, note retag, bulk delete preview.
- Deep retrieval analysis: advanced filters, related notes, long summaries.

### Где UX ping-pong
- `/find` -> open app даже когда top-3 уже достаточны.
- Ошибки parser: пользователь уходит в Jobs для простого retry.
- Delete: слишком ранний перевод в app при малом объеме (1-2 notes).

### Как снизить friction
- Закрывать “small tasks” в bot до конца.
- Передавать prefilled state в app (query, filters, selected note/job).
- Вводить threshold routing по сложности.

### Routing rules
- `If quick capture/find/status/retry-single/delete<=2 items -> Bot`
- `If query needs filters, batch actions, history review, >3 results triage -> Mini App`
- `If summary generated in bot but user asks “show sources/related/edit tags” -> Hybrid`
- `If failures_count<=2 and deterministic retry -> Bot; else -> Mini App Jobs`
- `If destructive action >2 items or older than 24h notes -> Mini App with confirmation sheet`

## 5) UX Critique

| Flow | Drop-off risk | Микрокопирайт правки | Лишние шаги | Как ускорить first value |
|---|---|---|---|---|
| Onboarding | Кнопка `Open App` слишком рано, пользователь еще не понял value | Вместо “Open App” -> “Сначала сохраним первую заметку” | Ранний app jump | `/start` сразу показывает input hint + template chips |
| Daily flow | “Processing completes” без ETA вызывает тревогу | “Сохраняю… обычно до 5с” + прогресс-стейт | Отправка в app ради tagging | Inline quick-tags в bot (2-3 suggested tags) |
| Power-user | top-3 без explainability | Добавить “Почему эти результаты” (1 строка) | Обязательный переход в app | Дать `Show 3 more` в bot перед CTA |
| Recovery | `/status` агрегирован, но непонятно что чинить первым | “2 критичные ошибки, начните с parser timeout” | Переход в Jobs для single retry | Кнопка `Retry critical now` прямо в bot |
| Delete | Тревога/страх, если copy абстрактный | “Будут удалены: 12 заметок, восстановление 30с” + список примеров | Лишний экран confirm в app для small delete | Для 1 note: bot confirm + undo без app |

### Улучшенные bot-copy примеры
- `Сохранено: "Q2 ideas". Добавить теги сейчас? [#idea] [#meeting] [Открыть в App]`
- `Нашел 3 совпадения. Показать еще 3 здесь или открыть расширенный поиск в App?`
- `Сводка готова (уверенность: средняя). Основано на 4 заметках. [Источники] [Уточнить] [Открыть в App]`
- `Ошибка парсинга домена medium.com (таймаут). [Повторить] [Игнорировать] [Jobs]`
- `Удаление 12 заметок подтверждено. Можно отменить в течение 30 секунд. [Отменить]`

## 6) UI/IA Critique (Mini App)

| Current IA issue | Better IA decision | Why |
|---|---|---|
| Dashboard перегружен KPI-карточками | First-run Dashboard = 3 блока: Continue, Failed jobs, Recent notes | Быстрее ориентирование |
| Separate Jobs tab всегда виден | Jobs как inbox badge + отдельный экран только при ошибках | Снижает noise для большинства |
| Settings как полноценный таб | Перенести Settings в profile drawer | Освобождает главный nav |
| Слишком много действий в Note Detail | Primary CTA только 2: Edit tags, Open sources | Уменьшает CTA conflict |
| Search results без явного next action | На карточке 1 primary action: Open, secondary in kebab menu | Четче decision path |
| Empty states общие | Contextual empty states per filter/query type | Выше discoverability |
| Error state “fallback keyword” только в Search | Глобальный inline error framework (retry + diagnostics ID) | Единая mental model |

### Рекомендованный v1 IA (минимум complexity)
- Bottom tabs: `Home`, `Search`, `Activity`
- `Home`: Continue where left off, Quick capture hints, Critical errors badge
- `Search`: query + filters + results + note detail deep-link
- `Activity`: jobs + recent actions + delete/restore history
- `Settings/Profile`: в side sheet
- Убрать из v1: standalone Dashboard KPI wall, отдельный Jobs tab

## 7) Metrics & Analytics Audit

### Проблемы текущего плана
- Слишком много event-объема, мало decision-метрик.
- Есть риск vanity: `miniapp_dashboard_view`, `command_start`.
- Нет измерения качества результатов (retrieval precision proxy, citation click-through, recovery success latency).

### Чего не хватает
- `time_to_first_value_seconds`
- `query_success_rate` (result click within 60s)
- `summary_accept_rate` (copy/save/follow-up)
- `retry_resolution_time_p50/p95`
- `undo_regret_rate` (delete undo / delete confirmed, сегментированно)
- `deep-link success rate` (bot->app open with correct context)

### Vanity -> Actionable замены
- `command_start` -> `command_completion_rate by command`
- `miniapp_dashboard_view` -> `task_completed_in_app_rate`
- `session_ended` -> `value_session_rate by cohort`

### North Star (лучше)
- `Weekly Successful Knowledge Tasks (WSKT)` = unique users/7d с `capture` + `successful retrieval or accepted summary` + `no unresolved critical error in session`.

### 5 guardrails
1. `Critical error rate per value session`
2. `P95 time_to_answer` (find/summary)
3. `Cross-tenant incident count` (must be zero)
4. `Delete regret rate` (undo ratio + support tickets)
5. `Deep-link context mismatch rate`

### 3 decision dashboards
1. `Activation Dashboard`
- Метрики: start->first capture, first capture->first retrieval, TTFV
- Решения: правки onboarding copy, template defaults, CTA order

2. `Quality & Reliability Dashboard`
- Метрики: query_success_rate, summary_accept_rate, retry_resolution_time, error taxonomy
- Решения: ranking/model tuning, parser priorities, retry policy

3. `Migration & Monetization Dashboard`
- Метрики: bot CTA CTR, app-open-after-cta, task completion in app, paid-intent proxy (advanced usage frequency)
- Решения: bot/app routing thresholds, paywall placement, packaging

## 8) Security & Abuse Readiness

| Risk | Severity | Likelihood | Gap | Required control before launch |
|---|---|---|---|---|
| Cross-tenant data leak in search | Critical | Medium | Tenant checks описаны общо | Enforce tenant_id at query builder + contract tests |
| Payload exposure in Jobs inspect | High | Medium | Нет PII masking policy | Redaction layer + role-based access |
| Undo race conditions on delete | High | Medium | Нет atomic restore guarantees | Soft-delete with versioning + transactional restore |
| Token replay for destructive actions | High | Low-Med | TTL указан, anti-replay нет | One-time nonce + bind to user/session |
| Retry storm amplifies failure | Medium-High | High | “Capped retries” без thresholds | Exponential backoff + circuit breaker |
| Flood abuse via bot commands | Medium | High | Rate limit без tiering | Per-user + per-tenant quotas + anomaly alerts |
| Prompt/data injection via links | High | Medium | Parser timeout only | URL sanitization + content-type allowlist + sandbox parsing |
| Missing incident observability | High | Medium | Нет runbook+alert matrix | SLO alerts, incident channel, on-call ownership |
| Auth-deny false positives | Medium | Medium | Только metric guardrail | Debug trace IDs in user-safe errors |

## 9) Delivery Realism

### Где переоценка
- Weeks 2-4: одновременно full Search, Jobs, Note Detail, safe delete, hybrid summary quality.
- Weeks 5-8: topic clusters + note health + saved views вместе слишком широко.
- Weeks 9-12: differentiation + monetization без стабилизированной quality loop рискованно.

### Что выкинуть/перенести для маленькой команды
- Перенести после Week 8: Topic clusters, Cross-note suggestions, Shareable digest, Voice visibility.
- Сохранить в 90d только если quality метрики зеленые 2 недели подряд.

### Новый pragmatic roadmap

| Period | Deliverables | Acceptance criteria |
|---|---|---|
| Week 1 | `/start` v2, deep-link infra, basic events, command telemetry | 1) TTFV < 120s median на тест-когорте. 2) Deep-link success > 95%. |
| Weeks 2-4 | v1 core: capture, `/find` top-3 + `show more`, Search basic, Jobs basic, Safe delete (single + small batch), summary with citations | 1) Query success rate > 60%. 2) Retry resolution p50 < 2 min. 3) No P0 tenant leaks. |
| Weeks 5-8 | Reliability hardening, Saved views lite, weekly review lite, better recovery UX | 1) Failed job rate < 5%. 2) D7 retention +20% vs baseline cohort. |
| Weeks 9-12 | Controlled growth: onboarding experiments, app migration tuning, first monetization probe | 1) 7d Mini App adoption > 30% active users. 2) Paid-intent proxy defined and tracked. |

## 10) Final Verdict

**GO with conditions**

### Top-12 обязательных правок перед активной реализацией
1. Переопределить onboarding completion (bot-only vs hybrid).
2. Ввести strict routing rules bot/app по сложности задачи.
3. Упростить v1 search scope (без перегруза фильтрами).
4. Зафиксировать summary quality contract (citations mandatory).
5. Сделать delete flow atomic + anti-replay token.
6. Ограничить Jobs payload inspect (PII redaction + RBAC).
7. Добавить quality/SLO metrics, не только usage events.
8. Вынести Settings из tab bar; сократить IA до 3 основных зон.
9. Ввести error taxonomy и retry policy до launch.
10. Перенести high-risk P1/P2 (clusters, link suggestions) за Week 8.
11. Определить monetization hypothesis до начала экспериментов.
12. Назначить incident ownership + runbooks + alert thresholds.

### Revised Top 3 Bets
1. `Fast Capture + Reliable Retrieval` (TTFV + query success)
2. `Trust Layer` (Jobs recovery + Safe delete correctness)
3. `Frictionless Bot->App Migration` (context-preserving deep-links + threshold routing)

### Open questions (must answer before final PRD)
1. Какой допустимый P95 latency для `/find` и `/summary`?
2. Что считается “accepted summary” в продуктовой логике?
3. Какой ranking fallback при недоступности semantic index?
4. Какой лимит batch delete для bot-only path?
5. Где хранится undo state и как гарантируется atomic restore?
6. Кто имеет доступ к Jobs payload inspect?
7. Какие tenant isolation tests обязательны в CI?
8. Какой формат deep-link context и TTL?
9. Какое минимальное качество Search нужно для GA?
10. Какие сегменты являются ICP на первые 90 дней?
11. Есть ли human-in-the-loop для unknown errors?
12. Какая схема quota/rate limits по тарифам?
13. Какой paid package тестируется первым?
14. Как выглядит rollback plan при росте error rate?
15. Какие 2-3 эксперимента onboarding приоритетны в Weeks 9-12?

**Assumption:** анализ выполнен только по содержимому blueprint; архитектурные ограничения текущего кода, размер команды и фактические SLA не предоставлены.

codex
