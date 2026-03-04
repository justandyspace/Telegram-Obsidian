# INCIDENT PLAYBOOK

## Severity definitions

- `SEV-1`: bot/worker fully unavailable, data loss risk, security incident.
- `SEV-2`: degraded processing, partial command failure, retries accumulating.
- `SEV-3`: non-critical parser/provider instability.

## Triage checklist (first 10 minutes)

1. Confirm service state:
   ```bash
   cd /home/user/telegram-obsidian-local
   docker compose ps
   docker compose logs --tail=200 bot worker
   ```
2. Check health sockets:
   - bot `127.0.0.1:8080`
   - worker `127.0.0.1:8081`
3. Run DB integrity:
   ```bash
   python scripts/db_integrity_check.py --db .data/state/bot_state.sqlite3
   ```
4. Recover stuck jobs:
   ```bash
   python scripts/recover_stuck_jobs.py --db .data/state/bot_state.sqlite3 --max-age-seconds 600
   ```

## Security incident flow

Symptoms:
- Unexpected webhook traffic.
- Unauthorized Telegram messages.
- Secret leak suspicion.

Immediate actions:
1. Rotate `TELEGRAM_TOKEN` and `WEBHOOK_SECRET_TOKEN`.
2. Restrict ingress (`WEBHOOK_BASE_URL`, proxy ACL).
3. Restart bot/worker:
   ```bash
   docker compose up -d --force-recreate bot worker
   ```
4. Audit logs and queue:
   ```bash
   docker compose logs --since=2h bot worker
   ```

## Upstream API degradation (Gemini / parser targets)

Symptoms:
- Increased retries / `retry` queue growth.
- Parser fetch errors.

Actions:
1. Verify worker is running and recovering stuck jobs.
2. Keep processing active (embedder fallback is automatic).
3. If needed, lower pressure temporarily:
   - increase `WORKER_POLL_SECONDS`
   - reduce parser URL load at input
4. Requeue failed items using `/retry <job_id_or_prefix>`.

## Data corruption or restore

1. Stop workload:
   ```bash
   docker compose stop bot worker
   ```
2. Restore from latest known-good backup.
3. Start services and verify `/status` in Telegram plus health endpoints.

## Post-incident requirements

1. Root-cause summary.
2. Timeline with UTC timestamps.
3. Remediation PRs and preventive tests.
4. Update this playbook and runbook if gaps were found.

