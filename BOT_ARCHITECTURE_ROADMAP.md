# Telegram -> Obsidian Bot: Final Architecture & Roadmap

## Scope
Build a server-side Telegram bot that ingests user content, stores structured Markdown notes in an Obsidian vault, and supports semantic retrieval/summaries across the knowledge base.

## Locked Decisions (Accepted)
1. Sync strategy: `Obsidian LiveSync + CouchDB` (Option B).
2. Sync optimization: RAG indexes/cache must stay server-only (outside synced vault).
3. Bot access: strict single-user mode in MVP (hard bind to one Telegram `user_id`).
4. Deployment mode in MVP: `Long Polling` (no domain/TLS requirement yet).
5. CouchDB access in MVP: local network and/or VPN (`Tailscale` preferred), no public exposure.
6. Edit policy: bot never overwrites manual text; bot updates only its own managed blocks. Re-summary only on explicit `#resummarize`.
7. Transcription: postponed after MVP.
8. Models: Gemini API for generation and embeddings.
9. File naming: `YYYYMMDD-HHMM - Title (ID).md`.
10. Language profile: mixed `RU/EN/UK` content; prompts and retrieval must be multilingual.
11. X/Twitter in MVP: no paid API; fallback via raw link + public redirect metadata (`fxtwitter`/`vxtwitter`).
12. Project hygiene: no Cyrillic/translit filenames in codebase; modular Python structure; best practices.

## System Architecture (MVP)
### Services (`docker-compose`)
- `bot`: Telegram intake, command routing, user auth gate.
- `worker`: async processing pipeline for extraction/summarization/indexing.
- `couchdb`: LiveSync backend.
- Optional: `scheduler` for retry/reindex jobs.

### Storage Boundaries
- Synced Obsidian vault: user-facing notes only.
- Server-only data (not synced to devices):
  - `/srv/obsidian-bot/index/` (vector index, chunk maps)
  - `/srv/obsidian-bot/cache/` (fetch/cache artifacts)
  - `/srv/obsidian-bot/state/` (job state, idempotency keys)

### Note Ownership Model
- Bot writes only into explicit managed blocks:
  - `BOT_META`
  - `BOT_SUMMARY`
  - `BOT_TASKS`
  - `BOT_LINKS`
- User text outside those blocks is immutable for the bot.
- `#resummarize` is required to regenerate summary block.

## Target Repository Structure
```text
project-root/
  docker-compose.yml
  .env.example
  README.md
  pyproject.toml
  src/
    main.py
    config.py
    bot/
      telegram_router.py
      commands.py
      auth.py
    pipeline/
      ingest.py
      normalize.py
      actions.py
      dedup.py
      jobs.py
    parsers/
      article_parser.py
      youtube_parser.py
      pdf_parser.py
      twitter_fallback_parser.py
    obsidian/
      note_schema.py
      note_writer.py
      block_merge.py
      vault_router.py
    rag/
      embedder.py
      chunker.py
      index_store.py
      retriever.py
    infra/
      logging.py
      metrics.py
      storage.py
  tests/
```

## Prioritized Roadmap

## Priority: Critical (Foundation)
1. Compose baseline with `bot + worker + couchdb`.
2. Telegram strict-auth gate by `user_id`.
3. Long polling runtime and resilient startup.
4. Ingestion contract (`content + hashtags`, default action = `#save`).
5. Idempotent job pipeline with retry and dedup.
6. Obsidian note schema + deterministic filename format.
7. Managed-block write policy (no user text overwrite).
8. Git versioning baseline (clean commits, env templates, secrets policy).

Definition of done (Critical):
- Message/link from authorized user becomes a structured note in vault.
- Note syncs to desktop via LiveSync.
- Repeated same input does not create duplicates.
- Manual edits remain intact after bot updates.

## Priority: High (Content and UX)
1. Parsers: article URL, PDF text extraction, YouTube captions path.
2. X fallback parser (`fxtwitter`/`vxtwitter` metadata + raw URL persistence).
3. Action tags:
- `#save`
- `#summary`
- `#task`
- `#resummarize`
- `#translate`
4. Commands:
- `/find`
- `/summary`
- `/status`
- `/retry <job_id>`
5. Structured status responses and error transparency.

Definition of done (High):
- Core content types are processed with graceful fallback.
- User can query status and retry failed jobs.
- Action tags change pipeline behavior deterministically.

## Priority: Medium/Hard (RAG)
1. Multilingual chunking and embedding pipeline (Gemini embeddings).
2. Vector index in server-only storage.
3. Retrieval API for `/find` and `/summary <question>`.
4. Source-grounded response formatting with note references.
5. Incremental reindex on note changes.

Definition of done (Medium/Hard):
- Bot answers knowledge questions from vault content, not generic model memory.
- Answers include note-level grounding.

## Post-Release Backlog

### 1. Multi-tenant mode (Многопользовательский режим с изоляцией)
*   **Что это:** Перевод бота из режима "только для одного хозяина" в режим "база знаний для нескольких человек" (с проверкой по whitelist). У каждого пользователя будет свой изолированный vault, свои RAG-индексы и своя очередь задач.
*   **Зачем:** Для безопасного шеринга бота с семьей или коллегами. Гарантирует, что чужие заметки не попадут в ваш Obsidian, а RAG-поиск не сольет ваши данные другому пользователю.
*   **Сложность:** Средняя. Фундамент в коде уже заложен (используется параметр `tenant_id`). Нужно дописать интерфейс приглашений/управления доступом и автоматическое создание tenant-директорий.

### 2. Move from long polling to webhook (Переход на Webhooks)
*   **Что это:** Изменение механизма получения апдейтов от Telegram. Вместо того чтобы бот постоянно спрашивал сервер "есть новые сообщения?" (Long Polling), Telegram сам будет отправлять POST-запросы на ваш сервер при новых событиях (Webhook). Требует домена и TLS (SSL).
*   **Зачем:** Повышение стабильности (нет разрывов коннекта), мгновенная реакция на сообщения, экономия сетевых ресурсов и CPU сервера. Стандарт для production-решений.
*   **Сложность:** Ниже средней. Код бота меняется минимально, основная сложность — настройка инфраструктуры (белый IP, реверс-прокси Nginx/Caddy, сертификаты Let's Encrypt).

### 3. Secure remote CouchDB access via Cloudflare Tunnel (Удаленный доступ к CouchDB)
*   **Что это:** Безопасный проброс локальной базы CouchDB (используемой для Obsidian LiveSync) в интернет без открытия портов на роутере.
*   **Зачем:** Для бесшовной синхронизации заметок с мобильным телефоном вне дома. Позволяет телефону подключаться к CouchDB по красивому адресу (например, `sync.yourdomain.com`) через защищенный туннель Cloudflare, устраняя необходимость постоянно включать VPN (Tailscale).
*   **Сложность:** Низкая (DevOps задача). Код писать не нужно, достаточно запустить Docker-контейнер `cloudflared` и настроить маршрутизацию в дашборде Cloudflare.

### 4. Voice transcription module (Модуль транскрибации голоса)
*   **Что это:** Интеграция API (или локальных моделей типа Whisper) для перевода голосовых сообщений (Voice/Audio/Video) в структурированный текст.
*   **Статус:** **ВЫПОЛНЕНО (Sprint 1)**. Реализовано с использованием мультимодальной генерации Gemini Flash-Lite.

### 5. Mobile-first sync hardening and conflict telemetry (Защита от конфликтов синхронизации)
*   **Что это:** Сбор телеметрии о коллизиях при синхронизации файлов и внедрение умных алгоритмов разрешения конфликтов.
*   **Зачем:** Предотвращение потери данных или дублирования файлов, если пользователь редактирует заметку на телефоне одновременно с тем, как бот (worker) обновляет эту же заметку (например, дописывает AI-саммари).
*   **Сложность:** Высокая. Требует глубокого понимания механизмов CRDT и работы плагина Obsidian LiveSync для корректного автоматического слияния (merge) изменений.

## Non-Functional Requirements
- Secrets in env only; never committed.
- Structured logs with correlation IDs.
- Retry policy with capped exponential backoff.
- Healthcheck endpoints for containers.
- Backup policy for vault and CouchDB snapshots.

## Start Command for Phase 1
Use this exact chat command to start implementation:

`START PHASE 1: Build Critical foundation only (compose services, strict Telegram auth, long polling, ingest + dedup pipeline, Obsidian managed-block writer, deterministic file naming, and initial git-ready project scaffold).`

## Exclusions for MVP
- No transcription.
- No public CouchDB exposure.
- No multi-tenant access.
- No webhook infra.
