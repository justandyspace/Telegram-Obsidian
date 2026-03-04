import os
import asyncio
import aiofiles
from datetime import datetime
from aiogram import Bot, Dispatcher, types
import google.generativeai as genai

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "ВАШ_ТОКЕН_ИЗ_BOTFATHER")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "ВАШ_API_KEY_ИЗ_AI_STUDIO")
VAULT_PATH = os.getenv("VAULT_PATH", os.path.join(os.path.dirname(__file__), "..", "local_obsidian_inbox"))

dp = Dispatcher()

SYSTEM_PROMPT = """
Ты — ассистент по управлению знаниями в Obsidian.
Преврати входящее сообщение в заметку Markdown.
Определи подходящий заголовок.
Добавь YAML-метаданные: дату и теги.
Верни ТОЛЬКО содержимое файла .md без пояснений.
"""


def _validate_config() -> None:
    if (not TELEGRAM_TOKEN) or TELEGRAM_TOKEN.startswith("ВАШ_"):
        raise RuntimeError("Set TELEGRAM_TOKEN env var or replace placeholder in file")
    if (not GEMINI_API_KEY) or GEMINI_API_KEY.startswith("ВАШ_"):
        raise RuntimeError("Set GEMINI_API_KEY env var or replace placeholder in file")


def _make_filename(text: str) -> str:
    safe_title = "".join(c for c in text[:20] if c.isalnum() or c in (" ", "-", "_"))
    safe_title = safe_title.rstrip() or "note"
    ts = datetime.now().strftime("%Y-%m-%d")
    return f"{ts}_{safe_title}.md"


@dp.message()
async def process_message(message: types.Message):
    if not message.text:
        return

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"{SYSTEM_PROMPT}\n\nТекст пользователя: {message.text}"
        response = model.generate_content(prompt)
        md_content = (response.text or "").strip()

        os.makedirs(VAULT_PATH, exist_ok=True)
        filename = _make_filename(message.text)
        file_path = os.path.join(VAULT_PATH, filename)
        async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(md_content)

        await message.answer(f"Заметка сохранена: {filename}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


async def main():
    _validate_config()
    bot = Bot(token=TELEGRAM_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


