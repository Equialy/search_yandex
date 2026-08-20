from typing import Any

from openai import AsyncOpenAI

from src.application.prompts import VISION_DESIGN_EXTRACT_PROMPT, VISION_STYLE_APPLY_PROMPT
from src.config.settings import settings


def _build_image_content_part(image_base64: str, mime_type: str) -> dict[str, Any]:
    data_url = f"data:{mime_type};base64,{image_base64}"
    return {
        "type": "image_url",
        "image_url": {"url": data_url, "detail": "high"},
    }


class OpenAiGateway:
    """Шлюз для генерации контента через официальный OpenAI API (GPT-4o)."""

    def __init__(self, openai_client: AsyncOpenAI):
        self._client = openai_client
        self._model = settings.OPENAI.MODEL
        self._vision_model = settings.OPENAI.VISION_MODEL

    def _normalize_message_for_api(self, msg: dict[str, Any]) -> dict[str, Any]:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            return {"role": role, "content": content}

        return {"role": role, "content": str(content)}

    def _history_has_images(self, messages: list[dict[str, Any]]) -> bool:
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
        return False

    async def generate_completion_with_reasoning(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "high",
        *,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> tuple[str, str]:
        """Генерирует ответ через OpenAI API."""
        formatted_messages = [self._normalize_message_for_api(msg) for msg in messages]
        use_model = model or (
            self._vision_model if self._history_has_images(formatted_messages) else self._model
        )

        response = await self._client.chat.completions.create(
            model=use_model,
            messages=formatted_messages,
            # temperature=temperature,
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
            reasoning_effort=reasoning_effort,

        )
        return content

    async def completion_with_history(
        self,
        history: list[dict[str, Any]],
        user_prompt: str,
        *,
        image_base64: str | None = None,
        image_mime_type: str = "image/png",
        temperature: float = 0.7,
        history_user_content: str | None = None,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """Возвращает (текст ответа, рассуждения, обновленная история)."""
        updated_history = list(history)

        if image_base64:
            user_content: str | list[dict[str, Any]] = [
                _build_image_content_part(image_base64, image_mime_type),
                {"type": "text", "text": user_prompt},
            ]
            model = self._vision_model
        else:
            user_content = user_prompt
            model = None

        updated_history.append({"role": "user", "content": user_content})

        content, reasoning = await self.generate_completion_with_reasoning(
            updated_history,
            reasoning_effort="high",
            model=model,
            # temperature=temperature,
        )

        if history_user_content is not None:
            updated_history[-1] = {"role": "user", "content": history_user_content}

        updated_history.append({
            "role": "assistant",
            "content": content,
            "reasoning": reasoning
        })

        return content, reasoning, updated_history

    async def _vision_completion(
        self,
        text_prompt: str,
        image_base64: str,
        image_mime_type: str,
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> str:
        messages = [{
            "role": "user",
            "content": [
                _build_image_content_part(image_base64, image_mime_type),
                {"type": "text", "text": text_prompt},
            ],
        }]
        kwargs: dict[str, Any] = {
            "model": self._vision_model,
            "messages": messages,
            # "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def style_article_from_screenshot(
        self,
        article_html: str,
        user_prompt: str,
        image_base64: str,
        image_mime_type: str = "image/png",
    ) -> tuple[str, str]:
        """
        Изолированная стилизация: без истории чата.
        Шаг 1 — design tokens со скриншота, шаг 2 — применение к markup.
        """
        print("[OpenAI]: стилизация — шаг 1/2: извлечение design tokens...")
        design_tokens = await self._vision_completion(
            VISION_DESIGN_EXTRACT_PROMPT,
            image_base64,
            image_mime_type,
            # temperature=0.15,
            json_mode=True,
        )

        apply_prompt = VISION_STYLE_APPLY_PROMPT.format(
            design_tokens=design_tokens,
            user_prompt=user_prompt.strip() or "Стилизуй статью под скриншот сайта",
            article_markup=article_html,
        )

        print("[OpenAI]: стилизация — шаг 2/2: применение CSS к статье...")
        messages = [{"role": "user", "content": apply_prompt}]
        content, reasoning = await self.generate_completion_with_reasoning(
            messages,
            model=self._model,
            # temperature=0.25,
        )
        return content, reasoning

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
        {parsed_data.get('body_text', '')}

        ЗАДАЧИ АНАЛИЗА ПО МЕТОДИЧКЕ:
        1. КОММЕРЧЕСКИЕ ФАКТОРЫ: выдели точные цены из таблиц/текста, гарантии, призывы к действию (CTA), этапы работ, коммерческие пакеты.
        2. LSA / LSI СЕМАНТИКА: выпиши ключевые тематические термины, коммерческие «хвосты» и профессиональную лексику ниши, использованную на этой странице.
        3. СИЛЬНЫЕ И СЛАБЫЕ СТОРОНЫ СТРАНИЦЫ: что сделано отлично и каких элементов/смыслов не хватает.
        4. ВЫЖИМКА ДЛЯ НАШЕЙ СТАТЬИ: главных тезисов и смысловых блоков, которые обязательно нужно применить в нашей статье.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.generate_completion(messages, reasoning_effort="high")
