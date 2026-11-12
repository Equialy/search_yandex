import asyncio
import json
import re
from typing import Any
import httpx

from src.config.settings import settings


def _clean_text_for_llm(text: str, max_chars: int = 40000) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F\uFFFD]", "", str(text))
    cleaned = re.sub(r"[^\S\r\n]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n...[текст обрезан]"
    return cleaned


class DeepSeekGateway:
    """
    Шлюз KIE.AI для DeepSeek V4.1 Flash.
    Работает через эндпоинт POST /openai/v1/responses.
    """

    ALLOWED_EFFORT = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}

    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._api_key = settings.kie.API_KEY
        self._base_url = settings.kie.KIE_BASE_URL.rstrip("/")
        self._endpoint = "/openai/v1/responses"
        self._model = "deepseek-v4-1-flash"

    def _format_input(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Приводит входной список сообщений к структуре input схемы OpenAPI."""
        formatted = []
        for msg in messages:
            role = msg.get("role", "user")
            # Допустимые роли: system, developer, user, assistant
            if role not in ("system", "developer", "user", "assistant"):
                role = "user"

            content = msg.get("content", "")
            if isinstance(content, list):
                # Если передан список частей (текст/картинки)
                text_parts = []
                for p in content:
                    if isinstance(p, dict) and "text" in p:
                        text_parts.append(p["text"])
                    elif isinstance(p, str):
                        text_parts.append(p)
                content_str = "\n\n".join(text_parts)
            else:
                content_str = str(content)

            cleaned = _clean_text_for_llm(content_str)
            if cleaned:
                formatted.append({
                    "role": role,
                    "content": cleaned,
                })

        if not formatted:
            formatted.append({"role": "user", "content": "Привет"})
        return formatted

    def _extract_response(self, data: dict[str, Any]) -> tuple[str, str]:
        content_parts = []
        reasoning_parts = []

        output_items = data.get("output", [])
        for item in output_items:
            item_type = item.get("type")

            if item_type == "message":
                for part in item.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        content_parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        content_parts.append(part)

            elif item_type == "reasoning":
                for summary_item in item.get("summary", []):
                    if isinstance(summary_item, dict) and summary_item.get("type") == "summary_text":
                        reasoning_parts.append(summary_item.get("text", ""))
                    elif isinstance(summary_item, str):
                        reasoning_parts.append(summary_item)

        content = "".join(content_parts).strip()
        reasoning = "".join(reasoning_parts).strip()

        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        # 2. Очистка оберток markdown-кода (```html ... ```)
        if content.startswith("```"):
            content = re.sub(r"^```(?:html|xml)?\s*", "", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content).strip()

        return content, reasoning

    async def generate_completion_with_reasoning(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "low",
    ) -> tuple[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }



        # effort = str(reasoning_effort).lower()
        # if effort not in self.ALLOWED_EFFORT:
        #     effort = "low" if effort in ("minimal", "low") else "high"

        payload = {
            "model": self._model,
            "stream": False,
            "input": self._format_input(messages),
            "reasoning": {"effort": "none"},
        }

        url = f"{self._base_url}{self._endpoint}"
        max_retries = 3
        last_error = ""

        for attempt in range(1, max_retries + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers, timeout=160.0)

                if response.status_code == 200:
                    data = response.json()

                    # Проверка ошибок в теле ответа (согласно OpenAPI)
                    if "code" in data and data.get("code") != 200:
                        raise ValueError(f"DeepSeek KIE API error ({data.get('code')}): {data.get('msg')}")
                    if "error" in data:
                        raise ValueError(f"DeepSeek error: {data['error']}")

                    content, reasoning = self._extract_response(data)
                    if content:
                        return content, reasoning

                    last_error = f"Пустой output в ответе DeepSeek: {data}"
                    await asyncio.sleep(2.0 * attempt)
                    continue

                if response.status_code in (500, 502, 503, 504, 429):
                    last_error = f"HTTP {response.status_code}: {response.text}"
                    await asyncio.sleep(2.5 * attempt)
                    continue

                raise ValueError(f"Ошибка DeepSeek ({response.status_code}): {response.text}")

            except httpx.RequestError as err:
                last_error = str(err)
                await asyncio.sleep(2.0 * attempt)

        raise ValueError(f"Ошибка DeepSeek V4.1 Flash после {max_retries} попыток: {last_error}")

    async def generate_completion(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str = "low",
    ) -> str:
        content, _ = await self.generate_completion_with_reasoning(
            messages=messages,
            reasoning_effort=reasoning_effort,
        )
        return content

    async def completion_with_history(
        self,
        history: list[dict[str, Any]],
        user_prompt: str,
        reasoning_effort: str = "low",
    ) -> tuple[str, str, list[dict[str, Any]]]:
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_prompt})

        content, reasoning = await self.generate_completion_with_reasoning(
            updated_history,
            reasoning_effort=reasoning_effort,
        )

        updated_history.append({
            "role": "assistant",
            "content": content,
            "reasoning": reasoning,
        })
        return content, reasoning, updated_history

    async def summarize_site(self, parsed_data: dict[str, Any]) -> str:
        seo = parsed_data.get("seo_meta", {})
        struct = parsed_data.get("content_structure", {})

        headings_list = [f"- [{h.get('level', 'H')}] {h.get('text', '')}" for h in struct.get("headings", [])][:40]
        headings_text = "\n".join(headings_list) or "Нет данных"

        raw_tables = "\n---\n".join(struct.get("tables", []))
        tables_text = _clean_text_for_llm(raw_tables, max_chars=4000) or "Нет таблиц"

        raw_faq = "\n---\n".join(struct.get("faq_blocks", []))
        faq_text = _clean_text_for_llm(raw_faq, max_chars=4000) or "Нет явных FAQ блоков"

        clean_body = _clean_text_for_llm(parsed_data.get("body_text", ""), max_chars=14000)

        prompt = f"""
Проведи глубокий коммерческий и LSA-анализ страницы конкурента {parsed_data.get('url')}:

1. МЕТАДАННЫЕ:
- Title: "{seo.get('title', parsed_data.get('title'))}"
- Description: "{seo.get('description', parsed_data.get('description'))}"

2. СТРУКТУРА ЗАГОЛОВКОВ:
{headings_text}

3. ТАБЛИЦЫ И ЦЕНЫ:
{tables_text}

4. FAQ:
{faq_text}

5. ОСНОВНОЙ ТЕКСТ (BODY):
{clean_body}

ЗАДАЧИ АНАЛИЗА:
1. КОММЕРЧЕСКИЕ ФАКТОРЫ: точные цены, гарантии, условия, этапы.
2. LSA СЕМАНТИКА: ключевые профессиональные термины ниши.
3. СИЛЬНЫЕ И СЛАБЫЕ СТОРОНЫ.
4. ВЫЖИМКА ТЕЗИСОВ ДЛЯ НАШЕЙ СТАТЬИ.
"""
        messages = [{"role": "user", "content": prompt}]
        return await self.generate_completion(messages, reasoning_effort="none")