"""Telegram end-to-end smoke test using a real user session.

Usage:
  TG_API_ID=... TG_API_HASH=... TG_PHONE=+123... TG_BOT_USERNAME=my_bot python scripts/tg_smoke_test.py

Optional:
  TG_SESSION=/path/to/session
  TG_TIMEOUT_SECONDS=25
  TG_COMMANDS="/start|/status|/delete cancel"
"""

from __future__ import annotations

import asyncio
import json
import os
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


def _commands_from_env() -> list[str]:
    raw = (os.getenv("TG_COMMANDS") or "").strip()
    if not raw:
        return ["/start", "/status", "/delete cancel"]
    items = [item.strip() for item in raw.split("|")]
    return [item for item in items if item]


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
    username = str(payload["result"].get("username") or "").strip()
    if not username:
        raise SystemExit("Bot username is empty in getMe response.")
    return username


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


async def main() -> int:
    api_id_raw = _require_env("TG_API_ID")
    api_hash = _require_env("TG_API_HASH")
    phone = _require_env("TG_PHONE")
    bot_username = _detect_bot_username()
    timeout_seconds = int((os.getenv("TG_TIMEOUT_SECONDS") or "25").strip())
    commands = _commands_from_env()
    login_code = (os.getenv("TG_LOGIN_CODE") or "").strip()
    twofa_password = (os.getenv("TG_2FA_PASSWORD") or "").strip()

    session_path = Path(
        (os.getenv("TG_SESSION") or str(Path.home() / ".telegram-smoke" / "session")).strip()
    )
    session_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise SystemExit("TG_API_ID must be an integer.") from exc

    print(f"Session file: {session_path}")
    print(f"Target bot: @{bot_username}")
    print(f"Commands: {commands}")
    print()

    client = TelegramClient(str(session_path), api_id, api_hash)
    if login_code:
        await client.start(
            phone=phone,
            code_callback=lambda: login_code,
            password=twofa_password or None,
        )
    else:
        await client.start(phone=phone)

    me = await client.get_me()
    display = (me.username or f"id={me.id}") if me else "unknown"
    print(f"Authorized as: {display}")
    print()

    ok_count = 0
    for command in commands:
        print(f">>> {command}")
        sent = await client.send_message(bot_username, command)
        try:
            reply = await _wait_for_bot_reply(
                client,
                bot_username,
                sent_message_id=sent.id,
                timeout_seconds=timeout_seconds,
            )
            print("<<<", reply.replace("\n", " | "))
            ok_count += 1
        except TimeoutError as exc:
            print("!!!", str(exc))
        print()

    await client.disconnect()
    print(f"Completed: {ok_count}/{len(commands)} replies received.")
    return 0 if ok_count == len(commands) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)
