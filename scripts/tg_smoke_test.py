#!/usr/bin/env python3
"""Telegram end-to-end smoke test using a real user session.

Usage:
  TG_API_ID=... TG_API_HASH=... TG_PHONE=+123... TG_BOT_USERNAME=my_bot python scripts/tg_smoke_test.py

Optional:
  TG_SESSION=/path/to/session
  TG_TIMEOUT_SECONDS=25
  TG_COMMANDS="/start|/status|/delete cancel"
  TG_AUTH_MODE="request-code" | "complete-login" | "status" | "run"
  TG_LOGIN_METHOD="qr"
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from pathlib import Path

import qrcode
import qrcode.image.svg
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError


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
    login_method = (os.getenv("TG_LOGIN_METHOD") or "").strip().lower()
    auth_mode = (os.getenv("TG_AUTH_MODE") or "run").strip().lower()

    # Use project-local session folder to avoid permission issues
    default_session = Path(__file__).resolve().parents[1] / ".sessions" / "session"
    session_path = Path(os.getenv("TG_SESSION", str(default_session)).strip())

    # CRITICAL FIX: Ensure parent directory exists!
    session_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise SystemExit("TG_API_ID must be an integer.") from exc

    print(f"Session file: {session_path}")
    print(f"Target bot: @{bot_username}")
    if auth_mode == "run":
        print(f"Commands: {commands}")
    print()

    client = TelegramClient(str(session_path), api_id, api_hash)
    auth_meta_path = session_path.with_suffix(".auth.json")

    if auth_mode == "status":
        await client.connect()
        try:
            authorized = await client.is_user_authorized()
            if authorized:
                me = await client.get_me()
                display = (getattr(me, 'username', '') or getattr(me, 'id', 'unknown')) if me else "unknown"
                print(f"[STATUS] AUTHORIZED as {display}")
                return 0
            print("[STATUS] NOT AUTHORIZED")
            return 1
        finally:
            await client.disconnect()

    if auth_mode == "request-code":
        await client.connect()
        try:
            print(f"Requesting login code for phone: {phone}")
            sent = await client.send_code_request(phone)

            code_type_name = type(sent.type).__name__
            timeout_val = getattr(sent.type, 'timeout', None)
            next_type_obj = getattr(sent, 'next_type', None)
            next_type_name = type(next_type_obj).__name__ if next_type_obj else "None"

            print("\n--- Code Sent Info ---")
            print(f"Type: {code_type_name}")
            print(f"Timeout: {timeout_val} seconds")
            print(f"Next Type (Fallback): {next_type_name}")
            print("----------------------\n")

            if "App" in code_type_name:
                print(">>> WARNING: The code was sent to your existing Telegram App (mobile/desktop).")
                print(">>> It did NOT arrive via SMS.")
            elif "Sms" in code_type_name:
                print(">>> The code was sent via SMS.")

            auth_meta_path.write_text(
                json.dumps({"phone": phone, "phone_code_hash": sent.phone_code_hash}, ensure_ascii=False),
                encoding="utf-8",
            )
            print("\nNext step: Provide the code via TG_LOGIN_CODE=... and TG_AUTH_MODE=complete-login")
            return 0
        finally:
            await client.disconnect()

    if auth_mode == "complete-login":
        if not auth_meta_path.exists():
            raise SystemExit(f"Missing auth meta file: {auth_meta_path}. Run TG_AUTH_MODE=request-code first.")
        if not login_code:
            raise SystemExit("Missing TG_LOGIN_CODE for complete-login mode.")
        meta = json.loads(auth_meta_path.read_text(encoding="utf-8"))
        await client.connect()
        try:
            try:
                await client.sign_in(
                    phone=str(meta["phone"]),
                    code=login_code,
                    phone_code_hash=str(meta["phone_code_hash"]),
                )
            except SessionPasswordNeededError as exc:
                if not twofa_password:
                    raise SystemExit("2FA password required. Set TG_2FA_PASSWORD.") from exc
                await client.sign_in(password=twofa_password)
            if not await client.is_user_authorized():
                raise SystemExit("Login failed: session is not authorized.")
        finally:
            await client.disconnect()
        print("Login completed successfully. Session saved.")
        return 0

    if login_method == "qr":
        await client.connect()
        if not await client.is_user_authorized():
            try:
                qr_login = await client.qr_login()
            except SessionPasswordNeededError as exc:
                if not twofa_password:
                    raise SystemExit(
                        "2FA password required to start QR login. Set TG_2FA_PASSWORD."
                    ) from exc
                await client.sign_in(password=twofa_password)
                qr_login = await client.qr_login()

            print("Scan this QR in Telegram app: Settings -> Devices -> Link Desktop Device")
            print()
            qr = qrcode.QRCode(border=1)
            qr.add_data(qr_login.url)
            qr.make(fit=True)
            qr_svg_path = Path(
                os.getenv("TG_QR_SVG_PATH") or session_path.parent / "telegram-login-qr.svg"
            )
            qr_svg_path.parent.mkdir(parents=True, exist_ok=True)
            qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(str(qr_svg_path))
            print(f"QR SVG saved to: {qr_svg_path}")
            print("QR URL saved in-session for 120 seconds.")
            print()
            qr.print_ascii(invert=True)
            print()
            try:
                await qr_login.wait(timeout=120)
            except SessionPasswordNeededError as exc:
                if not twofa_password:
                    raise SystemExit("2FA password required for QR login. Set TG_2FA_PASSWORD.") from exc
                await client.sign_in(password=twofa_password)

            if not await client.is_user_authorized():
                raise SystemExit("QR Login failed: session is still not authorized.")
            print("QR Login successful.")

    # Mode: "run" (default) or any unknown fallback
    # Check authorization first to avoid hanging on input() in CI
    await client.connect()
    if not await client.is_user_authorized():
        print("[WARN] Session not authorized. Proceeding with interactive client.start()...")
        await client.start(phone=phone)

    me = await client.get_me()
    display = (getattr(me, 'username', '') or getattr(me, 'id', 'unknown')) if me else "unknown"
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
        raise SystemExit(130) from None
