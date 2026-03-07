#!/usr/bin/env python3
"""Deterministic Telegram E2E flow with chat replies and side-effect checks."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telethon import TelegramClient

from src.bot.auth import build_tenant_context
from src.infra.storage import StateStore
from src.obsidian.search import find_notes


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _detect_bot_username() -> str:
    explicit = (os.getenv("TG_BOT_USERNAME") or "").strip().lstrip("@")
    if explicit:
        return explicit

    token = (os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_BOT_TOKEN") or "").strip()
    if not token:
        raise SystemExit("Missing TG_BOT_USERNAME (or TELEGRAM_TOKEN/TG_BOT_TOKEN for auto-detect).")

    url = f"https://api.telegram.org/bot{token}/getMe"
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok") or not payload.get("result"):
        raise SystemExit("Failed to auto-detect bot username from token.")
    return str(payload["result"].get("username") or "").strip()


def _runtime_path(env_name: str, fallback_relative: str) -> Path:
    raw = (os.getenv(env_name) or "").strip()
    if raw and not raw.startswith("/srv/") and not raw.startswith("/data/"):
        return Path(raw).resolve()
    return (_project_root() / fallback_relative).resolve()


def _session_path() -> Path:
    default_session = _project_root() / ".sessions" / "session"
    return Path(os.getenv("TG_SESSION", str(default_session)).strip()).resolve()


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: expected to find {needle!r} in reply: {text!r}")


async def _wait_for_bot_reply(
    client: TelegramClient,
    bot_username: str,
    *,
    sent_message_id: int,
    timeout_seconds: int,
) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        messages = await client.get_messages(bot_username, limit=20)
        for message in messages:
            if message.out or message.id <= sent_message_id:
                continue
            text = _normalize(message.raw_text or "")
            if text:
                return text
        await asyncio.sleep(1.0)
    raise TimeoutError("Timed out while waiting for bot reply.")


async def _send_and_expect_reply(
    client: TelegramClient,
    bot_username: str,
    command: str,
    *,
    timeout_seconds: int,
    label: str,
) -> str:
    print(f"Testing {label}: {command}")
    sent = await client.send_message(bot_username, command)
    reply = await _wait_for_bot_reply(
        client,
        bot_username,
        sent_message_id=sent.id,
        timeout_seconds=timeout_seconds,
    )
    print(f"[OK] {label}: {reply[:220]}")
    return reply


def _wait_for_note_persisted(
    store: StateStore,
    *,
    tenant_id: str,
    vault_path: Path,
    marker: str,
    timeout_seconds: int,
) -> dict[str, str]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        matches = find_notes(vault_path, marker, limit=5)
        notes = store.list_notes(tenant_id=tenant_id)
        notes_by_file = {str(item["file_name"]): item for item in notes}
        for match in matches:
            file_name = str(match["file_name"])
            note_row = notes_by_file.get(file_name)
            if note_row is None:
                continue
            note_path = (vault_path / file_name).resolve()
            job = store.get_job_status(str(note_row["last_job_id"]), tenant_id=tenant_id)
            if note_path.exists() and job and str(job.get("status")) == "done":
                return {
                    "file_name": file_name,
                    "note_id": str(note_row["note_id"]),
                    "content_fingerprint": str(note_row["content_fingerprint"]),
                    "job_id": str(note_row["last_job_id"]),
                    "note_path": str(note_path),
                }
        time.sleep(1.0)
    raise TimeoutError("Timed out waiting for note persistence in vault + SQLite.")


def _wait_for_note_deleted(
    store: StateStore,
    *,
    tenant_id: str,
    vault_path: Path,
    file_name: str,
    marker: str,
    timeout_seconds: int,
) -> None:
    deadline = time.time() + timeout_seconds
    note_path = (vault_path / file_name).resolve()
    while time.time() < deadline:
        still_in_db = any(str(item["file_name"]) == file_name for item in store.list_notes(tenant_id=tenant_id))
        still_in_search = bool(find_notes(vault_path, marker, limit=1))
        if not note_path.exists() and not still_in_db and not still_in_search:
            return
        time.sleep(1.0)
    raise TimeoutError("Timed out waiting for note deletion from vault + SQLite.")


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    api_id = int(_require_env("TG_API_ID"))
    api_hash = _require_env("TG_API_HASH")
    bot_username = _detect_bot_username()
    timeout = int(os.getenv("TG_TIMEOUT_SECONDS") or "35")
    state_db_path = _runtime_path("STATE_DIR", ".data/state") / "bot_state.sqlite3"
    vault_path = _runtime_path("VAULT_PATH", "local_obsidian_inbox")
    session_path = _session_path()

    print("=== DETERMINISTIC TELEGRAM E2E START ===")
    print(f"Target Bot: @{bot_username}")
    print(f"State DB: {state_db_path}")
    print(f"Vault: {vault_path}")

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Error: Session not authorized. Run tg_smoke_test.py login flow first.")
        return 1

    me = await client.get_me()
    if me is None or getattr(me, "id", None) is None:
        print("Error: failed to resolve Telegram account identity.")
        return 1

    tenant_id = build_tenant_context(int(me.id)).tenant_id
    marker = f"codex-e2e-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    intake_text = f"{marker} #save deterministic telegram e2e note"

    store = StateStore(state_db_path)
    store.initialize()

    results: list[tuple[str, bool]] = []

    try:
        start_reply = await _send_and_expect_reply(
            client,
            bot_username,
            "/start",
            timeout_seconds=timeout,
            label="START_COMMAND",
        )
        _assert_contains(start_reply, "Obsidian", "START_COMMAND")
        results.append(("START_COMMAND", True))

        status_reply = await _send_and_expect_reply(
            client,
            bot_username,
            "/status",
            timeout_seconds=timeout,
            label="STATUS_COMMAND",
        )
        _assert_contains(status_reply, "краткая сводка", "STATUS_COMMAND")
        results.append(("STATUS_COMMAND", True))

        intake_reply = await _send_and_expect_reply(
            client,
            bot_username,
            intake_text,
            timeout_seconds=timeout,
            label="INGEST_TEXT",
        )
        if not intake_reply:
            raise AssertionError("INGEST_TEXT: bot reply is empty.")
        results.append(("INGEST_TEXT", True))

        note_info = _wait_for_note_persisted(
            store,
            tenant_id=tenant_id,
            vault_path=vault_path,
            marker=marker,
            timeout_seconds=70,
        )
        print(f"[OK] NOTE_PERSISTED: {note_info['file_name']}")
        results.append(("NOTE_PERSISTED", True))

        job_status = store.get_job_status(note_info["job_id"], tenant_id=tenant_id)
        if not job_status or str(job_status.get("status")) != "done":
            raise AssertionError(f"JOB_DONE: unexpected status {job_status!r}")
        print(f"[OK] JOB_DONE: {note_info['job_id']}")
        results.append(("JOB_DONE", True))

        find_reply = await _send_and_expect_reply(
            client,
            bot_username,
            f"/find {marker}",
            timeout_seconds=timeout,
            label="FIND_CREATED_NOTE",
        )
        _assert_contains(find_reply, note_info["file_name"], "FIND_CREATED_NOTE")
        results.append(("FIND_CREATED_NOTE", True))

        summary_reply = await _send_and_expect_reply(
            client,
            bot_username,
            f"/summary {marker}",
            timeout_seconds=timeout,
            label="SUMMARY_CREATED_NOTE",
        )
        if "не могу ответить уверенно" in summary_reply:
            raise AssertionError("SUMMARY_CREATED_NOTE: summary did not ground on created note.")
        _assert_contains(summary_reply, note_info["file_name"], "SUMMARY_CREATED_NOTE")
        results.append(("SUMMARY_CREATED_NOTE", True))

        long_query = " ".join(["оченьдлинныйтекст"] * 200)
        long_reply = await _send_and_expect_reply(
            client,
            bot_username,
            f"/summary {long_query}",
            timeout_seconds=timeout,
            label="SUMMARY_LONG_TEXT",
        )
        _assert_contains(long_reply, "Слишком длинный запрос", "SUMMARY_LONG_TEXT")
        results.append(("SUMMARY_LONG_TEXT", True))

        delete_cancel_reply = await _send_and_expect_reply(
            client,
            bot_username,
            "/delete cancel",
            timeout_seconds=timeout,
            label="DELETE_CANCEL",
        )
        if "Нечего отменять" not in delete_cancel_reply and "отменено" not in delete_cancel_reply:
            raise AssertionError(f"DELETE_CANCEL: unexpected reply {delete_cancel_reply!r}")
        results.append(("DELETE_CANCEL", True))

        delete_reply = await _send_and_expect_reply(
            client,
            bot_username,
            f"/delete {note_info['file_name']}",
            timeout_seconds=timeout,
            label="DELETE_CREATED_NOTE",
        )
        _assert_contains(delete_reply, "Заметка удалена", "DELETE_CREATED_NOTE")
        results.append(("DELETE_CREATED_NOTE", True))

        _wait_for_note_deleted(
            store,
            tenant_id=tenant_id,
            vault_path=vault_path,
            file_name=note_info["file_name"],
            marker=marker,
            timeout_seconds=30,
        )
        print("[OK] NOTE_DELETED")
        results.append(("NOTE_DELETED", True))

        find_deleted_reply = await _send_and_expect_reply(
            client,
            bot_username,
            f"/find {marker}",
            timeout_seconds=timeout,
            label="FIND_AFTER_DELETE",
        )
        _assert_contains(find_deleted_reply, "точных совпадений пока нет", "FIND_AFTER_DELETE")
        results.append(("FIND_AFTER_DELETE", True))

        print("\n=== DETERMINISTIC TELEGRAM E2E SUMMARY ===")
        for label, ok in results:
            print(f"{'PASS' if ok else 'FAIL'}: {label}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        print("\n=== DETERMINISTIC TELEGRAM E2E SUMMARY ===")
        for label, ok in results:
            print(f"{'PASS' if ok else 'FAIL'}: {label}")
        return 1
    finally:
        store.close()
        await client.disconnect()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
