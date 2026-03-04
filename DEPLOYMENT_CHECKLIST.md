# DEPLOYMENT CHECKLIST

## Pre-deploy

1. Code synced and clean:
   ```bash
   cd /home/user/telegram-obsidian-local
   git fetch --all --prune
   git status
   ```
2. Required env values present:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_ALLOWED_USER_ID` or `TELEGRAM_ALLOWED_USER_IDS`
   - `WEBHOOK_SECRET_TOKEN` (if webhook enabled)
3. Quality gates pass:
   ```bash
   pip install -r requirements-dev.txt
   ruff check src tests
   mypy src
   bandit -q -c pyproject.toml -r src
   pip-audit -r requirements.txt
   pytest -q
   ```
4. Backup created:
   ```bash
   mkdir -p backups
   python scripts/backup_state.py \
     --state-db .data/state/bot_state.sqlite3 \
     --vault-dir local_obsidian_inbox \
     --index-dir .data/index \
     --out-dir backups
   ```

## Deploy

```bash
cd /home/user/telegram-obsidian-local
git pull --ff-only
docker compose build bot worker
docker compose up -d --no-deps bot
docker compose up -d --no-deps worker
docker compose ps
docker compose logs --tail=100 bot worker
```

## Post-deploy verification

1. Health checks return `200 OK`.
2. Telegram `/status` works.
3. Enqueue test message and confirm:
   - job moves to `done`
   - note created in tenant vault
   - RAG search returns the note

## Rollback trigger conditions

- Failed health checks after restart.
- Queue growth in `failed`/`processing`.
- Security/auth regression.
- Data write failures.

## Rollback

```bash
cd /home/user/telegram-obsidian-local
docker compose stop bot worker
git checkout <previous_known_good_commit>
docker compose build bot worker
docker compose up -d bot worker
```

Data rollback (only if required):
```bash
python scripts/restore_state.py \
  --backup-dir backups/backup-YYYYMMDD-HHMMSS \
  --state-db .data/state/bot_state.sqlite3 \
  --vault-dir local_obsidian_inbox \
  --index-dir .data/index \
  --force
docker compose up -d bot worker
```
