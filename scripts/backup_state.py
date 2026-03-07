"""Create filesystem backup for state DB, vault, and index directories."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def _sqlite_backup(source_db: Path, dest_db: Path) -> None:
    src = sqlite3.connect(str(source_db))
    try:
        dst = sqlite3.connect(str(dest_db))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup telegram-obsidian state")
    parser.add_argument("--state-db", required=True)
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    state_db = Path(args.state_db).resolve()
    vault_dir = Path(args.vault_dir).resolve()
    index_dir = Path(args.index_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_root = out_dir / f"backup-{stamp}"
    backup_root.mkdir(parents=True, exist_ok=False)

    _sqlite_backup(state_db, backup_root / "state.sqlite3")
    shutil.copytree(vault_dir, backup_root / "vault", dirs_exist_ok=True)
    shutil.copytree(index_dir, backup_root / "index", dirs_exist_ok=True)
    print(str(backup_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

