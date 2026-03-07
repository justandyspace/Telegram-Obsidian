# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/`. Key areas are `src/bot/` for Telegram handlers and commands, `src/pipeline/` for ingest/enrichment flow, `src/obsidian/` for vault writes and search helpers, `src/rag/` for indexing/retrieval, and `src/infra/` for config, storage, logging, and integrations. Tests live in `tests/`. Operational scripts are in `scripts/`, while deployment files sit under `deploy/`. Local runtime data is written to `.data/`, `.sessions/`, and `local_obsidian_inbox/`.

## Build, Test, and Development Commands
- `.\.venv\Scripts\python -m src.main --role bot` starts the Telegram bot only.
- `.\.venv\Scripts\python -m src.main --role worker` starts the async worker only.
- `.\.venv\Scripts\python -m src.main --role standalone` runs bot and worker in one local process.
- `.\.venv\Scripts\python -m pytest` runs the full test suite with coverage.
- `.\.venv\Scripts\python -m ruff check src tests` runs lint checks.
- `.\.venv\Scripts\python -m mypy src` runs static type checks.

## Coding Style & Naming Conventions
Use Python 3.12, 4-space indentation, and type hints on new code. Follow existing module naming: `snake_case.py` for files, `PascalCase` for classes, `snake_case` for functions, and uppercase for constants. Keep changes small and local to the relevant subsystem. Ruff is the formatting/lint baseline; line length is 110.

## Testing Guidelines
Tests use `pytest`; test files must be named `tests/test_*.py`. Coverage is enforced in `pyproject.toml` with `--cov-fail-under=62`. Prefer focused unit tests near the changed behavior, then run broader regression checks when routing, storage, or RAG logic changes.

## Commit & Pull Request Guidelines
Recent history favors short imperative subjects, often with prefixes like `fix:` and `chore:`. Keep commit messages specific, for example: `fix: sanitize Telegram media links in notes`. PRs should describe the user-facing impact, note config or migration changes, and list verification steps performed.

## Security & Runtime Notes
Never commit real secrets from `.env`, Telegram sessions, or generated vault/state data. For major bot, router, pipeline, config, or Telegram UX changes, run live Telegram E2E before considering the work complete. `scripts/tg_mega_smoke.py` is the primary deterministic check; `scripts/tg_smoke_test.py` is only a quick sanity check.
