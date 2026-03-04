"""Runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    role: str
    telegram_token: str
    telegram_allowed_user_id: int
    vault_path: Path
    state_dir: Path
    cache_dir: Path
    index_dir: Path
    log_level: str
    worker_poll_seconds: float
    job_max_retries: int
    bot_health_port: int
    worker_health_port: int

    @property
    def state_db_path(self) -> Path:
        return self.state_dir / "bot_state.sqlite3"


def _required(name: str, value: str | None) -> str:
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def load_config() -> AppConfig:
    role = os.getenv("APP_ROLE", "bot").strip().lower()
    if role not in {"bot", "worker"}:
        raise RuntimeError("APP_ROLE must be either 'bot' or 'worker'.")

    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if role == "bot":
        token = _required("TELEGRAM_TOKEN", token)

    allowed_raw = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
    if role == "bot":
        allowed_raw = _required("TELEGRAM_ALLOWED_USER_ID", allowed_raw)

    try:
        allowed_user_id = int(allowed_raw or "0")
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_ID must be an integer.") from exc

    vault_path = Path(os.getenv("VAULT_PATH", "/data/vault")).resolve()
    state_dir = Path(os.getenv("STATE_DIR", "/srv/obsidian-bot/state")).resolve()
    cache_dir = Path(os.getenv("CACHE_DIR", "/srv/obsidian-bot/cache")).resolve()
    index_dir = Path(os.getenv("INDEX_DIR", "/srv/obsidian-bot/index")).resolve()

    return AppConfig(
        role=role,
        telegram_token=token,
        telegram_allowed_user_id=allowed_user_id,
        vault_path=vault_path,
        state_dir=state_dir,
        cache_dir=cache_dir,
        index_dir=index_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        worker_poll_seconds=float(os.getenv("WORKER_POLL_SECONDS", "2")),
        job_max_retries=int(os.getenv("JOB_MAX_RETRIES", "5")),
        bot_health_port=int(os.getenv("BOT_HEALTH_PORT", "8080")),
        worker_health_port=int(os.getenv("WORKER_HEALTH_PORT", "8081")),
    )
