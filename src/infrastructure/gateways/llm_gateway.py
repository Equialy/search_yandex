from typing import Any
from openai import AsyncOpenAI
from src.config.settings import settings


class LLMGateway:
    def __init__(self, openai_client: AsyncOpenAI):
        self._client = openai_client
        self._model = settings.OPENAI.MODEL

    async def summarize_site(self, parsed_data: dict[str, Any]) -> str:
        prompt = f"""
        Проанализируй граф структуры и контент сайта:
        Заголовок: {parsed_data.get('title')}
        Иерархия заголовков (Граф): {parsed_data.get('graph', {}).get('hierarchy')}
        Текст: {parsed_data.get('content_sample')}

        Сформулируй 3-5 главных тезисов и уникальных мыслей этого сайта.
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content or ""

    async def completion_with_history(
            self,
            history: list[dict[str, Any]],
            user_prompt: str
    ) -> tuple[str, list[dict[str, Any]]]:
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_prompt})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=updated_history
        )

        answer = response.choices[0].message.content or ""
        updated_history.append({"role": "assistant", "content": answer})

        return answer, updated_history