"""Weekly health check for telegram-obsidian + Obsidian plugins."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run weekly health checks.")
    parser.add_argument("--state-db", type=Path, required=True, help="Path to bot_state.sqlite3")
    parser.add_argument("--vault-dir", type=Path, required=True, help="Path to vault with markdown notes")
    parser.add_argument(
        "--obsidian-dir",
        type=Path,
        required=True,
        help="Path to vault/.obsidian directory",
    )
    return parser.parse_args()


def _check_sqlite(db_path: Path) -> tuple[bool, list[str]]:
    if not db_path.exists():
        return False, [f"state db missing: {db_path}"]
    try:
        conn = sqlite3.connect(str(db_path))
        integrity = conn.execute("PRAGMA quick_check").fetchone()
        row = conn.execute(
            "SELECT status, COUNT(*) FROM jobs_mt GROUP BY status ORDER BY status"
        ).fetchall()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        return False, [f"sqlite check failed: {exc}"]

    issues: list[str] = []
    if not integrity or integrity[0] != "ok":
        issues.append(f"sqlite quick_check is not ok: {integrity}")

    status_report = ", ".join(f"{status}={count}" for status, count in row) or "empty queue"
    return len(issues) == 0, [f"queue status: {status_report}", *issues]


def _check_vault_notes(vault_dir: Path) -> tuple[bool, str]:
    if not vault_dir.exists():
        return False, f"vault dir missing: {vault_dir}"
    count = sum(1 for _ in vault_dir.rglob("*.md"))
    if count == 0:
        return False, f"no notes found in vault: {vault_dir}"
    return True, f"notes found: {count}"


def _check_plugins(obsidian_dir: Path) -> tuple[bool, list[str]]:
    community_file = obsidian_dir / "community-plugins.json"
    plugins_root = obsidian_dir / "plugins"
    if not community_file.exists():
        return False, [f"missing file: {community_file}"]

    try:
        enabled = json.loads(community_file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, [f"invalid community-plugins.json: {exc}"]

    issues: list[str] = []
    checks: list[str] = []
    if not isinstance(enabled, list):
        return False, ["community-plugins.json must contain a JSON array"]

    for plugin_id in enabled:
        plugin_dir = plugins_root / str(plugin_id)
        manifest = plugin_dir / "manifest.json"
        main_js = plugin_dir / "main.js"
        if not plugin_dir.exists():
            issues.append(f"missing plugin dir: {plugin_id}")
            continue
        if not manifest.exists():
            issues.append(f"missing manifest.json: {plugin_id}")
        if not main_js.exists():
            issues.append(f"missing main.js: {plugin_id}")
        checks.append(f"ok: {plugin_id}")

    return len(issues) == 0, [*checks, *issues]


def main() -> int:
    args = _parse_args()
    ok = True

    db_ok, db_details = _check_sqlite(args.state_db)
    notes_ok, notes_detail = _check_vault_notes(args.vault_dir)
    plugins_ok, plugins_details = _check_plugins(args.obsidian_dir)

    print("[db]")
    for line in db_details:
        print(f"- {line}")
    print("[vault]")
    print(f"- {notes_detail}")
    print("[plugins]")
    for line in plugins_details:
        print(f"- {line}")

    ok = db_ok and notes_ok and plugins_ok
    print(f"[result] {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
