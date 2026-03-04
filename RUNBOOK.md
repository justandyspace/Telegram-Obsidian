# RUNBOOK

## 1. Service control (Docker Compose)

```bash
cd /home/user/telegram-obsidian-local
docker compose up -d --build bot worker
docker compose ps
docker compose logs -f --tail=200 bot worker
```

Stop:
```bash
docker compose stop bot worker
```

Restart:
```bash
docker compose restart bot worker
```

## 2. Health and readiness

```bash
python - <<'PY'
import socket
for port in (8080, 8081):
    s = socket.create_connection(("127.0.0.1", port), timeout=2)
    s.sendall(b"GET /health HTTP/1.0\r\n\r\n")
    print(port, s.recv(256).decode("utf-8", errors="ignore").splitlines()[0])
    s.close()
PY
```

## 3. Queue and DB integrity

```bash
cd /home/user/telegram-obsidian-local
python scripts/db_integrity_check.py --db .data/state/bot_state.sqlite3
python scripts/recover_stuck_jobs.py --db .data/state/bot_state.sqlite3 --max-age-seconds 600
```

## 4. Backup

```bash
cd /home/user/telegram-obsidian-local
mkdir -p backups
python scripts/backup_state.py \
  --state-db .data/state/bot_state.sqlite3 \
  --vault-dir local_obsidian_inbox \
  --index-dir .data/index \
  --out-dir backups
```

## 5. Restore

```bash
cd /home/user/telegram-obsidian-local
docker compose stop bot worker
python scripts/restore_state.py \
  --backup-dir backups/backup-YYYYMMDD-HHMMSS \
  --state-db .data/state/bot_state.sqlite3 \
  --vault-dir local_obsidian_inbox \
  --index-dir .data/index \
  --force
docker compose up -d bot worker
```

## 6. Low-downtime update

```bash
cd /home/user/telegram-obsidian-local
git fetch --all --prune
git checkout main
git pull --ff-only
docker compose build bot worker
docker compose up -d --no-deps bot
docker compose up -d --no-deps worker
docker compose ps
```

## 7. systemd mode (alternative to Docker)

Install units:
```bash
sudo cp deploy/systemd/telegram-obsidian-bot.service /etc/systemd/system/
sudo cp deploy/systemd/telegram-obsidian-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-obsidian-bot telegram-obsidian-worker
sudo systemctl status telegram-obsidian-bot telegram-obsidian-worker
```

