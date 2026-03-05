# Product Roadmap & Sprint 1 Technical Specification
> Дата: 2026-03-05
> Проект: telegram-obsidian-local

## 🏆 Идеи для Quick Wins (Максимальный вау-эффект)

### 1. Voice-to-Text → Obsidian (P0)
**Почему:** Меняет поведение пользователя — из "сохранения ссылок" превращает бот в "внешнюю память". 
**Реализация:**
- Новый парсер: `src/parsers/voice_parser.py`
- Использование уже доступного `gemini-2.5-flash` (multimodal).
- API: `genai.upload_file()` + `generate_content(audio_part)`.

### 2. Авто-тегирование через LLM (P0)
**Почему:** Заметки самоорганизуются без усилий пользователя.
**Реализация:** 
- Шаг AI Enrichment добавляется в `src/worker.py` между парсингом и сохранением (`writer.write()`).

### 3. File Watcher для RAG-индекса (P1)
**Почему:** Критично для надёжности. Если менять файлы в Obsidian руками, RAG деградирует.
**Реализация:**
- Watchdog-демон как третья роль: `APP_ROLE=watcher`. Слушает изменения в папке `local_obsidian_inbox` и обновляет индекс.

---

## 🛠️ Technical Specification: Sprint 1 (Voice & Auto-tagging)

Этот спринт фокусируется на добавлении голосовых заметок и автоматическом тегировании.

### Задача 1: Авто-тегирование (AI Enrichment)
* **Архитектура:** Создать `src/pipeline/ai_enrichment.py` (или расширить `normalize.py`). Встроить вызов функции в `src/worker.py`.
* **Логика работы:**
  1. Системный промпт для Gemini: *"Проанализируй текст и верни 2-4 релевантных тега в формате JSON массива строк (например: [\"python\", \"ideas\"])."*
  2. Использовать `response_mime_type="application/json"` для получения валидного JSON.
  3. Объединить полученные теги с существующими (если были извлечены из Telegram).
* **Обработка ошибок:** Вызов обернуть в `try/except`. При ошибке API или таймауте — не фейлить задачу, а просто сохранять заметку без AI-тегов (graceful degradation).

### Задача 2: Voice-to-Text Parser (Голосовые сообщения)
* **Telegram Router:** В `src/bot/telegram_router.py` добавить хэндлер для `F.voice | F.audio`. Скачивать файл во временную директорию (через aiogram).
* **Новый парсер:** Создать `src/parsers/voice_parser.py`.
* **Логика работы:**
  1. **Загрузка:** `genai.upload_file(path)` во временное хранилище Gemini.
  2. **Транскрибация:** Вызов `gemini-2.5-flash` с аудио-файлом и промптом: *"Тщательно транскрибируй аудио. Если есть четкая мысль или задача, добавь краткое резюме."*
  3. **Очистка:** Обязательно вызывать `file.delete()` через API Gemini и удалять локальный временный файл.
  4. **Payload:** Возвращать стандартный объект парсинга (например, `ParsedArticle`), где текст — это транскрипт.

### Задача 3: Telegram Forward Attributes (Бонус)
* **Логика:** При обработке сообщения проверять `message.forward_origin`.
* Если это форвард из канала (`ForwardOriginChannel`), извлекать название канала (`chat.title`) и ссылку.
* Передавать эти данные в `Job Payload` и рендерить в YAML Frontmatter заметки (`source`, `author`, `forwarded_at`).
