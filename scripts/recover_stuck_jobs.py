"""Recover stale jobs from processing state to retry."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.infra.storage import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover stuck processing jobs")
    parser.add_argument("--db", required=True, help="Path to bot state sqlite database")
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=600,
        help="Recover jobs stuck longer than this age",
    )
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    store = StateStore(Path(args.db))
    try:
        store.initialize()
        recovered = store.recover_stuck_jobs(
            max_processing_age_seconds=args.max_age_seconds,
            limit=args.limit,
        )
        print(f"recovered={recovered}")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())

