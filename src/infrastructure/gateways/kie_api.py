from typing import Any
import httpx

from src.config.settings import settings


class KieApiGateway:
    """Шлюз для генерации контента через KIE.AI API (GPT 5.2)."""

    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._api_key = settings.kie.API_KEY
        self._base_url = settings.kie.KIE_BASE_URL.rstrip('/')
        self._endpoint = "/gpt-5-2/v1/chat/completions"

    def _format_messages_for_kie(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Преобразует стандартный формат сообщений OpenAI [{'role': 'user', 'content': 'str'}]
        в формат KIE.AI [{'role': 'user', 'content': [{'type': 'text', 'text': 'str'}]}]
        """
        formatted = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, str):
                formatted_content = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                formatted_content = content
            else:
                formatted_content = [{"type": "text", "text": str(content)}]

            formatted.append({
                "role": role,
                "content": formatted_content
            })
        return formatted

    async def generate_completion_with_reasoning(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "high"
    ) -> tuple[str, str]:
        """Возвращает (текст ответа, ход рассуждений нейросети)."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "messages": self._format_messages_for_kie(messages),
            "reasoning_effort": reasoning_effort
        }

        url = f"{self._base_url}{self._endpoint}"

        response = await self._client.post(url, json=payload, headers=headers, timeout=120.0)
        response.raise_for_status()

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"Пустой ответ от KIE.AI API: {data}")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""

        return content, reasoning

    async def generate_completion(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "high"
    ) -> str:
        """Возвращает только текст ответа (без рассуждений)."""
        content, _ = await self.generate_completion_with_reasoning(
            messages=messages,
            reasoning_effort=reasoning_effort
        )
        return content

    async def completion_with_history(
        self,
        history: list[dict[str, Any]],
        user_prompt: str
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """Возвращает (текст ответа, рассуждения, обновленная история)."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_prompt})

        content, reasoning = await self.generate_completion_with_reasoning(
            updated_history,
            reasoning_effort="high"
        )

        updated_history.append({
            "role": "assistant",
            "content": content,
            "reasoning": reasoning
        })

        return content, reasoning, updated_history

    async def summarize_site(self, parsed_data: dict[str, Any]) -> str:
        """Анализирует граф и контент сайта для получения выжимки."""
        prompt = f"""
        Проанализируй граф структуры и контент сайта:
        Заголовок: {parsed_data.get('title')}
        Иерархия заголовков (Граф): {parsed_data.get('graph', {}).get('hierarchy')}
        Текст: {parsed_data.get('content_sample')}

        Сформулируй 3-5 главных тезисов и уникальных мыслей этого сайта.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.generate_completion(messages, reasoning_effort="high")