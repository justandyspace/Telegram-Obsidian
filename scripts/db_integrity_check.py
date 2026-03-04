"""Run SQLite integrity and schema checks for the state database."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.infra.storage import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Run state DB integrity check")
    parser.add_argument("--db", required=True, help="Path to bot state sqlite database")
    args = parser.parse_args()

    store = StateStore(Path(args.db))
    try:
        store.initialize()
        ok, details = store.integrity_check()
        version = store.schema_version()
        if ok:
            print(f"ok schema_version={version}")
            return 0
        print(f"failed schema_version={version} details={details}")
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())

