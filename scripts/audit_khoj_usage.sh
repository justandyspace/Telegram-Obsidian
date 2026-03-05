#!/usr/bin/env bash
set -u

echo "=== KHOJ SERVER USAGE AUDIT ==="
echo "host: $(hostname)"
echo "time: $(date -Is)"
echo

run_section() {
  local title="$1"
  shift
  echo "---- ${title} ----"
  "$@" 2>/dev/null || true
  echo
}

run_section "docker containers (khoj/postgres/pgvector)" \
  bash -lc "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' | grep -Ei 'khoj|postgres|pgvector|chroma|qdrant|milvus' || echo 'no matches'"

run_section "docker compose projects (khoj refs)" \
  bash -lc "docker compose ls 2>/dev/null | grep -Ei 'khoj|postgres|pgvector' || echo 'no matches'"

run_section "systemd units" \
  bash -lc "systemctl list-unit-files --type=service | grep -Ei 'khoj|postgres|pgvector' || echo 'no matches'"

run_section "running processes" \
  bash -lc "ps aux | grep -Ei 'khoj|postgres|pgvector|khoj-server' | grep -v grep || echo 'no matches'"

run_section "listening ports (incl 42110 khoj, 5432 postgres)" \
  bash -lc "ss -ltnp | grep -E ':42110|:5432' || echo 'no matches'"

run_section "cron references" \
  bash -lc "(crontab -l 2>/dev/null; sudo crontab -l 2>/dev/null; sudo ls -1 /etc/cron.d 2>/dev/null | xargs -r -I{} sudo sh -c 'echo ### /etc/cron.d/{}; cat /etc/cron.d/{}') | grep -Ei 'khoj|postgres|pgvector' || echo 'no matches'"

run_section "env files in common app dirs" \
  bash -lc "grep -RInE 'khoj|postgres|pgvector|DATABASE_URL|KHOJ' /home /opt /srv /etc 2>/dev/null | head -n 200 || echo 'no matches'"

run_section "compose/yaml/json/toml configs with khoj refs" \
  bash -lc "find /home /opt /srv /etc -maxdepth 5 -type f \\( -name 'docker-compose*.yml' -o -name '*.yaml' -o -name '*.yml' -o -name '*.json' -o -name '*.toml' -o -name '*.env' \\) 2>/dev/null | xargs -r grep -InE 'khoj|postgres|pgvector|DATABASE_URL|KHOJ' 2>/dev/null | head -n 300 || echo 'no matches'"

run_section "filesystem paths named *khoj*" \
  bash -lc "find / -maxdepth 5 -iname '*khoj*' 2>/dev/null | head -n 200 || echo 'no matches'"

echo "=== END AUDIT ==="
