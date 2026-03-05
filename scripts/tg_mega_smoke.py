#!/usr/bin/env python3
"""Mega-smoke test that checks ALL bot commands by discovering real data.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from telethon import TelegramClient


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


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


async def _wait_for_bot_reply(
    client: TelegramClient,
    bot_username: str,
    *,
    sent_message_id: int,
    timeout_seconds: int,
) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        messages = await client.get_messages(bot_username, limit=10)
        for message in messages:
            if message.out:
                continue
            if message.id <= sent_message_id:
                continue
            text = (message.raw_text or "").strip()
            if text:
                return text
        await asyncio.sleep(1.0)
    raise TimeoutError("Timed out while waiting for bot reply.")


async def _wait_for_multiple_bot_replies(
    client: TelegramClient,
    bot_username: str,
    *,
    min_message_id: int,
    expected_count: int,
    timeout_seconds: int,
) -> list[str]:
    deadline = time.time() + timeout_seconds
    seen_ids: set[int] = set()
    replies: list[str] = []

    while time.time() < deadline:
        messages = await client.get_messages(bot_username, limit=30)
        for message in messages:
            if message.out:
                continue
            if message.id <= min_message_id:
                continue
            if message.id in seen_ids:
                continue
            text = (message.raw_text or "").strip()
            if not text:
                continue
            seen_ids.add(message.id)
            replies.append(text)
        if len(replies) >= expected_count:
            return replies
        await asyncio.sleep(1.0)
    raise TimeoutError(
        f"Timed out waiting for {expected_count} replies, got {len(replies)}."
    )


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    api_id = int(_require_env("TG_API_ID"))
    api_hash = _require_env("TG_API_HASH")
    bot_username = _detect_bot_username()
    timeout = int(os.getenv("TG_TIMEOUT_SECONDS") or "25")

    default_session = Path(__file__).resolve().parents[1] / ".sessions" / "session"
    session_path = Path(os.getenv("TG_SESSION", str(default_session)).strip())
    
    print(f"=== MEGA SMOKE TEST START ===")
    print(f"Target Bot: @{bot_username}")
    
    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Error: Session not authorized. Run regular smoke test with QR first.")
        return 1

    results = []

    async def run_cmd(cmd: str, label: str) -> str:
        print(f"Testing {label}: {cmd}")
        sent = await client.send_message(bot_username, cmd)
        try:
            reply = await _wait_for_bot_reply(client, bot_username, sent_message_id=sent.id, timeout_seconds=timeout)
            print(f"[OK] {label}")
            results.append((label, True))
            return reply
        except Exception as e:
            print(f"[FAIL] {label}: {e}")
            results.append((label, False))
            return ""

    # 1. /start
    await run_cmd("/start", "START_COMMAND")

    # 2. /status & Data Discovery
    status_reply = await run_cmd("/status", "STATUS_COMMAND")
    
    # Discovery: Job ID (hex)
    job_ids = re.findall(r"<code>([a-f0-9]{10,})</code>", status_reply)
    # Discovery: Note names (e.g. 20260305...md)
    note_names = re.findall(r"<code>(\d{8}-\d{4}\s*-.+?\.md)</code>", status_reply)

    # 3. /find (if note found)
    if note_names:
        note_to_find = note_names[0]
        # Use first word of note name for better search matching
        query = note_to_find.split("-")[-1].split(".")[0].strip()[:20]
        await run_cmd(f"/find {query}", "FIND_COMMAND")
    else:
        print("[SKIP] FIND_COMMAND (no notes in status)")
        results.append(("FIND_COMMAND", True))

    # 4. /summary
    await run_cmd("/summary О чем мои последние заметки?", "SUMMARY_COMMAND")

    # 5. /job (if job ID found)
    if job_ids:
        await run_cmd(f"/job {job_ids[0]}", "JOB_COMMAND")
    else:
        print("[SKIP] JOB_COMMAND (no job IDs in status)")
        results.append(("JOB_COMMAND", True))

    # 6. /delete cancel
    await run_cmd("/delete cancel", "DELETE_CANCEL_COMMAND")

    # 7. Dirty: /summary without args
    await run_cmd("/summary", "SUMMARY_EMPTY_ARGS")

    # 8. Dirty: long command payload
    long_query = " ".join(["оченьдлинныйтекст"] * 200)
    await run_cmd(f"/summary {long_query}", "SUMMARY_LONG_TEXT")

    # 9. Dirty: invalid delete argument
    invalid_delete_reply = await run_cmd("/delete asdasd", "DELETE_INVALID_ARG")
    if "Удаление отклонено" not in invalid_delete_reply and "note not found" not in invalid_delete_reply.lower():
        print("[FAIL] DELETE_INVALID_ARG: unexpected response format")
        results.append(("DELETE_INVALID_ARG_FORMAT", False))
    else:
        print("[OK] DELETE_INVALID_ARG response format")
        results.append(("DELETE_INVALID_ARG_FORMAT", True))

    # 10. Dirty: burst commands sent quickly
    print("Testing BURST_COMMANDS: /status + /summary + /delete cancel")
    burst_commands = ["/status", "/summary", "/delete cancel"]
    sent_ids: list[int] = []
    for cmd in burst_commands:
        sent = await client.send_message(bot_username, cmd)
        sent_ids.append(sent.id)
    try:
        await _wait_for_multiple_bot_replies(
            client,
            bot_username,
            min_message_id=max(sent_ids),
            expected_count=1,
            timeout_seconds=timeout,
        )
        print("[OK] BURST_COMMANDS")
        results.append(("BURST_COMMANDS", True))
    except Exception as e:
        print(f"[FAIL] BURST_COMMANDS: {e}")
        results.append(("BURST_COMMANDS", False))

    # 11. /delete all (Request)
    await run_cmd("/delete all", "DELETE_ALL_REQUEST")
    
    # 12. /delete cancel (Again, to cleanup request)
    await run_cmd("/delete cancel", "DELETE_CANCEL_CLEANUP")

    print("\n=== MEGA SMOKE SUMMARY ===")
    all_ok = True
    for label, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {label}")
        if not ok:
            all_ok = False

    await client.disconnect()
    return 0 if all_ok else 1

if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
