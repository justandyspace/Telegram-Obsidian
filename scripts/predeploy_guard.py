#!/usr/bin/env python3
"""Pre-deploy guard.
Runs internal smoke pipeline. If successful, prints READY TO DEPLOY.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PLACEHOLDER_VALUES = {
    "put_your_bot_token_here",
    "put_gemini_api_key_here",
    "replace_with_long_random_secret_token",
    "change_me",
    "changeme",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _validate_env() -> int:
    env = _parse_env_file(ENV_PATH)
    if not env:
        print(f"[ERROR] Missing .env file: {ENV_PATH}")
        return 1

    required = ["TELEGRAM_TOKEN", "GEMINI_API_KEY"]
    for key in required:
        value = env.get(key, "")
        if not value or value.lower() in PLACEHOLDER_VALUES:
            print(f"[ERROR] Secret {key} is empty or placeholder in .env")
            return 1

    couch_pass = env.get("COUCHDB_PASSWORD", "")
    if couch_pass.lower() in PLACEHOLDER_VALUES:
        print("[ERROR] COUCHDB_PASSWORD uses placeholder value in .env")
        return 1

    mode = env.get("TELEGRAM_MODE", "auto").strip().lower()
    webhook_url = env.get("WEBHOOK_BASE_URL", "").strip()
    if mode == "webhook" or (mode == "auto" and webhook_url):
        secret = env.get("WEBHOOK_SECRET_TOKEN", "").strip()
        if len(secret) < 16 or secret.lower() in PLACEHOLDER_VALUES:
            print("[ERROR] WEBHOOK_SECRET_TOKEN is weak or missing for webhook mode")
            return 1

    return 0

def main() -> int:
    print(">>> Running pre-deploy guard...")

    env_code = _validate_env()
    if env_code != 0:
        print("\n[ERROR] Secret/env validation failed! Do not deploy.")
        return env_code
    
    smoke_script = ROOT / "scripts" / "internal_smoke.py"
    
    result = subprocess.run([sys.executable, str(smoke_script)], cwd=ROOT)
    
    if result.returncode != 0:
        print("\n[ERROR] Pre-deploy guard failed! Do not deploy.")
        return result.returncode
        
    print("\n" + "=" * 40)
    print("READY TO DEPLOY")
    print("=" * 40)
    return 0

if __name__ == "__main__":
    sys.exit(main())
