# Критический анализ Product Blueprint: Telegram Bot → Mini App

> **Документ для команды разработки** | Дата: 2026-03-05 | Статус: Pre-PRD Critique

---

## 1. Executive Assessment

| Ось                               | Оценка | Обоснование                                                                                                                                                                                                                                                                                                                               |
| :-------------------------------- | :----: | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Product Clarity**               |  6/10  | Стратегия "бот = input, app = output" — хорошая ментальная модель. Но KPI не связаны между собой в единую систему: цель "60% DAU открывают MA" и цель "снижение ошибок команд до 3%" — разные уровни амбиции и никак не подкреплены аудиторным baseline. Segment matrix не имеет весовых оценок: непонятно, кого строим в первую очередь. |
| **User Value**                    |  7/10  | JTBD #1 (Capture) и #2 (Retrieve) сильные. JTBD #5 (Recover) — нишевый, его не должно быть в топ-5. Silent Append реально ценен. Tinder-Review — рискованная ставка на «геймификацию беспорядка», ценность спорна.                                                                                                                        |
| **UX Quality**                    |  5/10  | Onboarding flow продуман, но содержит ловушку: "✅ Сохранено" может прийти через 30+ сек (если парсинг YouTube медленный). Сценарий Recovery открывает модалку с техническим текстом — не про пользователя. Daily flow целиком зависит от Reply Keyboard, которая не работает при открытом Mini App. Много "UX ping-pong".                |
| **Technical Feasibility**         |  5/10  | `initDataUnsafe` — небезопасная точка входа, должна быть `initData` с валидацией HMAC (критично). WebSocket для 2-3 человек в команде на Week 5 — переоценка. «Semantic Search» заявлен как P0 без упоминания наличия/отсутствия Vector DB. Ни слова о текущем стеке — все на assumptions.                                                |
| **Operational Readiness**         |  4/10  | Нет runbook'ов для инцидентов. Нет staging/production pipeline. Monitoring описан в 1 колонку таблицы безопасности. Нет on-call политики. Нет описания деплоя Mini App (webhook vs polling у бота). SLA на парсинг не определён.                                                                                                          |
| **Growth/Monetization Potential** |  5/10  | Blueprint не содержит ни слова о монетизации. Daily Briefing как Retention hook — верно, но нет пути от retention к revenue. Нет freemium/premium разделения. "Assumption": продукт — это личный инструмент, монетизация вторична.                                                                                                        |

---

## 2. Structural Consistency Check

| Conflict ID | Где найдено                              | В чем конфликт                                                                                                                                                                         | Риск     | Как исправить                                                                                    |
| :---------- | :--------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------- | :----------------------------------------------------------------------------------------------- |
| **C-01**    | Goals vs Features                        | Goal #1: "60% DAU открывают MA" — но ни одна P0-фича напрямую не создает ежедневный повод заходить в MA. Silent Append убирает feedback-loop бота без замены.                          | HIGH     | Добавить "Daily hook" (Briefing) в P0, убрать из P1. Без этого цель недостижима в 90 дней.       |
| **C-02**    | Features vs Roadmap                      | Fич #4 "Active Jobs & Queue UI" помечена P0 в Feature Matrix, но в Roadmap попадает в Weeks 5-8.                                                                                       | HIGH     | Либо Queue UI → в Weeks 2-4 (рядом с Dashboard), либо снизить приоритет до P2 в Feature Matrix.  |
| **C-03**    | UX Flows vs Analytics                    | Flow B (Daily) говорит о Reply Keyboard "📲 Моя база" — но в event schema нет события `bot_keyboard_button_clicked`. Не знаем, работает ли этот channel.                               | MEDIUM   | Добавить события `bot_keyboard_tap` и `miniapp_opened_from_keyboard`.                            |
| **C-04**    | Security vs UX                           | Security: "soft delete, Undo 5 сек". UX Flow D: "Кнопки: [Попробовать как простой текст] [Удалить задание]". Немедленное удаление задачи (Job) без Undo противоречит security-решению. | MEDIUM   | Применить Soft Delete + Undo ко всем destructive actions, включая Job Deletion.                  |
| **C-05**    | Bot/Mini App split vs Execution          | 3 из 4 P0-фич — Mini App. Но в Week 1 заложен только "skeleton" MA. Это значит P0 MVP не появится раньше Weeks 2-4 в лучшем случае. Week 1 не даёт value пользователю.                 | HIGH     | Переосмыслить: Week 1 должен быть Bot-heavy (Silent Append + улучшенные команды). MA — с Week 2. |
| **C-06**    | Analytics vs North Star                  | NSM = "Successful Retrieval Rate", но в event schema нет события `original_url_opened` (переход по исходной ссылке). Без него NSM неизмерим.                                           | HIGH     | Добавить `original_url_opened` как primary value signal.                                         |
| **C-07**    | initDataUnsafe (Security vs Feasibility) | Roadmap Week 1 ставит `initDataUnsafe` как авторизацию. Это уязвимость (нет верификации HMAC).                                                                                         | CRITICAL | Заменить на валидацию `initData` через HMAC-SHA256 на сервере. Это блокер для production.        |
| **C-08**    | "60% DAU in Mini App" vs user base       | Baseline DAU бота неизвестен. Если DAU = 50 человек, цель бессмысленна как KPI.                                                                                                        | MEDIUM   | Зафиксировать минимальный target для абсолютных чисел, не только % (e.g., min 200 MAU).          |

---

## 3. Feature Quality Review

| Feature                       | Value Score | Complexity Risk | Hidden Dependency                                                                             | Cut/Keep/Delay          | Why                                                                                                     |
| :---------------------------- | :---------: | :-------------- | :-------------------------------------------------------------------------------------------- | :---------------------- | :------------------------------------------------------------------------------------------------------ |
| 1. Quick Append (Silent)      |     5/5     | LOW             | Bot message editing API limits (Telegram: 48h edit window)                                    | **KEEP (P0)**           | Самая дешевая по effort, самая высокая по user satisfaction. Первое, что нужно сделать.                 |
| 2. Global Semantic Search     |     4/5     | HIGH            | Vector DB (pgvector/Qdrant/Weaviate) уже должна быть. Embeddings pipeline должен работать.    | **KEEP, Scope Cut**     | v1: только keyword + basic filter. Semantic — с Week 5. Иначе риск заблокировать Launch.                |
| 3. Native Article Reader      |     3/5     | LOW             | Requires clean text extraction (html → readable). Может не работать для PDF/paywall.          | **KEEP (v1 с caveats)** | Показывать AI Summary + ссылку. Full text — только если он уже есть в базе. Не парсить заново.          |
| 4. Active Jobs & Queue UI     |     3/5     | MEDIUM          | WebSocket или SSE на бэкенде. Polling проще, но хуже UX.                                      | **DELAY to W5**         | Для v1 достаточно: бот пушит "Jobs done". UI очереди не нужен, пока Job Error Rate неизвестен.          |
| 5. Magic `/find` shortcut     |     3/5     | LOW             | Зависит от качества текстового поиска.                                                        | **KEEP (P1)**           | Легко сделать. Конвертация из bot-only в hybrid.                                                        |
| 6. Tinder-style Review        |     3/5     | HIGH            | Требует swipe-геста, анимации, mobile-first CSS. Много edge-cases (отмена серии свайпов).     | **DELAY to W9+**        | Ценность только для Hoarders с 100+ заметок. Маленькая аудитория. Сложно тестировать.                   |
| 7. AI Briefing Digest         |     5/5     | HIGH            | Регулярный LLM-вызов = стоимость. Нужен планировщик (cron), локальный TZ юзера, токен-бюджет. | **KEEP, MVP Scope Cut** | v1: генерировать 1×в день batch-запросом для всех юзеров, отправлять текстом в бот. MA-версия — Week 9. |
| 8. Bulk Delete Dashboard      |     2/5     | MEDIUM          | Multi-select UI — нетривиальная задача для Touch-интерфейса.                                  | **DELAY to W9**         | Проблема актуальна только при большом накоплении. Решить через Tinder Review позже.                     |
| 9. One-tap Visual Retry       |     4/5     | LOW             | Уже есть в Recovery flow через Inline кнопки бота.                                            | **KEEP как Bot-фича**   | В MA это дублирование. Retry через бот = быстрее. MA — только если нужен контекст ошибки.               |
| 10. Semantic Clusters Views   |     2/5     | VERY HIGH       | Clustering требует постобработки эмбеддингов (k-means/HDBSCAN), хранения cluster labels, UI.  | **CUT из v1**           | Исследовательская фича. Для маленькой команды — непозволительная роскошь в 12 недель.                   |
| 11. Recycle Bin (Soft Delete) |     5/5     | LOW             | Флаг в БД + крон. Просто, но критично для user trust.                                         | **KEEP (P0, W2)**       | Без этого нельзя выпускать Delete в MA.                                                                 |
| 12. Source Type Facet Filters |     4/5     | LOW             | Мета-поле `content_type` должно быть в каждой записи.                                         | **KEEP (v1)**           | Решает ключевой pain Researcher'а.                                                                      |
| 13. Insight "Did you know?"   |     1/5     | MEDIUM          | Требует логики выбора "интересных" фактов. Может раздражать.                                  | **CUT**                 | Vanity feature без четкого JTBD.                                                                        |
| 14. Note Health Score         |     1/5     | HIGH            | Непонятно, что это такое. Прокси каких метрик?                                                | **CUT**                 | Нет пользователя, который спрашивал об этом.                                                            |
| 15. Multi-selection Export    |     1/5     | MEDIUM          | В какой формат? Куда? Нет ответа на базовые вопросы.                                          | **CUT**                 | Преждевременная фича.                                                                                   |

---

## 4. Bot vs Mini App Migration Audit

### Что правильно оставлено в Bot

- Ingestion (ссылки, файлы, текст) — абсолютно верно. Бот = самый быстрый I/O.
- Пуш-уведомления (Job done, Briefing ready) — верно. Telegram бот отлично справляется с push.
- Команды как быстрые shortcuts (`/status`, `/find` top-1) — верно.

### Что точно надо унести в Mini App

- Browse/Read заметок — сейчас в боте неудобно, перенос критичен.
- Управление ошибками Jobs (с объяснением, что произошло и почему) — контекст требует UI.
- Настройки аккаунта и предпочтений — не должны быть в чате.
- Delete / Bulk управление контентом — опасно и неудобно в текстовом интерфейсе.

### UX Ping-Pong (проблемные точки)

1. **Recovery flow:** Бот → [Кнопка починить] → MA модалка → [Done] → где пользователь? Он в MA без контекста. Нет "Back to Bot" или четкого следующего шага.
2. **Daily user:** Reply Keyboard "📲 Моя база" → MA (Search). Но если пользователь УЖЕ в MA, Reply Keyboard недоступна. Дублирование навигационной логики.
3. **Power-user:** Отправил 10 файлов → открыл Jobs в MA → файлы обработаны → бот присылает пуш в чат. Пользователь снова переключается в бот, потом обратно в MA. Минимум 3 переключения контекста.

### Правила маршрутизации (обязательные к фиксации в PRD)

| Сценарий                                   | Routing                                                                                     | Implementation                                |
| :----------------------------------------- | :------------------------------------------------------------------------------------------ | :-------------------------------------------- |
| Пользователь отправляет ссылку/файл/текст  | → **Bot** (тихая обработка, реакция/ack)                                                    | Без исключений                                |
| Пользователь хочет найти что-то конкретное | → **Hybrid** (Bot /find = top-1 preview) → MA (полная выдача)                               | Bot inline кнопка с query param               |
| Пользователь хочет читать заметку          | → **Mini App** (напрямую, по deep link)                                                     | `tg://resolve?domain=botname&start=note_UUID` |
| Уведомление о завершении Job               | → **Bot** (push) → MA (опционально, кнопка)                                                 | Только если юзер хотел следить                |
| Ошибка парсинга с контекстом               | → **Bot** (короткое уведомление) + кнопка → **MA** (полный контекст ошибки + retry options) |                                               |
| Массовое управление (delete/archive)       | → **Mini App** (только)                                                                     | Никаких команд `/delete` в чате               |
| Просмотр статуса системы                   | → **Bot** `/status` (quick)                                                                 | MA — только если нужна детализация            |
| Настройки                                  | → **Mini App** (только)                                                                     |                                               |

---

## 5. UX Critique

### A) Onboarding Flow

**Проблема #1:** "✅ Сохранено и проанализировано!" через 3 сек — нереалистично для YouTube. Реальный парсинг видео = 15–90 сек. Пользователь видит "⏳ Парсю..." и уходит. Ожидаемая конверсия в кнопку Mini App — низкая.

**Проблема #2:** "📲 Открыть мою базу (Mini App)" после первой сохраненной вещи — слишком рано. Dashboard пустой по сути (1 карточка). First impression — разочарование.

**Проблема #3:** Onboarding не обучает Share Extension (самый ценный способ ввода). Пользователь думает, что нужно вставлять ссылки вручную в Telegram.

**Улучшенный /start copy:**

```
👋 Привет! Ты только что открыл свой AI-архив знаний.

Просто пересылай сюда статьи, видео, PDF — я сохраню главное.
Потом найдешь всё по смыслу, а не по ключевым словам.

👇 Скинь любую ссылку, чтобы начать.
```

_(Убраны: "Спойлер", "полноэкранный интерфейс" — отвлекают от core JTBD)_

**Фикс onboarding race condition:**

- После отправки ссылки → бот сразу: "⚡️ Получил! Обрабатываю в фоне, это займёт ~30 сек."
- По завершению → бот ЗАМЕНЯЕТ сообщение (edit), добавляет кнопку MA.
- Кнопку MA показывать только когда есть минимум 1 готовая запись.

**Шаги, которые можно убрать из onboarding:** "Спойлер про интерфейс" в /start — шум до получения ценности.

### B) Daily Flow

**Проблема:** Reply Keyboard с "📲 Моя база" занимает экран и мешает вводу ссылок. В Telegram Reply Keyboard перекрывает поле ввода — неудобно.

**Фикс:** Использовать Menu Button (кнопка рядом с полем ввода, нативный TG элемент) вместо Reply Keyboard. Это постоянно видимый entrypoint в MA без захламления чата.

### C) Power-user Flow

**Проблема:** "Следить за прогрессом в MA" предполагает, что пользователь держит MA открытым. Telegram закрывает MA при сворачивании. Polling/WS соединение рвется. Пользователь возвращается в пустой или устаревший UI.

**Фикс:** Основной delivery механизм — пуш от бота ("✅ 10/10 готово"). MA Jobs view — только для любопытных, которые сами открыли.

**Улучшенный copy для Heavy Jobs:**

```
📦 10 файлов приняты. Ставлю в очередь.
Когда всё будет готово — напишу сюда.
```

_(Убрана кнопка MA — не нужна, если бот сам уведомит)_

### D) Recovery Flow

**Проблема:** "Текст ошибки: Сайт требует капчу или это PDF больше 50мб" — технический язык, пользователь не понимает, что делать.

**Улучшенный copy:**

```
⚠️ Не смог обработать эту ссылку.

Причина: сайт блокирует автоматическое чтение (paywall).

Что сделать:
```

- Кнопки: [Сохранить без анализа] [Удалить] [Попробовать позже]

**Кнопка [Починить] → MA модалка** — лишний переход. Три действия выше можно сделать прямо в боте через inline кнопки без открытия MA.

### E) Delete Flow

**Проблема:** Undo-кнопка в Telegram inline keyboard disappears после рестарта приложения или прокрутки вверх. Если пользователь случайно удалил из бота — нет визуального Undo (только в MA).

**Фикс:** `/delete {id}` в боте → снабдить ответ временной inline кнопкой [↩️ Отменить (30 дней)], которая ведет в MA на экран корзины. Undo через бот не нужен — soft delete дает 30 дней.

---

## 6. UI/IA Critique (Mini App)

| Current IA Issue                                                          | Better IA Decision                                                                                                                        | Why                                                                                                      |
| :------------------------------------------------------------------------ | :---------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------- |
| 4 вкладки в bottom nav: Home, Search, Queue, Settings                     | 3 вкладки: **Feed** (Home+Briefing), **Search**, **Settings**. Queue — внутри Feed или Settings, не таб.                                  | Queue нужна только при наличии активных/сломанных job'ов. Занимает постоянное место для редкого события. |
| Dashboard: Hero "Daily Briefing" первым экраном при НУЛЕВОЙ базе          | Адаптивный Hero: если < 5 заметок → онбординг-баннер "Добавь 5 вещей, и я начну строить твой брифинг". Если > 5 → Briefing.               | Пустой Briefing = разочарование. Прогрессивное раскрытие фичей.                                          |
| Filter chips: [All][Videos][Articles][Notes][Last 7 days] на одной строке | Разделить: Тип-фильтры (Videos/Articles) и Время-фильтры (7d/30d/All time) — в разные строки или dropdown                                 | Смешение типов и времени на одной строке — плохая IA.                                                    |
| Note Detail: "Related notes" внизу (Section 3)                            | Вынести "Related notes" в отдельный коллапсируемый блок или убрать из v1.                                                                 | Для v1 требует Semantic Search. Если latency высокий — блок будет тупить и тянуть весь экран.            |
| Jobs Screen: "Active Processes" как полноценный экран                     | В v1 сделать Jobs Badge на кнопке Settings (число ошибок). При клике → модальный bottom sheet, не полный экран.                           | Экономит один таб в nav. Полноэкранный Jobs View — только если Job Error Rate > 5%.                      |
| Settings Screen: не описан совсем                                         | Обязательно включить: Notification preferences (Briefing on/off, время), Account info (TG ID), Data export (скачать всё), Delete account. | Без этого нельзя запускаться — GDPR/базовые ожидания пользователя.                                       |
| Empty state: "Красивая иллюстрация"                                       | Конкретный empty state: 3-шаговый checklist "Что сделать сейчас: 1) Добавь ссылку 2) Найди что-нибудь 3) Открой Daily Brief".             | Иллюстрация без действия ничего не конвертирует.                                                         |
| Loading State: не описан для Dashboard                                    | Dashboard: вместо full-skeleton — показывать стейтлесс Header + skeleton только для card list.                                            | Частичный рендер = ощущение быстрого отклика.                                                            |

---

## 7. Metrics & Analytics Audit

### Проблемы текущего North Star

**Текущий NSM:** "Успешный Retrieval Rate" — правильная идея, но:

- "Чтение > 15 секунд" не говорит о ценности (пользователь мог уйти от телефона).
- "Копирование текста" — не отслеживается нативно в WebView.
- "Клик по URL из заметки" — ближайший к реальной ценности сигнал, но и он косвенный.

**Пересмотренный NSM:**

> **Weekly Active Retrievers (WAR)** = кол-во уникальных пользователей, выполнивших хотя бы 1 действие поиска или просмотра в MA за 7 дней, с успешным переходом на исходный источник (`original_url_opened`) ИЛИ просмотром > 30 сек.

_Почему лучше:_ Недельная частота ближе к реальному поведению "сохранил в пятницу, открыл в понедельник". Переход на источник — сильнейший сигнал ценности.

### Vanity Metrics в текущем плане

| Vanity Metric (из blueprint)                      | Почему vanity                    | Замена на actionable                                     |
| :------------------------------------------------ | :------------------------------- | :------------------------------------------------------- |
| "Open rate утреннего push-уведомления" (Briefing) | Открыл ≠ получил ценность        | `briefing_note_clicked` (перешел к заметке из брифинга)  |
| "% DAU открывают MA" как Goal                     | Открыть ≠ использовать           | `miniapp_dau_with_interaction` (% с хотя бы 1 действием) |
| "Кол-во очищенных заметок в день" (Tinder Review) | Может быть bulk-свайп без чтения | `notes_reviewed_before_delete` (кол-во с view > 5 сек)   |

### Недостающие события (критичные)

| Отсутствующее событие                   | Почему критично                              |
| :-------------------------------------- | :------------------------------------------- |
| `original_url_opened`                   | Без этого NSM не измерить                    |
| `note_parse_completed` (+ latency)      | Нет данных о SLA парсинга                    |
| `note_parse_failed` (+ reason category) | Нельзя приоритизировать типы ошибок          |
| `bot_keyboard_tap`                      | Нет данных о работе основного CTA            |
| `miniapp_cold_start_time_ms`            | Нет данных о Performance (guardrail метрика) |
| `search_zero_results`                   | Сигнал о качестве индекса                    |
| `settings_notification_changed`         | Нет данных о блокировке Briefing             |
| `user_blocked_bot`                      | Самый важный churn signal                    |

### 3 Decision Dashboards

**Dashboard 1: "Retrieval Health" (ежедневный)**

- Метрики: WAR (Weekly Active Retrievers), % поисков с кликом, `search_zero_results` rate, top-10 запросов без результата.
- Решение: Если zero-results > 20% → срочно улучшить индекс или подсказки.

**Dashboard 2: "Ingestion Pipeline" (реал-тайм)**

- Метрики: Jobs in queue, % failed jobs (по типу: url/pdf/text), p95 parse time, rate-limit hits.
- Решение: Если failed jobs > 10% за 1 день → freeze new campaign, чинить парсер.

**Dashboard 3: "Mini App Adoption" (еженедельный)**

- Метрики: MA открытия по source (inline_button / menu_button / direct), bounce < 5 сек, miniapp_dau_with_interaction, cold_start_time_ms p95.
- Решение: Если bounce > 40% → проблема с производительностью или IA первого экрана.

---

## 8. Security & Abuse Readiness

| Risk                                                | Severity | Likelihood | Gap in Blueprint                                                                                                      | Required Control Before Launch                                                                                             |
| :-------------------------------------------------- | :------: | :--------: | :-------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------- |
| **`initDataUnsafe` без HMAC-валидации**             | CRITICAL |    HIGH    | Blueprint прямо рекомендует `initDataUnsafe`. Это означает, что любой может подделать userId и получить чужие данные. | Обязательная серверная валидация `initData` через HMAC-SHA256 с Bot Token. Без этого — НЕ ЗАПУСКАТЬ.                       |
| **SSRF через URL парсинг**                          |   HIGH   |   MEDIUM   | В blueprint упомянут "SSRF защита" как намерение. Реализация не описана.                                              | IP allowlist (запрет 169.254.x.x, 10.x.x.x, 127.x.x.x). Timeout 10 сек. Domain blacklist. Headless browser only в sandbox. |
| **Хранение Bot Token в коде**                       |   HIGH   |   MEDIUM   | Blueprint не касается этого. Assumption: токен может быть в env файле без rotation policy.                            | Secrets Manager (Vault / AWS SSM). Ротация токена после каждого security incident.                                         |
| **Rate Limit отсутствует на API MA**                |   HIGH   |    HIGH    | Blueprint говорит "Rate-limiting" как намерение. Конкретики нет.                                                      | Redis token bucket: 60 req/min на search, 10 req/min на /delete, 5 req/min на job submission.                              |
| **Soft Delete — физическое удаление через 30 дней** |  MEDIUM  |    LOW     | Описано верно. Gap: нет cron job spec, нет audit log удаления.                                                        | Audit log в БД (`deletion_audit` table). Cron + dead man's switch alert.                                                   |
| **XSS в Note Content**                              |   HIGH   |   MEDIUM   | Не упомянуто. Хранимый HTML из парсинга (если есть) может содержать скрипты.                                          | Sanitize all stored content (DOMPurify на фронте, bleach на бэке). Хранить только plain text + структурированный JSON.     |
| **Multi-tenant через Telegram Group**               |  MEDIUM  |    LOW     | Blueprint не рассматривает сценарий бота в группе (Assumption: только личные чаты).                                   | Явно ограничить бота до private chats. Добавить check на `chat.type == 'private'`.                                         |
| **Replay Attack на Briefing Push**                  |   LOW    |    LOW     | Не рассмотрен.                                                                                                        | Добавить `nonce` к каждому push-кнопке. Istance expiry для inline buttons (Telegram: 48h).                                 |

---

## 9. Delivery Realism

### Что нереалистично в текущем Roadmap

| Элемент                                                          | Проблема                                                                | Решение                                                                              |
| :--------------------------------------------------------------- | :---------------------------------------------------------------------- | :----------------------------------------------------------------------------------- |
| Week 1: "настройка CI/CD + React + SDK + авторизация"            | Это 2–3 недели для нормальной настройки, не 1.                          | W1 = только Bot fixes. MA skeleton — конец W2.                                       |
| Weeks 2-4: Dashboard + Search + Detail + API + Auth + Bot кнопки | Слишком широко. 3 экрана + полноценный API за 3 недели для 2-3 человек. | Scope cut: W2-4 = только 1 экран (Search/List) + API auth. Dashboard — W5.           |
| Weeks 5-8: WebSocket для Jobs                                    | WebSocket требует persistent connection, серверного state management.   | Заменить на Server-Sent Events или Polling (5 сек интервал). WS — после v1 стабилен. |
| Weeks 9-12: Tinder Review + Briefing Backend + Push кампании     | Три разных сложных фичи за 4 недели + стабилизация.                     | Выбрать одно: либо Tinder Review, либо Briefing. Не оба.                             |

### Пересмотренный Pragmatic Roadmap

**Week 1 — "Bot Hygiene" (только бот, 0 MA)**

- Scope: Silent Append (emoji reaction / edit msg), переписать копи всех команд, добавить Menu Button (MA entrypoint).
- Dependencies: Текущий бот-стек готов, нужно только изменение handlers.
- Deliverables: `/start` новый копи, Silent Append работает, `/find` → top-1 + кнопка.
- Acceptance Criteria: Бот не отправляет новых сообщений при каждой ссылке (только edit); `/status` возвращает ≤ 2 строки текста.

**Weeks 2-4 — "MA v0.1: List + Auth" (MVP шасси)**

- Scope: TG Web App SDK init, HMAC initData валидация на сервере, API Auth middleware, Notes List экран (только список с basic info), Note Detail (только AI Summary + оригинальная ссылка), Soft Delete + Undo 30 дней.
- Dependencies: Готовые API endpoints с user-scoped queries. CI/CD на Vercel.
- Deliverables: Рабочий MA, доступный через Menu Button. Пользователь видит свои заметки. Может удалить с Undo.
- Acceptance Criteria: Cold start MA < 2 сек. Авторизованный запрос возвращает только записи текущего пользователя. `/delete` превращается в soft delete.

**Weeks 5-8 — "MA v1: Search + Polish"**

- Scope: Search экран (keyword, filters по типу), Source Type filters, Bot inline-кнопки с query params (e.g., открыть MA на поиске), Jobs bottom sheet (простой polling 5 сек), Performance audit (bundle size, lazy loading).
- Dependencies: Search API (keyword first, semantic — опционально если уже есть).
- Deliverables: Полноценный поиск работает. Пользователь может найти заметку из MA за < 10 сек. Jobs ошибки видны.
- Acceptance Criteria: Search с результатами работает. p95 поиска < 1.5 сек. MA Bounce rate < 35%.

**Weeks 9-12 — "Retention Engine"**

- Scope: AI Briefing v1 (генерация 1×день, доставка в бот текстом + кнопка в MA), Briefing экран в MA (список инсайтов из Briefing), Settings экран (управление уведомлениями). Tinder Review — только если Briefing работает и есть время.
- Dependencies: LLM budget approved. Cron scheduler. User timezone хранится.
- Deliverables: Ежедневный Briefing пуш работает. Настройки уведомлений доступны.
- Acceptance Criteria: Briefing → MA click-through rate > 25%. Opt-out rate по Briefing < 20%.

---

## 10. Final Verdict

### Вердикт: `GO with conditions`

Blueprint содержит правильную стратегическую идею (bot = input layer, MA = UX layer), достаточно проработанные JTBD и разумную feature matrix. Однако в текущем виде он не готов к старту реализации из-за критических пробелов в безопасности, нереалистичного Roadmap и нескольких структурных несостыковок.

### Топ-12 обязательных правок перед startом разработки

| #   | Правка                                                                                             | Приоритет | Владелец  |
| :-- | :------------------------------------------------------------------------------------------------- | :-------- | :-------- |
| 1   | **КРИТИЧНО:** Заменить `initDataUnsafe` на HMAC-SHA256 валидацию `initData`                        | P0        | Backend   |
| 2   | Добавить `original_url_opened` в event schema как primary value signal                             | P0        | Analytics |
| 3   | Синхронизировать Feature Matrix с Roadmap: Jobs UI P0 → P2 или перенести в Weeks 2-4               | P0        | PM        |
| 4   | Добавить "Daily Briefing LITE" (текстовый пуш в бот, без MA-экрана) в Week 9 scope                 | P0        | PM        |
| 5   | Исправить Onboarding: убрать "✅ за 3 сек", добавить честное "⚡️ Обрабатываю, напишу когда готово" | P0        | Bot Dev   |
| 6   | Описать Settings screen в IA: уведомления, user data, delete account                               | P0        | Design    |
| 7   | Заменить Reply Keyboard "📲 Моя база" на нативный Menu Button                                      | P1        | Bot Dev   |
| 8   | Добавить SSRF protection spec в Build Plan (IP blocklist, timeout, sandbox)                        | P1        | Backend   |
| 9   | Зафиксировать правила маршрутизации Bot/MA как Architecture Decision Record (ADR)                  | P1        | Tech Lead |
| 10  | Scope cut Week 2-4: убрать Dashboard, оставить только List + Detail + Search + Auth                | P1        | PM        |
| 11  | Заменить NSM с "Retrieval Rate" на "Weekly Active Retrievers (WAR)"                                | P1        | Analytics |
| 12  | Добавить Rate Limiting spec: endpoint-level limits (req/min per user)                              | P1        | Backend   |

### Revised Top 3 Bets

Текущие "3 ставки" в blueprint правильные по сути, но **AI Briefing Digest** требует переноса ставки:

1. **Silent Append (Bot Hygiene)** — **оставить**. Дешево, высокий impact. Первый шаг.
2. **Semantic Search в MA** — **оставить, но scope cut**: начать с keyword + filter. Semantic — только если уже есть vector pipeline. Не строить с нуля ради MA launch.
3. **Revised Bet #3 → "Instant Link to Note" Deep Link System** (вместо AI Briefing Digest): прямая ссылка `tg://resolve?domain=bot&start=note_UUID` из любого пуша бота напрямую открывает нужную заметку в MA. Это убивает сразу все UX-проблемы ping-pong и создает habit-loop без LLM-затрат. Briefing — следующая итерация.

### Open Questions (без ответа → PRD нельзя финализировать)

| #   | Вопрос                                                                                               | Blocker? |
| :-- | :--------------------------------------------------------------------------------------------------- | :------- |
| 1   | Какой текущий бэкенд-стек (язык, DB, ORM)? Есть ли PostgreSQL с pgvector?                            | YES      |
| 2   | Есть ли уже работающий Pipeline для эмбеддингов/семантического поиска?                               | YES      |
| 3   | Какой текущий DAU/MAU бота (для baseline KPI)?                                                       | YES      |
| 4   | Как деплоится бот сейчас: polling или webhook?                                                       | YES      |
| 5   | Есть ли бюджет на LLM API (оценка: $X/1000 юзеров/день)?                                             | YES      |
| 6   | Каков median и p95 latency парсинга ссылок и PDF сейчас?                                             | YES      |
| 7   | Job Error Rate сейчас: % от всех submitted заданий?                                                  | YES      |
| 8   | Используется ли Multi-tenancy (несколько пользователей) или продукт пока личный/для одного?          | YES      |
| 9   | Есть ли данные о том, какой % пользователей использует iOS Share Extension vs. ручная вставка?       | NO       |
| 10  | Есть ли требования к GDPR / right-to-be-forgotten? (влияет на soft delete срок и export)             | YES      |
| 11  | Планируется ли монетизация в 12-недельном горизонте? Какая модель?                                   | NO       |
| 12  | Есть ли SLA по uptime у текущего бота? Какой downtime был за последние 30 дней?                      | NO       |
| 13  | Какая ОС/устройство у большинства пользователей (iOS/Android) — влияет на MA CSS/gesture приоритеты? | NO       |
| 14  | Планируется ли регистрация бота как Mini App в BotFather до старта разработки?                       | YES      |
| 15  | Есть ли флаг для A/B тестирования (Feature flags system) или тестируем на всех сразу?                | NO       |
