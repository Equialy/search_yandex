# src/infrastructure/gateways/kie_api.py

import asyncio
import json
import re
from typing import Any
import httpx

from src.config.settings import settings


def _clean_text_for_llm(text: str, max_chars: int = 40000) -> str:
    """Очищает текст, сохраняя структуру абзацев и заголовков."""
    if not text:
        return ""

    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F\uFFFD]", "", str(text))
    cleaned = re.sub(r"[^\S\r\n]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n...[текст обрезан для соблюдения лимитов]"

    return cleaned


class KieApiGateway:
    """Шлюз KIE.AI для Gemini 3.8 Flash (/gemini/v1/models/gemini-3-8-flash:streamGenerateContent)."""

    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._api_key = settings.kie.API_KEY
        self._base_url = settings.kie.KIE_BASE_URL.rstrip('/')
        self._endpoint = "/gemini/v1/models/gemini-3-8-flash:streamGenerateContent"

    def _format_contents_for_gemini(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Преобразует сообщения в структуру `contents` Gemini.
        В Gemini разрешены только роли 'user' и 'model', они обязаны чередоваться.
        """
        merged_contents = []

        for msg in messages:
            raw_role = msg.get("role", "user")
            role = "model" if raw_role == "assistant" else "user"

            content = msg.get("content", "")
            text_parts = []

            if isinstance(content, str):
                cleaned = _clean_text_for_llm(content)
                if cleaned:
                    text_parts.append(cleaned)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        cleaned = _clean_text_for_llm(part["text"])
                        if cleaned:
                            text_parts.append(cleaned)
                    elif isinstance(part, str):
                        cleaned = _clean_text_for_llm(part)
                        if cleaned:
                            text_parts.append(cleaned)

            full_text = "\n\n".join(text_parts).strip()
            if not full_text:
                continue

            # Склеиваем соседние сообщения одной роли, чтобы соблюсти чередование user -> model -> user
            if merged_contents and merged_contents[-1]["role"] == role:
                merged_contents[-1]["parts"][0]["text"] += f"\n\n{full_text}"
            else:
                merged_contents.append({
                    "role": role,
                    "parts": [{"text": full_text}]
                })

        # Защита: в диалоге должно быть хотя бы одно сообщение от user
        if not merged_contents:
            merged_contents.append({"role": "user", "parts": [{"text": "Привет"}]})
        elif merged_contents[0]["role"] != "user":
            merged_contents[0]["role"] = "user"

        return merged_contents

    def _extract_gemini_text(self, data: Any) -> str:
        """Извлекает итоговый текст из ответа Gemini (поддерживает JSON и чанки)."""
        # 1. Если пришел словарь с candidates
        if isinstance(data, dict):
            candidates = data.get("candidates") or []
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text_list = [p["text"] for p in parts if isinstance(p, dict) and "text" in p]
                if text_list:
                    return "".join(text_list).strip()

        # 2. Если пришел массив объектов
        elif isinstance(data, list):
            collected = []
            for item in data:
                if isinstance(item, dict):
                    candidates = item.get("candidates") or []
                    for c in candidates:
                        parts = c.get("content", {}).get("parts", [])
                        for p in parts:
                            if isinstance(p, dict) and "text" in p:
                                collected.append(p["text"])
            if collected:
                return "".join(collected).strip()

        return ""

    async def generate_completion_with_reasoning(
            self,
            messages: list[dict[str, Any]],
            reasoning_effort: str = "low",
    ) -> tuple[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-Goog-Api-Key": self._api_key,
            "Content-Type": "application/json",
        }

        # Настройки генерации Gemini
        payload = {
            "stream": False,
            "contents": self._format_contents_for_gemini(messages),
            "generationConfig": {
                "thinkingConfig": {
                    "includeThoughts": False,
                    "thinkingLevel": "low" if str(reasoning_effort).lower() == "low" else "high",
                }
            }
        }

        url = f"{self._base_url}{self._endpoint}"
        max_retries = 3
        last_error = ""

        for attempt in range(1, max_retries + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers, timeout=140.0)

                if response.status_code == 200:
                    raw_text = response.text.strip()

                    if raw_text.startswith("data:") or "event:" in raw_text:
                        full_parts = []
                        for line in raw_text.split("\n"):
                            line = line.strip()
                            if line.startswith("data:"):
                                chunk_str = line[5:].strip()
                                if chunk_str and chunk_str != "[DONE]":
                                    try:
                                        chunk_json = json.loads(chunk_str)
                                        part = self._extract_gemini_text(chunk_json)
                                        if part:
                                            full_parts.append(part)
                                    except Exception:
                                        pass
                        content = "".join(full_parts).strip()
                        if content:
                            return content, ""

                    # Стандартный JSON ответ
                    data = response.json()
                    content = self._extract_gemini_text(data)
                    if content:
                        return content, ""

                    last_error = f"Пустой candidates в ответе Gemini: {data}"
                    await asyncio.sleep(2.0 * attempt)
                    continue

                if response.status_code in (500, 502, 503, 504, 429):
                    last_error = response.text
                    await asyncio.sleep(2.0 * attempt)
                    continue

                raise ValueError(f"Ошибка KIE Gemini 3.8 Flash ({response.status_code}): {response.text}")

            except httpx.RequestError as err:
                last_error = str(err)
                await asyncio.sleep(2.0 * attempt)

        raise ValueError(f"Ошибка Gemini 3.8 Flash после {max_retries} попыток: {last_error}")

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
            "reasoning": reasoning
        })

        return content, reasoning, updated_history

    async def summarize_site(self, parsed_data: dict[str, Any]) -> str:
        seo = parsed_data.get('seo_meta', {})
        struct = parsed_data.get('content_structure', {})

        headings_list = [f"- [{h.get('level', 'H')}] {h.get('text', '')}" for h in struct.get('headings', [])][:40]
        headings_text = "\n".join(headings_list) or "Нет данных"

        raw_tables = "\n---\n".join(struct.get('tables', []))
        tables_text = _clean_text_for_llm(raw_tables, max_chars=4000) or "Нет таблиц"

        raw_faq = "\n---\n".join(struct.get('faq_blocks', []))
        faq_text = _clean_text_for_llm(raw_faq, max_chars=4000) or "Нет явных FAQ блоков"

        clean_body = _clean_text_for_llm(parsed_data.get('body_text', ''), max_chars=12000)

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
        return await self.generate_completion(messages, reasoning_effort="low")