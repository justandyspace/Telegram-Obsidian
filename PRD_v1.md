# PRD v1: Telegram Bot + Mini App

## 1. Product Frame

Продукт не должен "переехать из бота в Mini App".

Правильная модель:

- `Telegram Bot` = быстрый вход, уведомления, короткие команды
- `Mini App` = просмотр, поиск, разбор, управление

Главный value loop:

1. Пользователь быстро сохраняет ссылку, текст или файл в бота.
2. Система надежно обрабатывает это в фоне.
3. Пользователь потом быстро находит, читает или суммаризирует это через bot preview или Mini App.
4. Ошибки и destructive-сценарии прозрачны и безопасны.

## 2. Goals (90 Days)

### Goal 1: Speed up `capture -> first value`

- KPI: median `time_to_first_value < 2 min`

### Goal 2: Improve retrieval success

- KPI: `query_success_rate > 60%`
- Определение: пользователь получил результат и открыл заметку или источник

### Goal 3: Make Mini App a real work surface

- KPI: `30%+` активных пользователей открывают Mini App хотя бы раз за 7 дней
- Условие: open считается только если внутри было хотя бы 1 действие

### Goal 4: Reduce fear around failures and deletion

- KPI: `failed_job_resolution_p50 < 2 min`
- KPI: `delete_regret_rate` под контролем

## 3. ICP

Фокус на первые 90 дней:

- `Solo founder / knowledge worker`
- `Research-heavy user`

Не фокусироваться в v1:

- на геймификации для hoarders
- на массовом content management
- на social/share сценариях

## 4. Core JTBD

1. Быстро сохранить мысль, ссылку или файл без трения.
2. Найти нужную заметку по смыслу за 5-10 секунд.
3. Получить короткий grounded answer по своим заметкам.
4. Понять, что сломалось в обработке, и быстро исправить.
5. Безопасно удалить и иметь путь к восстановлению.

## 5. Routing Rules

### Keep in Bot

- capture
- `/start`
- `/status`
- `/find` как quick preview
- `/summary` как short answer
- single retry
- small delete

### Move to Mini App

- advanced search
- note reading and detail view
- jobs triage
- bulk delete and restore
- settings
- длинные multi-step сценарии

### Routing Principle

- `simple / short / single-step -> Bot`
- `multi-result / multi-step / destructive / batch -> Mini App`

## 6. Scope v1

### P0

#### 1. Bot v2

- компактный `/start`
- тихое подтверждение intake
- компактный `/status`
- `/find` возвращает top results + CTA в app
- `/summary` возвращает короткий grounded answer + sources + CTA
- понятные error/retry ответы
- deep-link в конкретный экран Mini App

#### 2. Mini App v1

- `Search`
- `Note Detail`
- `Jobs`
- `Delete/Restore`
- без KPI-wall
- без перегруженного dashboard

#### 3. Trust Layer

- safe delete / soft delete
- undo / restore
- quality guardrails для summary/search
- понятная taxonomy ошибок
- tenant-safe routing

### P1

- weekly review lite
- saved views lite
- quick templates in bot

### Explicitly Out of Scope for v1

- tinder review
- topic clusters
- note health score
- "did you know" insights
- shareable digest
- complex graph features

## 7. Bot UX

### `/start`

- короткий старт
- CTA: сохранить первую заметку
- CTA: открыть app, но не как главный шаг до first value

### `/status`

Показывает только essentials:

- queue state
- failed jobs count
- recent success
- CTA `Open Jobs`

### `/find <query>`

- top-3 результата
- короткий snippet
- primary CTA: `Open advanced search`

### `/summary <query>`

- короткий grounded answer
- обязательные источники
- честный отказ, если контекста недостаточно
- длинные и тяжелые запросы режутся guard'ами

### `/retry <id>`

- single-job recovery
- если проблема сложная, CTA в `Jobs`

### `/delete`

- small delete допустим в боте
- bulk delete только через Mini App

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
- без KPI-перегруза

### `Search`

- query
- basic filters
- results
- open note

### `Note Detail`

- title/meta
- summary
- source/original
- related notes только если это дешево и качественно

### `Activity`

- jobs
- retry history
- delete/restore history

### `Settings`

- не отдельный bottom tab
- drawer или sheet

## 9. Analytics

### North Star

`Weekly Successful Knowledge Tasks`

Определение:

- уникальный пользователь за 7 дней сделал `capture`
- затем `successful retrieval` или `accepted summary`

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

- команды не превращаются в длинные простыни
- любой длинный ответ имеет app CTA
- `/find` и `/summary` не ломают chat UX
- все ошибки user-readable

### Mini App

- Search открывается с prefilled context из бота
- Note Detail открывается по deep-link без потери контекста
- Jobs показывает actionable status, а не raw internals
- delete/restore работает атомарно

### Quality

- summary без sources не показывается как уверенный ответ
- query latency остается в разумном пределе
- tenant leakage = 0
- destructive actions audit-логируются

## 11. Roadmap

### Week 1

- deep-link infra
- `/start` v2
- `/status` v2
- telemetry skeleton
- command cleanup

### Weeks 2-4

- Mini App: Search, Note Detail, Activity/Jobs basic
- `/find` hybrid flow
- `/summary` hybrid flow
- safe delete basic
- citations and quality gates

### Weeks 5-8

- recovery UX hardening
- saved views lite
- weekly review lite
- ranking/search improvements

### Weeks 9-12

- onboarding experiments
- migration optimization bot -> app
- first monetization hypothesis test

## 12. What To Cut Now

До отдельного решения не брать:

- clusters
- swipe review
- note health
- insight cards
- heavy dashboard metrics
- export/share flows

## 13. Final Product Thesis

Самая сильная версия продукта на текущем этапе:

- не "умный бот"
- не "еще один second-brain app"
- а `reliable capture + fast retrieval + safe operations`
