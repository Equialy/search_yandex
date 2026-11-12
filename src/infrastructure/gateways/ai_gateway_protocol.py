
from typing import Any, Protocol


class AiTextGatewayProtocol(Protocol):
    """Единый интерфейс для текстовых LLM-шлюзов (Gemini, DeepSeek и др.)."""

    async def generate_completion_with_reasoning(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "low",
    ) -> tuple[str, str]:
        """Возвращает кортеж (текст_ответа, рассуждения_модели)."""
        ...

    async def generate_completion(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "low",
    ) -> str:
        """Возвращает только итоговый сгенерированный текст."""
        ...

    async def completion_with_history(
        self,
        history: list[dict[str, Any]],
        user_prompt: str,
        reasoning_effort: str = "low",
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """Диалог в контексте истории."""
        ...

    async def summarize_site(self, parsed_data: dict[str, Any]) -> str:
        """Глубокий LSA и коммерческий анализ конкурента."""
        ...