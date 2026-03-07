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
    telegram_allowed_user_ids: tuple[int, ...]
    multi_tenant_mode: bool
    telegram_mode: str
    webhook_base_url: str
    webhook_bind_host: str
    webhook_bind_port: int
    webhook_path: str
    webhook_secret_token: str
    mini_app_base_url: str
    vault_path: Path
    state_dir: Path
    cache_dir: Path
    index_dir: Path
    log_level: str
    worker_poll_seconds: float
    worker_recovery_interval_seconds: float
    worker_stuck_timeout_seconds: int
    watcher_poll_seconds: float
    job_max_retries: int
    bot_health_port: int
    worker_health_port: int
    gemini_api_key: str
    gemini_embed_model: str
    gemini_generation_model: str
    gdrive_enabled: bool = False
    gdrive_client_id: str = ""
    gdrive_client_secret: str = ""
    gdrive_refresh_token: str = ""
    gdrive_root_folder_id: str = ""
    gdrive_share_public_links: bool = False
    gdrive_vault_mirror_interval_seconds: int = 1800
    gdrive_db_snapshot_interval_seconds: int = 86400

    @property
    def state_db_path(self) -> Path:
        return self.state_dir / "bot_state.sqlite3"


def _required(name: str, value: str | None) -> str:
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _validate_webhook_secret(secret: str) -> None:
    value = (secret or "").strip()
    if len(value) < 16:
        raise RuntimeError("WEBHOOK_SECRET_TOKEN must be at least 16 characters for secure webhook mode.")
    weak_values = {"change_me", "changeme", "secret", "token", "webhook_secret"}
    if value.lower() in weak_values:
        raise RuntimeError("WEBHOOK_SECRET_TOKEN is too weak; use a random token.")  # pragma: no cover


def load_config() -> AppConfig:
    role = os.getenv("APP_ROLE", "bot").strip().lower()
    if role not in {"bot", "worker", "watcher", "standalone"}:
        raise RuntimeError("APP_ROLE must be either 'bot', 'worker', 'watcher', or 'standalone'.")

    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if role in {"bot", "standalone"}:
        token = _required("TELEGRAM_TOKEN", token)

    configured_multi_tenant = os.getenv("TENANT_MODE", "single").strip().lower() == "multi"
    telegram_mode = os.getenv("TELEGRAM_MODE", "auto").strip().lower()
    if telegram_mode not in {"auto", "polling", "webhook"}:
        raise RuntimeError("TELEGRAM_MODE must be one of: auto, polling, webhook.")
    allowed_list_raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    allowed_single_raw = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
    if role in {"bot", "standalone"} and not allowed_list_raw and not allowed_single_raw:
        raise RuntimeError(
            "Set TELEGRAM_ALLOWED_USER_ID or TELEGRAM_ALLOWED_USER_IDS."
        )

    allowed_user_ids: list[int] = []
    if allowed_list_raw:
        for piece in allowed_list_raw.split(","):
            item = piece.strip()
            if not item:
                continue
            try:
                allowed_user_ids.append(int(item))
            except ValueError as exc:
                raise RuntimeError(
                    "TELEGRAM_ALLOWED_USER_IDS must be comma-separated integers."
                ) from exc
    if allowed_single_raw:
        try:
            single_id = int(allowed_single_raw)
        except ValueError as exc:
            raise RuntimeError("TELEGRAM_ALLOWED_USER_ID must be an integer.") from exc
        if single_id not in allowed_user_ids:
            allowed_user_ids.append(single_id)

    if role in {"bot", "standalone"} and not allowed_user_ids:
        raise RuntimeError(
            "No allowed Telegram user ids configured. Set TELEGRAM_ALLOWED_USER_ID or TELEGRAM_ALLOWED_USER_IDS."
        )

    allowed_user_id = allowed_user_ids[0] if allowed_user_ids else 0
    multi_tenant_mode = configured_multi_tenant or len(set(allowed_user_ids)) > 1

    vault_path = Path(os.getenv("VAULT_PATH", "/data/vault")).resolve()
    state_dir = Path(os.getenv("STATE_DIR", "/srv/obsidian-bot/state")).resolve()
    cache_dir = Path(os.getenv("CACHE_DIR", "/srv/obsidian-bot/cache")).resolve()
    index_dir = Path(os.getenv("INDEX_DIR", "/srv/obsidian-bot/index")).resolve()
    webhook_base_url = os.getenv("WEBHOOK_BASE_URL", "").strip()
    webhook_bind_host = os.getenv("WEBHOOK_BIND_HOST", "0.0.0.0").strip()
    webhook_bind_port = int(os.getenv("WEBHOOK_BIND_PORT", "8082"))
    webhook_path = os.getenv("WEBHOOK_PATH", "/telegram/webhook").strip() or "/telegram/webhook"
    if not webhook_path.startswith("/"):
        webhook_path = "/" + webhook_path
    webhook_secret_token = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
    mini_app_base_url = os.getenv("MINI_APP_BASE_URL", "").strip()
    if telegram_mode == "webhook" and not webhook_base_url:
        raise RuntimeError("WEBHOOK_BASE_URL is required when TELEGRAM_MODE=webhook.")
    webhook_secret_required = telegram_mode == "webhook" or (
        telegram_mode == "auto" and bool(webhook_base_url)
    )
    if webhook_secret_required:
        if not webhook_secret_token:
            raise RuntimeError(
                "WEBHOOK_SECRET_TOKEN is required when webhook endpoint is enabled."
            )
        _validate_webhook_secret(webhook_secret_token)
    elif webhook_secret_token:
        _validate_webhook_secret(webhook_secret_token)

    return AppConfig(
        role=role,
        telegram_token=token,
        telegram_allowed_user_id=allowed_user_id,
        telegram_allowed_user_ids=tuple(sorted(set(allowed_user_ids))),
        multi_tenant_mode=multi_tenant_mode,
        telegram_mode=telegram_mode,
        webhook_base_url=webhook_base_url,
        webhook_bind_host=webhook_bind_host,
        webhook_bind_port=webhook_bind_port,
        webhook_path=webhook_path,
        webhook_secret_token=webhook_secret_token,
        mini_app_base_url=mini_app_base_url,
        vault_path=vault_path,
        state_dir=state_dir,
        cache_dir=cache_dir,
        index_dir=index_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        worker_poll_seconds=float(os.getenv("WORKER_POLL_SECONDS", "2")),
        worker_recovery_interval_seconds=float(
            os.getenv("WORKER_RECOVERY_INTERVAL_SECONDS", "30")
        ),
        worker_stuck_timeout_seconds=int(
            os.getenv("WORKER_STUCK_TIMEOUT_SECONDS", "600")
        ),
        watcher_poll_seconds=float(os.getenv("WATCHER_POLL_SECONDS", "2")),
        job_max_retries=int(os.getenv("JOB_MAX_RETRIES", "5")),
        bot_health_port=int(os.getenv("BOT_HEALTH_PORT", "8080")),
        worker_health_port=int(os.getenv("WORKER_HEALTH_PORT", "8081")),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_embed_model=os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001").strip(),
        gemini_generation_model=os.getenv("GEMINI_GENERATION_MODEL", "gemini-2.0-flash-lite").strip(),
        gdrive_enabled=os.getenv("GDRIVE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        gdrive_client_id=os.getenv("GDRIVE_CLIENT_ID", "").strip(),
        gdrive_client_secret=os.getenv("GDRIVE_CLIENT_SECRET", "").strip(),
        gdrive_refresh_token=os.getenv("GDRIVE_REFRESH_TOKEN", "").strip(),
        gdrive_root_folder_id=os.getenv("GDRIVE_ROOT_FOLDER_ID", "").strip(),
        gdrive_share_public_links=os.getenv("GDRIVE_SHARE_PUBLIC_LINKS", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        gdrive_vault_mirror_interval_seconds=int(
            os.getenv("GDRIVE_VAULT_MIRROR_INTERVAL_SECONDS", "1800")
        ),
        gdrive_db_snapshot_interval_seconds=int(
            os.getenv("GDRIVE_DB_SNAPSHOT_INTERVAL_SECONDS", "86400")
        ),
    )
