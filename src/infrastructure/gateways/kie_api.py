import asyncio
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

    def _format_messages_for_gpt52(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Преобразует сообщения в строгий формат KIE.AI GPT-5.2:
        """
        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            formatted_content = []
            if isinstance(content, str):
                formatted_content.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") in ("text", "input_text"):
                            formatted_content.append({"type": "text", "text": part.get("text", "")})
                        # Картинка
                        elif part.get("type") in ("image_url", "input_image"):
                            img_obj = part.get("image_url")
                            if isinstance(img_obj, dict):
                                img_url = img_obj.get("url", "")
                            else:
                                img_url = str(img_obj or "")
                            formatted_content.append({"type": "image_url", "image_url": {"url": img_url}})
                        else:
                            formatted_content.append(part)
                    else:
                        formatted_content.append({"type": "text", "text": str(part)})
            else:
                formatted_content.append({"type": "text", "text": str(content)})

            formatted_messages.append({
                "role": role,
                "content": formatted_content
            })
        return formatted_messages

    async def generate_completion_with_reasoning(
            self,
            messages: list[dict[str, Any]],
            reasoning_effort: str = "low",
    ) -> tuple[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        effort = "low" if str(reasoning_effort).lower() == "low" else "high"

        payload = {
            "messages": self._format_messages_for_gpt52(messages),
            "reasoning_effort": effort
        }

        url = f"{self._base_url}{self._endpoint}"
        max_retries = 3
        last_error_text = ""

        for attempt in range(1, max_retries + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers, timeout=120.0)

                if response.status_code == 200:
                    data = response.json()

                    if data.get("code") and data.get("code") != 200:
                        last_error_text = str(data)
                        print(
                            f" [KIE.AI Retry #{attempt}/{max_retries}]: Внутренняя ошибка KIE (code={data.get('code')}). Ждем {2.0 * attempt}с...")
                        await asyncio.sleep(2.0 * attempt)
                        continue

                    choices = data.get("choices")
                    if choices and len(choices) > 0:
                        msg_obj = choices[0].get("message", {})
                        content = msg_obj.get("content") or ""
                        reasoning = msg_obj.get("reasoning_content") or msg_obj.get("reasoning") or ""
                        if content:
                            return content.strip(), reasoning.strip()

                    last_error_text = str(data)
                    print(
                        f"️ [KIE.AI Retry #{attempt}/{max_retries}]: Пустой choices/content в ответе. Ждем {2.0 * attempt}с...")
                    await asyncio.sleep(2.0 * attempt)
                    continue

                if response.status_code in (500, 502, 503, 504, 429):
                    last_error_text = response.text
                    print(
                        f" [KIE.AI Retry #{attempt}/{max_retries}]: HTTP {response.status_code}. Ждем {2.0 * attempt}с...")
                    await asyncio.sleep(2.0 * attempt)
                    continue

                raise ValueError(f"Ошибка KIE.AI GPT-5.2 ({response.status_code}): {response.text}")

            except httpx.RequestError as req_err:
                last_error_text = str(req_err)
                print(f" [KIE.AI Network Retry #{attempt}/{max_retries}]: {req_err}")
                await asyncio.sleep(2.0 * attempt)

        raise ValueError(f"Ошибка KIE.AI GPT-5.2 после {max_retries} попыток: {last_error_text}")

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