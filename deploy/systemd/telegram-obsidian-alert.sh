#!/usr/bin/env bash
set -euo pipefail

FAILED_UNIT="${1:-unknown}"
HOSTNAME_VALUE="$(hostname)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MESSAGE="telegram-obsidian alert: unit=${FAILED_UNIT} host=${HOSTNAME_VALUE} ts=${TS}"

if [[ -n "${ALERT_WEBHOOK_URL:-}" ]]; then
  curl -fsS -m 10 -X POST "${ALERT_WEBHOOK_URL}" \
    -H "Content-Type: application/json" \
    -d "{\"text\":\"${MESSAGE}\"}" \
    >/dev/null || true
fi

logger -t telegram-obsidian-alert "${MESSAGE}"
