"""Telegram command handlers."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.bot.auth import is_authorized_user
from src.infra.storage import StateStore


def build_command_router(store: StateStore, allowed_user_id: int) -> Router:
    router = Router(name="commands")

    def _authorized(message: Message) -> bool:
        incoming = message.from_user.id if message.from_user else None
        return is_authorized_user(
            incoming_user_id=incoming,
            allowed_user_id=allowed_user_id,
        )

    @router.message(Command("start"))
    async def start_handler(message: Message) -> None:
        if not _authorized(message):
            await message.answer("Unauthorized")
            return
        await message.answer(
            "Authorized intake bot is active. Send text/link with optional hashtags. Default action is #save."
        )

    @router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        if not _authorized(message):
            await message.answer("Unauthorized")
            return

        counts = store.status_counts()
        if not counts:
            await message.answer("Queue is empty.")
            return

        parts = [f"{key}={value}" for key, value in sorted(counts.items())]
        await message.answer("Queue status: " + ", ".join(parts))

    return router
