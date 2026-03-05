# Open Source Checklist

Before publishing the repository:

1. Ensure `.env` is not tracked and secrets are only in local/private env files.
2. Run secret scan:
   - `rg -n --hidden --glob '!.git/*' --glob '!.venv/*' "(TELEGRAM_TOKEN=|GEMINI_API_KEY=|CF_TUNNEL_TOKEN=|AIza[0-9A-Za-z\\-_]{20,}|[0-9]{8,10}:[A-Za-z0-9_-]{20,})"`
3. Verify no personal local paths remain (`C:\Users\...`, `/home/<user>/...`) except generic docs/examples.
4. Keep only template files in git:
   - `.env.example`
   - `billing_details.example.txt`
5. Review `git status` and remove accidental files (`.sessions/`, runtime data, caches).
6. Optional: run `scripts/predeploy_guard.py` and tests before tagging release.
