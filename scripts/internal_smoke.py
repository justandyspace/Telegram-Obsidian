"""Internal smoke pipeline for fast post-change validation.

Usage:
  python scripts/internal_smoke.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(title: str, args: list[str], *, env: dict[str, str] | None = None, soft_fail: bool = False) -> None:
    print(f"\n== {title} ==")
    print(" ".join(args))
    try:
        result = subprocess.run(args, cwd=ROOT, env=env)
        if result.returncode != 0:
            if soft_fail:
                print(f"[WARN] {title} failed but soft fail is enabled. Continuing.")
            else:
                raise SystemExit(result.returncode)
    except FileNotFoundError:
        if soft_fail:
            print(f"[WARN] Executable not found for {title}. Continuing.")
        else:
            raise


def _security_sanity() -> None:
    print("\n== Security Sanity ==")
    # 1. Check git status for unwanted files (secrets, backups)
    try:
        git_status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        suspicious_exts = {".env", ".bak", ".backup", ".sql", ".log"}
        for line in git_status.splitlines():
            if len(line) > 3:
                filepath = line[3:]
                ext = Path(filepath).suffix.lower()
                # Flag if it's a raw .env file or has suspicious extension
                if ext in suspicious_exts or Path(filepath).name == ".env":
                    print(f"[WARN] Suspicious or secret file in git status: {filepath}")
    except FileNotFoundError:
        print("[WARN] git not found, skipping git status check.")
    except subprocess.CalledProcessError:
        print("[WARN] git status failed, skipping.")

    # 2. Check compose file for exposed CouchDB
    compose_path = ROOT / "docker-compose.yml"
    if compose_path.exists():
        content = compose_path.read_text(encoding="utf-8")
        in_couchdb = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("couchdb:"):
                in_couchdb = True
            elif in_couchdb and stripped.startswith("ports:"):
                pass
            elif in_couchdb and stripped.startswith("-"):
                if "5984" in stripped and ":" in stripped:
                    if not ("127.0.0.1:" in stripped or "localhost:" in stripped):
                        print(f"[ERROR] CouchDB port exposed publicly in docker-compose.yml!\nLine: {stripped}")
                        raise SystemExit(1)
            elif in_couchdb and not line.startswith(" ") and not line.startswith("\t"):
                if stripped and not stripped.startswith("#"):
                    in_couchdb = False
    print("Security checks passed.")


def main() -> int:
    python = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    _security_sanity()

    _run(
        "Ruff Check",
        [python, "-m", "ruff", "check", "."],
    )

    _run(
        "Compile Check",
        [
            python,
            "-m",
            "py_compile",
            "src/bot/commands.py",
            "src/infra/storage.py",
            "src/obsidian/note_writer.py",
            "src/obsidian/couchdb_bridge.py",
            "src/bot/telegram_router.py",
        ],
    )

    _run(
        "Targeted Pytest Smoke",
        [
            python,
            "-m",
            "pytest",
            "-q",
            "--no-cov",
            "tests/test_job_command.py",
            "tests/test_delete_confirmation_flow.py",
            "tests/test_telegram_media_router.py",
            "tests/test_phase4.py",
            "tests/test_commands_smoke.py",
        ],
        env=env,
    )

    print("\nSmoke pipeline: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
