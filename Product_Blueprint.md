# Детальный продуктовый blueprint перехода Telegram-бота в гибридный формат с Mini App

Данный документ составлен с точки зрения максимальной прагматичности, реалистичности для небольшой команды и фокуса на измеримый результат.

---

## 1. Product Strategy

### 3 Product Goals на 90 дней

| Goal                                       | KPI                                                                | Baseline (Assumption)    | Target 90d       |
| :----------------------------------------- | :----------------------------------------------------------------- | :----------------------- | :--------------- |
| **Успешная миграция аудитории**            | % DAU бота, которые хотя бы 1 раз в день открывают Mini App        | 0%                       | > 60%            |
| **Углубление взаимодействия (Engagement)** | Среднее кол-во просмотренных сущностей (заметок/саммари) за сессию | 1.2 (через команды бота) | 3.5 (в Mini App) |
| **Снижение фрустрации от интерфейса**      | % команд с ошибками синтаксиса или пустым результатом              | 15%                      | < 3%             |

### 5 ключевых Jobs-To-Be-Done

1. **[Capture]** Когда я бегу по своим делам, я хочу закинуть ссылку/текст в одно место за 1 секунду, чтобы мой мозг освободился, зная, что информация надежно сохранена.
2. **[Retrieve]** Когда у меня в голове всплывает обрывок воспоминания («что-то про метрики B2B SaaS»), я хочу найти это по смыслу, а не точной цитате, чтобы не тратить время на перебор ключевых слов.
3. **[Consume]** Когда у меня есть 5 свободных минут, я хочу быстро просмотреть выжимку из сохраненного "на потом", чтобы получить пользу без чтения лонгридов.
4. **[Manage]** Когда у меня накапливается "информационный мусор", я хочу массово и быстро разобрать его (удалить/архивировать), чтобы поддерживать чистоту базы.
5. **[Recover]** Когда бот не смог обработать мой тяжелый PDF или защищенную ссылку, я хочу визуально понять причину и нажать кнопку "повторить с другими настройками", чтобы не возиться с консольными командами `/retry`.

### Сегменты пользователей и гибридное позиционирование

**Позиционирование гибрида:** Бот крут для _Input_ (самый быстрый шорткат в мире — `Share -> Telegram -> Bot`). Mini App крут для _Output_ (чтение, навигация, фильтрация).

| Segment                  | Main Pain                                                                                | Bot Role (The "Doer")                                                                 | Mini App Role (The "Viewer")                                                                                   |
| :----------------------- | :--------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------------------------- |
| **Information Hoarder**  | Копит ссылки тысячами, никогда их не читает, испытывает FOMO.                            | "Продвинутый Inbox". Просто принимает пересланные сообщения молча (или с 1 галочкой). | **AI Briefing Feed:** визуализация того, что он накопил, в формате Tinder-карточек или ленты коротких выжимок. |
| **Researcher / Student** | Ищет конкретные факты из ранее сохраненных статей и лекций. Болит от плохого поиска.     | Быстрый "Quick query" через `/find`.                                                  | **Semantic Search Workspace:** Фильтры по дате/тегам, полноэкранная читалка, highlighting.                     |
| **Task / Job Manager**   | Закидывает тяжелые ссылки/документы на парсинг в фоне. Не понимает, когда оно скачается. | Нотификатор. Пушит алерты: "Job #42 finished".                                        | **Jobs/Queue Dashboard:** Прогресс-бары, визуализация ошибок, логи парсинга, кнопки retry.                     |

---

## 2. Feature Matrix (Bot vs Mini App vs Hybrid)

| Feature                         | Placement | Impact | Effort | Priority |
| :------------------------------ | :-------- | :----- | :----- | :------- |
| 1. _Quick Append (Silent)_      | Bot       | 5      | 1      | P0       |
| 2. _Global Semantic Search_     | Mini App  | 5      | 3      | P0       |
| 3. _Native Article Reader_      | Mini App  | 4      | 2      | P0       |
| 4. _Active Jobs & Queue UI_     | Mini App  | 4      | 2      | P0       |
| 5. _Magic `/find` shortcut_     | Hybrid    | 3      | 1      | P1       |
| 6. _Tinder-style Review_        | Mini App  | 4      | 3      | P1       |
| 7. _AI Briefing Digest_         | Hybrid    | 5      | 4      | P1       |
| 8. _Bulk Delete Dashboard_      | Mini App  | 3      | 2      | P1       |
| 9. _One-tap Visual Retry_       | Mini App  | 3      | 2      | P2       |
| 10. _Semantic Clusters Views_   | Mini App  | 4      | 5      | P2       |
| 11. _Recycle Bin (Soft Delete)_ | Mini App  | 2      | 2      | P2       |
| 12. _Source Type Facet Filters_ | Mini App  | 3      | 2      | P2       |
| 13. _Insight "Did you know?"_   | Mini App  | 3      | 3      | P3       |
| 14. _Note Health Score_         | Mini App  | 2      | 3      | P3       |
| 15. _Multi-selection Export_    | Mini App  | 1      | 2      | P3       |

### Детальный разбор ключевых фичей:

**1. Quick Append (Silent)**

- **Problem:** Бот спамит длинными отбивками на каждую присланную ссылку.
- **Value:** Отсутствие шума. Человек отправляет 10 ссылок подряд.
- **Behavior:** Бот реагирует эмодзи-реакцией (👍) или удаляет свое предыдущее сообщение-статус и пишет одно обновленное: "10 items in queue".
- **Risk:** Пользователь не понимает, работает ли бот.
- **Metric:** Удержание (Day 7 Retention) "Hoarders".

**2. Global Semantic Search**

- **Problem:** Команда `/find` в боте возвращает простыню текста, которую неудобно скроллить.
- **Value:** Полноценный интерфейс поиска на весь экран.
- **Behavior:** Выдача как в Google: заголовки, сниппеты с подсветкой, фильтры под строкой поиска.
- **Risk:** Высокий latency (TTFB) при открытии Mini App с фокусом на инпут.
- **Metric:** % успешных поисков (клик на результат после ввода запроса).

**6. Tinder-style Review (Inbox Zero)**

- **Problem:** Накоплено 500+ заметок, разобрать руками команды `/delete` нереально.
- **Value:** Геймификация очистки базы.
- **Behavior:** Свайп вправо = "Оставить в архиве", Свайп влево = "Удалить в корзину", Вверх = "Создать саммари прямо сейчас".
- **Metric:** Кол-во очищенных заметок в день на пользователя.

**7. AI Briefing Digest (Hybrid)**

- **Problem:** Саммари по команде `/summary` оторвано от контекста, не формирует привычку.
- **Value:** Проактивная доставка ценности.
- **Behavior:** В 10:00 (локального времени) бот пушит: "У вас 5 новых статей. Главный инсайт: [1 предложение]. Открыть Daily Brief". По клику открывается красивый Stories-like интерфейс в Mini App.
- **Metric:** Open rate утреннего push-уведомления.

---

## 3. Telegram UX flows

**A) New user onboarding (First value in < 2 min)**

- **Trigger:** Юзер жмет `/start`
- **Bot msg:** "👋 Привет! Я твой AI-помощник для знаний. Перешли мне любую статью, видео или просто текст — я сохраню суть и помогу найти это, когда понадобится. \n\n🎯 _Спойлер: У меня есть удобный полноэкранный интерфейс._ \n\n👇 Отправь мне любую ссылку прямо сейчас."
- **User:** отправляет ссылку на youtube.
- **Bot msg:** (мгновенно) "⏳ Парсю [Название]..." -> (через 3 сек заменяется на) "✅ Сохранено и проанализировано! \n\n👀 _Посмотрим, как это выглядит внутри?_" + Inline-кнопка [🚀 Открыть мою базу (Mini App)]
- **Mini App:** Открывается дашборд с карточкой этого видео и уже сгенерированным коротким summary.
- **"Done" condition:** Пользователь открыл Mini App и кликнул на свою первую карточку.

**B) Daily Active User (The "Drop-and-Go" flow)**

- **Trigger:** Юзер шарит ссылку из Safari/Chrome в Telegram бота.
- **Bot msg:** Бот просто ставит реакцию ⚡️ на сообщение (без текста).
- **Trigger 2:** Юзеру нужно найти что-то сохраненное на прошлой неделе. Он открывает бота.
- **Bot msg:** Внизу всегда висит Reply Keyboard Button "📲 Моя база". Нажимает.
- **Mini App:** Открывается сразу на экране `Search` (фокус в поле ввода).

**C) Power-user flow (Heavy Jobs)**

- **Trigger:** Юзер скидывает архив с 10 документами.
- **Bot msg:** "📦 Принял 10 файлов. Поставил в очередь. Это займет пару минут." + Кнопка [📊 Следить за прогрессом (Mini App)]
- **Mini App:** Открывается вкладка `Jobs`. Юзер видит real-time прогресс бара (3/10 обработано) по WebSocket.
- **"Done":** Бот присылает пуш "✅ Все 10 файлов обработаны", юзер видит их в дашборде.

**D) Recovery flow (Failed Jobs)**

- **Trigger:** Парсинг упал по таймауту.
- **Bot msg:** "⚠️ Не удалось обработать 1 ссылку (paywall или таймаут)." + Кнопка [🛠 Починить (Mini App)]
- **Mini App:** Открывается модалка в приложении. Текст ошибки: "Сайт требует капчу или это PDF больше 50мб". Кнопки: [Попробовать как простой текст] [Удалить задание].
- **"Done":** Юзер переопределил способ загрузки.

**E) “Open Mini App” conversion flow from Bot command**

- **Trigger:** Юзер по старой памяти пишет `/find metrics`.
- **Bot msg:** Бот выдает 3 лучших результата текстом:
  "1. _SaaS Metrics 2024_ (Score: 0.9) - ... 2. _Product Analytics_ (Score: 0.8) - ... 3. ..."
  - Inline кнопка: [🔍 Смотреть все 14 результатов красиво (Mini App)] с передачей в Web App Data query string `?q=metrics`.
- **Mini App:** Открывается с предзаполненным поиском и красивой выдачей.

---

## 4. Mini App IA + UI Spec (v1)

**Navigation Model:** Топ-бар меняется по контексту. Bottom Tab Bar: `[ 🏠 Home ]` `[ 🔍 Search ]` `[ ⚡️ Queue (2) ]` `[ ⚙️ Settings ]`.

**`Screen: Dashboard (Home)`**

- _Top bar:_ Приветствие (Good morning, Alex), кнопка фильтра.
- _Section 1 (Hero):_ Карточка "Daily Briefing" (Сгенерированные итоги за 24ч).
  - _Primary CTA:_ "Read 3 mins"
- _Section 2:_ Скролл-лента (Latest Adds).
  - _Cards:_ Title, Domain tag (youtube, medium), 2 строки summary-сниппета, Time-ago, Status badge (✅, ⏳, 🔴).
- _Empty state:_ Красивая иллюстрация и кнопка "How to add notes?".
- _Data required:_ `/api/v1/feed?limit=10`, `/api/v1/briefings/latest`.

**`Screen: Search`**

- _Top bar:_ Липкий Search Input (нативный, полноширинный).
- _Filter row:_ Horizontal scroll chips: `[All]` `[Videos]` `[Articles]` `[Notes]` `[Last 7 days]`.
- _UI Blocks:_
  - Если query пустой -> "Recent Searches", "Semantic suggestions".
  - Если query введен -> Список результатов. Каждый с "Highlight match contexts".
- _Loading State:_ Skeleton loader (3 мерцающие карточки).
- _Data required:_ `/api/v1/search?q={text}&filters={filters}`.

**`Screen: Note Detail (Slide-in over Home/Search)`**

- _Top bar:_ `[< Back]` | `[ Trash Icon ]` `[ Share/Action Menu ]`
- _Header:_ H1 Title, Metadata (URL, Date added, Word count).
- _Section 1:_ **AI Summary** (блок выделен стилистически - легкий фон, иконка искры).
- _Section 2:_ Transcript / Full Text (сворачиваемый, если большой).
- _Section 3:_ Semantic matches ("Related notes" - 3 карточки).
- _Data required:_ `/api/v1/notes/{id}`.

**`Screen: Jobs / Queue`**

- _Top bar:_ H1 "Active Processes".
- _UI Blocks:_
  - List of Jobs.
  - _Card "Processing":_ Title, Progress Bar (45%), Spinner.
  - _Card "Failed":_ Red border, Reason text, `[ 🔄 Retry ]` `[ Delete ]` actions.
- _Data required:_ `/api/v1/jobs?status=active,error`.

---

## 5. Command Redesign (Control Plane)

Команды больше не возвращают "простыни". Они действуют как мгновенные триггеры.

- **`/start`**
  - _Current Problem:_ Длинная стена текста с инструкциями. Олдскульно.
  - _New Format:_ Микро-интродукция (2 абзаца). Inline-кнопка открытия Mini App.
- **`/status`**
  - _Current Problem:_ Сырой вывод JSON-подобного текста или списка ID.
  - _New Format:_ Бот: "📊 Система работает штатно. В очереди 2 файла. Обработано 154." + Кнопка `[Смотреть очередь]`.
- **`/find {query}`**
  - _Current Problem:_ Плохая читаемость длинных реплик.
  - _New Format:_ Выдает строго Топ-1 лучший результат + сниппет текста + ссылку на оригинал. Остальное уводит в Mini App по кнопке. (Как "I'm feeling lucky" в Google).
- **`/summary` / `/summary {id}`**
  - _Current Problem:_ Генерация долгого текста, мешает скроллу.
  - _New Format:_ Если без ID: "Генерирую сводку за неделю...". Присылает картинку-тизер или короткий bulleted-list + `[Читать полный брифинг]`.
- **`/job` / `/job {id}`**
  - _Current Problem:_ Слишком "разработческая" команда.
  - _New Format:_ Убрать из общего меню (сделать скрытой, для power users). В ответ: "Job #123: Error 403" + inline: `[Retry]` | `[Drop]`.
- **`/retry`**
  - _Current Problem:_ Юзеру нужно копировать Job ID в чате.
  - _New Format:_ Оставить алиасом, но перевести весь retry-flow на Inline-кнопки в сообщениях об ошибках, прилетающих от бота.
- **`/delete {id}`**
  - _Current Problem:_ Опасность опечаток. Нет корзины.
  - _New Format:_ Бот: "🗑 Удалено (Trash bin). Хранится 30 дней." + Inline `[Undo]`.

---

## 6. Data & Analytics Plan

**North Star Metric:** Успешный Retrieval Rate = кол-во сессий поиска/просмотра, завершившихся извлечением ценности (клик по URL из заметки, копирование текста из заметки или чтение > 15 секунд в Mini App).

**5 Guardrail Metrics:**

1. Bot Unsubscribe/Block rate.
2. % Failed Jobs.
3. p95 время парсинга.
4. % выходов (Bounce) из Mini App < 3 секунд (индикатор долгого Cold-start).
5. Кол-во обращений в поддержку / гневных фидбеков.

**Event Schema (Subset of 25):**

| event_name                      | trigger                         | properties                                          | purpose                              |
| :------------------------------ | :------------------------------ | :-------------------------------------------------- | :----------------------------------- |
| `bot_message_sent`              | Юзер отправил боту ссылку       | `source_type (bot)`, `content_type (url/text/file)` | Замер Ingestion                      |
| `bot_command_used`              | Ввод `/command`                 | `command_name`, `has_args (bool)`                   | Анализ использования fallback-команд |
| `miniapp_opened`                | Клик на кнопку открытия         | `source (menu_button, inline_button, bot_push)`     | Замер конверсии в UI                 |
| `miniapp_search_performed`      | Ввод q и нажатие enter/debounce | `query_length`, `is_semantic (bool)`                | Анализ интенсивности поиска          |
| `miniapp_search_result_clicked` | Тап по карточке в поиске        | `rank (позиция)`, `score (relevance)`               | Замер качества поиска                |
| `miniapp_note_viewed`           | Открытие детального экрана      | `note_id`, `view_duration_sec`                      | Замер Engagement                     |
| `miniapp_action_delete`         | Тап по иконке Trash             | `location (list, detail)`                           | Замер чистки                         |
| `miniapp_action_undo`           | Нажатие Undo (snackbar)         | `note_id`                                           | Замер "Accidental deletion"          |
| `job_retry_invoked`             | Нажатие Retry                   | `job_id`, `source (bot, miniapp)`                   | Замер friction                       |
| `briefing_push_opened`          | Клик из утреннего пуша бота     | `campaign_id`                                       | Измерение активации DAU              |

_(Остальные 15 идентичны по структуре для покрытия скролла, фильтров, изменения настроек, ошибок фронта, копирования в клипборд и т.д.)_

**Воронки:**

1. _Mini App Adoption:_ `bot_message_sent` -> `bot_push_received` -> `miniapp_opened` -> `miniapp_note_viewed`.
2. _Retrieval-to-value:_ `miniapp_opened` -> `miniapp_search_performed` -> `miniapp_search_result_clicked` -> `clipboard_copied_text`.

---

## 7. Security/Abuse by UX Design

| Risk / Threat                  | UX Mitigation                                                                                                | Backend / System Mitigation                                                       | Monitoring Signal                                                       |
| :----------------------------- | :----------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------- | :---------------------------------------------------------------------- |
| **Accidental Deletion**        | Нет диалогов подтверждения (бесят), вместо этого "Soft Delete" со всплывающим Snackbar `[Undo]` на 5 сек.    | Запись помечается `is_deleted=1`, физическое очищение кроном через 30 дней.       | event `miniapp_action_undo` spikes -> UI кнопка неудачно нажимается.    |
| **Command Flood/Abuse**        | В боте скрыты тяжелые команды из видимого меню. Реакция бота — замена сообщений, а не новые.                 | Rate-limiting (Token bucket) на Ingestion и поисковые запросы.                    | 429 ошибки на пользователя.                                             |
| **Multi-tenant Data Leakage**  | ID заметок не должны угадываться. В Mini App нельзя вбить `/note/1` и увидеть чужую.                         | Использование UUIDv4, RLS (Row Level Security) в Postgres на уровне пользователя. | Доступ по userID, несовпадение токена TG-auth и владельца записи = 403. |
| **Malicious URL/File parsing** | Индикатор "Scanning..." перед началом глубокого анализа (дает время отменить). Дисклеймеры на тяжелые файлы. | Изоляция воркеров (Docker/gVisor), строгие таймауты парсинга (SSRF защита).       | Частые Job Failures (OOM, Timeout) у конкретного юзера.                 |

---

## 8. Build Plan (Roadmap 12 weeks)

_Scope: Команда 2-3 человека (Backend, Frontend/React, PM/Design)_

**Week 1: Быстрые победы & Гигиена**

- _Scope:_ Уменьшить спам в боте, почистить выдачу команд, заложить Mini App Skeleton.
- _Deliverables:_ Тихий парсинг (обновление / удаление сообщений), настройка React/Vite/Telegram Web App SDK, авторизация через `initDataUnsafe`.
- _Dependencies:_ Настроенные CI/CD для Mini App (Vercel/Netlify).

**Weeks 2-4: v1 Launch (The Retrieval Engine)**

- _Scope:_ Реализовать основной flow чтения и поиска в Mini App.
- _Deliverables:_ Home Dashboard view, Полный экран поиска, Детальный экран заметки (только чтение). Авторизованные API-эндопинты. Перевод кнопок из бота в Mini App.
- _Acceptance:_ Юзер может найти заметку в MA так же, как в боте, но быстрее и удобнее читать.

**Weeks 5-8: Stabilization + Growth (The "App" Feel)**

- _Scope:_ Управление состоянием (удаление/очередь) + производительность.
- _Deliverables:_ UI для Jobs/Queue с WebSocket/Polling. Кнопка Retina/Retry. Soft delete (корзина). Кэширование на фронте.
- _Acceptance:_ TTFB открытия Mini App < 1 сек. Плавные анимации без дерганья. Полный отказ от `/job` и `/delete` как текстовых команд у 90% аудитории.

**Weeks 9-12: Differentiation (Tinder Review & Daily Briefings)**

- _Scope:_ Внедрение Retention-фич.
- _Deliverables:_ Tinder-карточки для разбора инбокса. Бэкенд генерации ежедневных саммари. Красивое UI для Briefings. Push-кампании.
- _Acceptance:_ Запуск Daily Brief увеличивает DAU минимум на 20%.

---

## 9. Top 3 Bets (Сильнейшие ставки)

1. **Мгновенный "Тихий добав" (Silent Append) в Bot. **
   - _Почему:_ Пользователи ненавидят, когда бот "разговаривает" после каждой сохраненной ссылки, перекрывая чат. Сделав бота невидимым "пылесосом", мы закрепим привычку инпута. Основной UI берет на себя Mini App.
   - _Impact:_ Огромное снижение фрустрации. _Risk:_ Низкий. _Rollback:_ Вернуть отбивку "Сохранено" флагом в базе, если будут жалобы на непонимание статуса.

2. **Global Semantic Search в Mini App.**
   - _Почему:_ Командная строка CLI/Бота ужасна для перебора вариантов (когнитивная нагрузка: прочесть список текста, выделить нужный ID, набрать команду просмотра). Визуальный поиск с подсветкой и сниппетами решает задачу Retrieval в разы быстрее.
   - _Impact:_ Радикальное улучшение Core Value Metric. _Risk:_ Техническая сложность (latency поиска + рендеринг MA). _Rollback:_ Fallback-кнопка в UI на серверный старый поиск, если Semantic упадет.

3. **AI Briefing Digest (Push-to-App).**
   - _Почему:_ Люди активно сохраняют, но пассивно читают ("Read-it-later graveyards"). У бота нет естественных триггеров возврата, кроме "мне что-то понадобилось". Проактивный digest формирует habit-loop.
   - _Impact:_ Рост Retention и MAU. _Risk:_ Риск показаться спамером и получить Block Bot. _Rollback:_ Легкая отписка в 1 клик ("Mute Briefings"); жесткий лимит — не слать, если юзер не сохранил минимум 3 ссылки за неделю.

---

### Open Questions (Для проработки с командой)

1. Какой стек сейчас на бэкенде и можем ли мы легко выставить REST/GraphQL API с аутентификацией `Telegram Web App initData`?
2. Готовы ли мы платить за LLM при проактивной генерации "Daily Briefing" для всех пользователей, или это будет Premium-фича?
3. Какой latency у существующего семантического поиска? Если > 2 сек, нужен скелетон-лоадер (очень критично для UX).
4. Поддерживаем ли мы оффлайн-кэш на стороне Mini App (IndexedDB) для мгновенной загрузки уже скачанных заметок? (Уменьшит расходы на БД).
5. Насколько часто падают Jobs? Если < 1% — UI очереди можно делать минималистичным, скрыть в "Настройки". Если > 15% — это первичный UI блок.
