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

    async def summarize_site(self, parsed_data: dict[str, Any]) -> str:
        """Делает глубинную SEO и коммерческую выжимку страницы по методичке."""
        seo = parsed_data.get('seo_meta', {})
        comm = parsed_data.get('commercial_signals', {})
        struct = parsed_data.get('content_structure', {})
        trust = parsed_data.get('trust_and_links', {})

        prompt = f"""
        Проведи глубокий коммерческий и SEO-анализ страницы конкурента {parsed_data.get('url')}:

        1. SEO МЕТАДАННЫЕ:
        - Title ({seo.get('title_length')} симв.): "{seo.get('title')}"
        - Description ({seo.get('description_length')} симв.): "{seo.get('description')}"
        - Кол-во H1: {seo.get('h1_count')} (Основной H1: "{seo.get('main_h1')}")

        2. СТРУКТУРА И ИЕРАРХИЯ ЗАГОЛОВКОВ (H1-H4):
        {struct.get('headings_hierarchy')}

        3. КОММЕРЧЕСКИЕ И КОНВЕРСИОННЫЕ ЭЛЕМЕНТЫ:
        - Найденные цены/диапазоны: {comm.get('prices')}
        - Формы заявки: {comm.get('forms_count')} шт. | Кнопки CTA: {comm.get('cta_buttons')}
        - Есть калькулятор: {comm.get('has_calculator')} | Квиз: {comm.get('has_quiz')}
        - Гарантии/Условия: {comm.get('has_guarantees')} | Кейсы/Примеры: {comm.get('has_cases')} | Отзывы: {comm.get('has_reviews')} | Реквизиты: {comm.get('has_requisites')}

        4. ВИЗУАЛ И ТАБЛИЦЫ:
        - Таблицы ({struct.get('tables_count')} шт.): {struct.get('tables_sample')}
        - Списки ({struct.get('lists_count')} шт.): {struct.get('lists_sample')}

        5. ЭЛЕМЕНТЫ ДОВЕРИЯ И ПЕРЕЛИНКОВКА:
        - Ссылки на документы/лицензии: {trust.get('trust_links')}
        - Перелинковка на услуги/статьи: {trust.get('related_service_links')}

        6. ПРИМЕР ТЕКСТА:
        {parsed_data.get('content_sample')}

        Сформируй выжимку по методичке:
        1. СИЛЬНЫЕ СТОРОНЫ (структура блоков, ценные элементы, наглядность).
        2. СЛАБЫЕ СТОРОНЫ (где недожали, чего не хватает, где ошибка в SEO/H1/Цене).
        3. КЛЮЧЕВЫЕ ТЕЗИСЫ И СМЫСЛЫ (что обязательно нужно применить в нашей статье).
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.generate_completion(messages, reasoning_effort="high")