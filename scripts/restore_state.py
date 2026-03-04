"""Restore state DB, vault, and index directories from a backup folder."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _replace_dir(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, dirs_exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore telegram-obsidian state")
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--state-db", required=True)
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--index-dir", required=True)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow destructive overwrite of target data",
    )
    args = parser.parse_args()

    if not args.force:
        raise SystemExit("Refusing to restore without --force.")

    backup_dir = Path(args.backup_dir).resolve()
    source_db = backup_dir / "state.sqlite3"
    source_vault = backup_dir / "vault"
    source_index = backup_dir / "index"
    if not source_db.exists() or not source_vault.exists() or not source_index.exists():
        raise SystemExit("Backup directory is incomplete: expected state.sqlite3, vault/, index/.")

    state_db = Path(args.state_db).resolve()
    vault_dir = Path(args.vault_dir).resolve()
    index_dir = Path(args.index_dir).resolve()

    state_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, state_db)
    _replace_dir(source_vault, vault_dir)
    _replace_dir(source_index, index_dir)
    print("restore-complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

