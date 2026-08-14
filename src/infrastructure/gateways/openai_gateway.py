from typing import Any
from openai import AsyncOpenAI

from src.config.settings import settings


class OpenAiGateway:
    """Шлюз для генерации контента через официальный OpenAI API (GPT-4o)."""

    def __init__(self, openai_client: AsyncOpenAI):
        self._client = openai_client
        self._model = settings.OPENAI.MODEL

    async def generate_completion_with_reasoning(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "high"
    ) -> tuple[str, str]:
        """Генерирует ответ через OpenAI API."""
        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Если content пришел в формате KIE [{'type': 'text', 'text': '...'}] -> распаковываем в текст
            if isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                text_content = "\n".join(text_parts) if text_parts else str(content)
            else:
                text_content = str(content)

            formatted_messages.append({"role": role, "content": text_content})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=formatted_messages,
            temperature=0.7,
        )

        message = response.choices[0].message
        content = message.content or ""
        reasoning = getattr(message, "reasoning_content", "") or ""

        return content, reasoning

    async def generate_completion(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "high"
    ) -> str:
        """Возвращает только текст ответа."""
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

        # src/infrastructure/gateways/openai_gateway.py

    async def summarize_site(self, parsed_data: dict[str, Any]) -> str:
        """Анализирует метаданные, заголовки, таблицы, FAQ и сплошной текст body."""
        seo = parsed_data.get('seo_meta', {})
        struct = parsed_data.get('content_structure', {})

        headings_list = [f"- [{h.get('level', 'H')}] {h.get('text', '')}" for h in struct.get('headings', [])]
        headings_text = "\n".join(headings_list) or "Нет данных"

        tables_text = "\n---\n".join(struct.get('tables', [])) or "Нет таблиц"
        faq_text = "\n---\n".join(struct.get('faq_blocks', [])) or "Нет явных FAQ блоков"

        prompt = f"""
        Проведи глубокий коммерческий и LSA-анализ страницы конкурента {parsed_data.get('url')}:

        1. МЕТАДАННЫЕ СТРАНИЦЫ:
        - Title: "{seo.get('title', parsed_data.get('title'))}"
        - Description: "{seo.get('description', parsed_data.get('description'))}"

        2. СТРУКТУРА И ИЕРАРХИЯ ЗАГОЛОВКОВ (H1-H4):
        {headings_text}

        3. НАЙДЕННЫЕ ТАБЛИЦЫ (Цены, Сравнения, Характеристики):
        {tables_text}

        4. НАЙДЕННЫЕ ВОПРОСЫ И ОТВЕТЫ (FAQ):
        {faq_text}

        5. ПОЛНЫЙ ЦЕНТРАЛЬНЫЙ ТЕКСТ СТРАНИЦЫ (BODY):
        {parsed_data.get('body_text', '')[:4000]}

        ЗАДАЧИ АНАЛИЗА ПО МЕТОДИЧКЕ:
        1. КОММЕРЧЕСКИЕ ФАКТОРЫ: выдели точные цены из таблиц/текста, гарантии, призывы к действию (CTA), этапы работ, коммерческие пакеты.
        2. LSA / LSI СЕМАНТИКА: выпиши ключевые тематические термины, коммерческие «хвосты» и профессиональную лексику ниши, использованную на этой странице.
        3. СИЛЬНЫЕ И СЛАБЫЕ СТОРОНЫ СТРАНИЦЫ: что сделано отлично и каких элементов/смыслов не хватает.
        4. ВЫЖИМКА ДЛЯ НАШЕЙ СТАТЬИ: 3-5 главных тезисов и смысловых блоков, которые обязательно нужно применить в нашей статье.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.generate_completion(messages, reasoning_effort="high")