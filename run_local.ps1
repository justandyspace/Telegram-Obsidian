$env:APP_ROLE = "bot"
$env:TELEGRAM_TOKEN = "PUT_TELEGRAM_TOKEN_HERE"
$env:TELEGRAM_ALLOWED_USER_ID = "PUT_TELEGRAM_USER_ID_HERE"
$env:VAULT_PATH = (Resolve-Path ".\local_obsidian_inbox").Path
$env:STATE_DIR = (Resolve-Path ".\.data\state").Path
$env:CACHE_DIR = (Resolve-Path ".\.data\cache").Path
$env:INDEX_DIR = (Resolve-Path ".\.data\index").Path

python -m src.main --role bot
