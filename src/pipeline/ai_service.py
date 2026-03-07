"""AI-powered assistant logic."""

from __future__ import annotations

from typing import Any, cast

from google import genai
from google.genai import types

from src.infra.ai_fallback import is_remote_ai_available, mark_remote_ai_failure, reset_remote_ai
from src.infra.logging import get_logger
from src.infra.resilience import RetryPolicy, async_with_retry

LOGGER = get_logger(__name__)
_AI_SCOPE = "assistant_reply"

# --- SYSTEM PROMPT ---
DEFAULT_ASSISTANT_PROMPT = (
    "Ты — интеллектуальный ассистент по управлению знаниями в Obsidian. "
    "Твоя задача — подтверждать получение информации от пользователя в вежливой и лаконичной манере. "
    "Ты должен: "
    "1. Коротко описать, что именно ты сохранил (например, 'Сохранил ссылку на статью о...', 'Записал твою мысль о...'). "
    "2. Упомянуть ключевые теги, если они явно указаны в сообщении (через #). "
    "3. Быть дружелюбным, но не навязчивым. "
    "4. Избегать технической информации вроде Job ID или внутренних статусов, если пользователь не спросил о них специально. "
    "5. Если в сообщении есть ссылка, подтверди, что ты начал её обработку."
)

class AIService:
    def __init__(
        self,
        api_key: str,
        model_name: str,
        system_instruction: str = DEFAULT_ASSISTANT_PROMPT,
    ) -> None:
        self.model_name = model_name
        self.system_instruction = system_instruction
        self.client: genai.Client | None
        if not api_key:
            LOGGER.warning("GEMINI_API_KEY is missing. AI assistant will be disabled.")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)

    async def generate_reply(self, user_text: str, context_info: str = "") -> str:
        """Generates a human-friendly reply for the user."""
        client = self.client
        if client is None:
            return "Принято. (AI ассистент не настроен)"
        if not is_remote_ai_available(_AI_SCOPE):
            return "Принято. Сохраняю в Obsidian..."

        try:
            prompt = f"Пользователь прислал: {user_text}\n\nКонтекст обработки: {context_info}"

            async def _call_gemini() -> Any:
                return await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                    )
                )

            policy = RetryPolicy(max_attempts=3, base_delay_seconds=1.5, max_delay_seconds=10.0)
            response = await async_with_retry(policy, _call_gemini, exc_types=(Exception,))
            reset_remote_ai(_AI_SCOPE)

            text = str(cast(Any, response).text or "").strip()
            return text or "Принято. Сохраняю в Obsidian..."
        except Exception as exc:
            mark_remote_ai_failure(_AI_SCOPE, exc)
            LOGGER.exception("Failed to generate AI reply")
            return "Принято. Сохраняю в Obsidian..."
