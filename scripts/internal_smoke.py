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


def _run(title: str, args: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"\n== {title} ==")
    print(" ".join(args))
    result = subprocess.run(args, cwd=ROOT, env=env)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    python = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

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
            "tests/test_job_command.py",
            "tests/test_delete_confirmation_flow.py",
            "tests/test_telegram_media_router.py",
            "tests/test_phase4.py",
        ],
        env=env,
    )

    print("\nSmoke pipeline: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
