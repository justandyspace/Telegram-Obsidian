$env:APP_ROLE = "bot"
$env:TELEGRAM_MODE = "polling"
$env:TELEGRAM_TOKEN = "PUT_TELEGRAM_TOKEN_HERE"
$env:TELEGRAM_ALLOWED_USER_ID = "PUT_TELEGRAM_USER_ID_HERE"
$env:TENANT_MODE = "single"
$env:GEMINI_API_KEY = "PUT_GEMINI_API_KEY_HERE_OR_LEAVE_EMPTY_FOR_HASH_FALLBACK"
$env:GEMINI_EMBED_MODEL = "gemini-embedding-001"
$env:GEMINI_GENERATION_MODEL = "gemini-2.5-flash"
$env:WEBHOOK_BASE_URL = ""
$env:WEBHOOK_BIND_HOST = "0.0.0.0"
$env:WEBHOOK_BIND_PORT = "8082"
$env:WEBHOOK_PATH = "/telegram/webhook"
$env:WEBHOOK_SECRET_TOKEN = ""
$env:VAULT_PATH = (Resolve-Path ".\local_obsidian_inbox").Path
$env:STATE_DIR = (Resolve-Path ".\.data\state").Path
$env:CACHE_DIR = (Resolve-Path ".\.data\cache").Path
$env:INDEX_DIR = (Resolve-Path ".\.data\index").Path
$env:WORKER_RECOVERY_INTERVAL_SECONDS = "30"
$env:WORKER_STUCK_TIMEOUT_SECONDS = "600"

python -m src.main --role bot
