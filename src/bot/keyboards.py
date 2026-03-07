"""Persistent reply keyboards for Telegram bot UX."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from src.bot.miniapp import build_mini_app_url


def build_quick_actions_keyboard(mini_app_base_url: str = "") -> ReplyKeyboardMarkup:
    mini_app_url = build_mini_app_url(mini_app_base_url, screen="home")

    rows: list[list[KeyboardButton]] = [
        [
            KeyboardButton(text="➕ Добавить"),
            KeyboardButton(text="🔎 Найти"),
            KeyboardButton(text="⚙️ Управление"),
        ],
    ]
    if mini_app_url:
        rows.append([KeyboardButton(text="📲 База", web_app=WebAppInfo(url=mini_app_url))])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Отправь текст, ссылку или нажми кнопку",
    )
