import asyncio
from typing import Any
import httpx

from src.config.settings import settings


class KieApiGateway:
    """Шлюз для быстрой генерации контента через KIE.AI API (Grok 4.3)."""

    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._api_key = settings.kie.API_KEY
        self._base_url = settings.kie.KIE_BASE_URL.rstrip('/')
        self._model = settings.kie.CHAT_MODEL
        self._endpoint = "/grok/v1/responses"

    def _format_input_for_grok(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Преобразует сообщения в формат KIE.AI Grok:
        [{'role': 'user', 'content': [{'type': 'input_text', 'text': '...'}]}]
        """
        formatted_input = []
        for msg in messages:
            role = msg.get("role", "user")

            # Роль 'system' мапим в 'user' для стабильности эндпоинта
            if role == "system" or role not in ("user", "assistant"):
                role = "user"

            content = msg.get("content", "")

            if isinstance(content, str):
                formatted_content = [{"type": "input_text", "text": content}]
            elif isinstance(content, list):
                formatted_content = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") in ("text", "input_text"):
                            formatted_content.append({"type": "input_text", "text": part.get("text", "")})
                        elif part.get("type") in ("image_url", "input_image"):
                            img_url = part.get("image_url", "")
                            if isinstance(img_url, dict):
                                img_url = img_url.get("url", "")
                            formatted_content.append({"type": "input_image", "image_url": str(img_url)})
                        else:
                            formatted_content.append(part)
                    else:
                        formatted_content.append({"type": "input_text", "text": str(part)})
            else:
                formatted_content = [{"type": "input_text", "text": str(content)}]

            formatted_input.append({
                "role": role,
                "content": formatted_content
            })
        return formatted_input

    def _parse_grok_response(self, data: dict[str, Any]) -> tuple[str, str]:
        """Извлекает текст ответа и reasoning из структуры output."""
        content = ""
        reasoning = ""

        outputs = data.get("output", [])
        for item in outputs:
            item_type = item.get("type")
            if item_type == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        content += part.get("text", "")
                    elif part.get("text"):
                        content += part.get("text", "")
            elif item_type == "reasoning":
                summaries = item.get("summary", [])
                if isinstance(summaries, list):
                    reasoning += " ".join(str(s) for s in summaries)
                elif isinstance(summaries, str):
                    reasoning += str(summaries)

        if not content and isinstance(data.get("data"), dict):
            return self._parse_grok_response(data["data"])

        return content.strip(), reasoning.strip()

    async def generate_completion_with_reasoning(
            self,
            messages: list[dict[str, Any]],
            reasoning_effort: str = "low",
    ) -> tuple[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self._model,
            "stream": False,
            "input": self._format_input_for_grok(messages),
            "reasoning": {
                "effort": "low"
            }
        }

        url = f"{self._base_url}{self._endpoint}"
        max_retries = 3
        last_error_text = ""

        for attempt in range(1, max_retries + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers, timeout=120.0)

                if response.status_code == 200:
                    data = response.json()
                    content, reasoning = self._parse_grok_response(data)
                    if content:
                        return content, reasoning
                    raise ValueError(f"Пустой content в ответе KIE.AI Grok ({url}): {data}")

                if response.status_code in (500, 502, 503, 504, 429):
                    last_error_text = response.text
                    print(f"⚠️ [KIE.AI Grok Retry #{attempt}/{max_retries}]: Статус {response.status_code}. Ждем 2с...")
                    await asyncio.sleep(2.0 * attempt)
                    continue

                raise ValueError(f"Ошибка KIE.AI Grok ({response.status_code}): {response.text}")

            except httpx.RequestError as req_err:
                print(f"⚠️ [KIE.AI Network Retry #{attempt}/{max_retries}]: {req_err}")
                await asyncio.sleep(2.0 * attempt)

        raise ValueError(f"Ошибка KIE.AI Grok после {max_retries} попыток: {last_error_text}")

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
    ) -> tuple[str, str, list[dict[str, Any]]]:
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_prompt})

        content, reasoning = await self.generate_completion_with_reasoning(
            updated_history,
            reasoning_effort="low",
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

        headings_list = [f"- [{h.get('level', 'H')}] {h.get('text', '')}" for h in struct.get('headings', [])]
        headings_text = "\n".join(headings_list) or "Нет данных"

        tables_text = "\n---\n".join(struct.get('tables', [])) or "Нет таблиц"
        faq_text = "\n---\n".join(struct.get('faq_blocks', [])) or "Нет явных FAQ блоков"

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
        {parsed_data.get('body_text', '')}

        ЗАДАЧИ АНАЛИЗА ПО МЕТОДИЧКЕ:
        1. КОММЕРЧЕСКИЕ ФАКТОРЫ: точные цены, гарантии, условия, этапы.
        2. LSA СЕМАНТИКА: ключевые профессиональные термины ниши.
        3. СИЛЬНЫЕ И СЛАБЫЕ СТОРОНЫ.
        4. ВЫЖИМКА ТЕЗИСОВ ДЛЯ НАШЕЙ СТАТЬИ.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.generate_completion(messages, reasoning_effort="low")