import asyncio
import re
from typing import Any
import httpx

from src.config.settings import settings


def _clean_text_for_llm(text: str, max_chars: int = 35000) -> str:
    """Удаляет непечатаемые символы, null-байты, сохраняя форматирование."""
    if not text:
        return ""

    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F\uFFFD]", "", text)
    cleaned = re.sub(r"[^\S\r\n]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n...[текст обрезан для лимита контекста]"

    return cleaned


class KieApiGateway:
    """Шлюз для генерации контента через KIE.AI GPT Codex API (/api/v1/responses)."""

    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._api_key = settings.kie.API_KEY
        self._base_url = settings.kie.KIE_BASE_URL.rstrip('/')
        self._endpoint = "/api/v1/responses"
        self._model = settings.kie.CHAT_MODEL or "gpt-5.1-codex"

    def _format_input_for_codex(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Преобразует историю сообщений в формат `input` схемы Codex."""
        formatted_input = []
        for msg in messages:
            role = msg.get("role", "user")
            if role in ("system", "developer"):
                role = "developer"

            content = msg.get("content", "")
            content_parts = []

            if isinstance(content, str):
                clean_str = _clean_text_for_llm(content)
                content_parts.append({"type": "input_text", "text": clean_str})
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        p_type = part.get("type")
                        if p_type in ("text", "input_text"):
                            clean_str = _clean_text_for_llm(part.get("text", ""))
                            content_parts.append({"type": "input_text", "text": clean_str})
                        elif p_type in ("image_url", "input_image"):
                            img_obj = part.get("image_url")
                            img_url = img_obj.get("url", "") if isinstance(img_obj, dict) else str(img_obj or "")
                            content_parts.append({"type": "input_image", "image_url": img_url})
                        else:
                            content_parts.append(part)
                    else:
                        content_parts.append({
                            "type": "input_text",
                            "text": _clean_text_for_llm(str(part))
                        })
            else:
                content_parts.append({
                    "type": "input_text",
                    "text": _clean_text_for_llm(str(content))
                })

            formatted_input.append({
                "role": role,
                "content": content_parts
            })
        return formatted_input

    def _extract_codex_response(self, data: dict[str, Any]) -> tuple[str, str]:
        """Извлекает текст ответа и рассуждения из формата `output` Codex."""
        content_text = ""
        reasoning_text = ""

        outputs = data.get("output") or []
        for item in outputs:
            item_type = item.get("type")

            # Извлекаем рассуждения
            if item_type == "reasoning":
                summary = item.get("summary") or []
                if isinstance(summary, list):
                    reasoning_text = "\n".join(str(s) for s in summary)
                elif isinstance(summary, str):
                    reasoning_text = summary

            # Извлекаем текст статьи/сообщения
            elif item_type == "message":
                parts = item.get("content") or []
                extracted_parts = []
                for p in parts:
                    if p.get("type") == "output_text":
                        extracted_parts.append(p.get("text", ""))
                    elif "text" in p:
                        extracted_parts.append(p.get("text", ""))
                content_text = "\n".join(extracted_parts).strip()

        # Фолбек на случай старого формата choices
        if not content_text and "choices" in data:
            choices = data.get("choices") or []
            if choices:
                msg_obj = choices[0].get("message", {})
                content_text = msg_obj.get("content", "").strip()
                reasoning_text = msg_obj.get("reasoning_content", "").strip()

        return content_text, reasoning_text

    async def generate_completion_with_reasoning(
            self,
            messages: list[dict[str, Any]],
            reasoning_effort: str = "high",
    ) -> tuple[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        effort = "high" if str(reasoning_effort).lower() in ("high", "xhigh") else "medium"

        payload = {
            "model": self._model,
            "stream": False,  
            "input": self._format_input_for_codex(messages),
            "reasoning": {
                "effort": effort
            }
        }

        url = f"{self._base_url}{self._endpoint}"
        max_retries = 3
        last_error_text = ""

        for attempt in range(1, max_retries + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers, timeout=140.0)

                if response.status_code == 200:
                    data = response.json()

                    if data.get("code") and data.get("code") != 200:
                        last_error_text = str(data)
                        await asyncio.sleep(2.0 * attempt)
                        continue

                    content, reasoning = self._extract_codex_response(data)
                    if content:
                        return content.strip(), reasoning.strip()

                    last_error_text = f"Empty content in Codex response: {data}"
                    await asyncio.sleep(2.0 * attempt)
                    continue

                if response.status_code in (500, 502, 503, 504, 429):
                    last_error_text = response.text
                    await asyncio.sleep(2.0 * attempt)
                    continue

                raise ValueError(f"Ошибка KIE.AI Codex ({response.status_code}): {response.text}")

            except httpx.RequestError as req_err:
                last_error_text = str(req_err)
                await asyncio.sleep(2.0 * attempt)

        raise ValueError(f"Ошибка KIE.AI Codex после {max_retries} попыток: {last_error_text}")

    async def generate_completion(
            self,
            messages: list[dict[str, Any]],
            reasoning_effort: str = "medium",
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
            reasoning_effort: str = "high",
    ) -> tuple[str, str, list[dict[str, Any]]]:
        system_msgs = [m for m in history if m.get("role") in ("system", "developer")]
        chat_msgs = [m for m in history if m.get("role") not in ("system", "developer")]

        trimmed_history = system_msgs + chat_msgs[-6:]
        updated_history = list(trimmed_history)
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

        raw_body = parsed_data.get('body_text', '')
        clean_body = _clean_text_for_llm(raw_body, max_chars=12000)

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
        messages = [{"role": "developer", "content": prompt}]
        return await self.generate_completion(messages, reasoning_effort="low")