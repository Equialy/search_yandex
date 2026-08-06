import json
from openai import AsyncOpenAI
from src.api.v1.text_router.schema import DetectResponse, HumanizeResponse


class TextAiService:
    def __init__(self, openai_client: AsyncOpenAI):
        self.client = openai_client

    async def detect_ai(self, text: str) -> DetectResponse:
        system_prompt = """
        Ты — экспертный анализатор текстов и детектора ИИ. Твоя задача — проанализировать текст и определить вероятность того, что он был сгенерирован ИИ.

        Верни результат СТРОГО в формате JSON с ключами:
        - "ai_percentage": целое число от 0 до 100.
        - "human_percentage": целое число от 0 до 100.
        - "reason": краткий анализ (2-3 предложения на русском языке), почему сделан такой вывод.
        """

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.1
        )

        data = json.loads(response.choices[0].message.content)
        return DetectResponse(**data)

    async def humanize_text(self, text: str) -> HumanizeResponse:
        system_prompt = """
        Ты — человек, который переписывает текст своими словами. Твоя задача — сделать так, чтобы текст вообще не казался сгенерированным нейросетью.

        ПРАВИЛА:
        1. Пиши просто и живо, как человек в блоге или мессенджере.
        2. Используй риторические вопросы или вводные слова ("кстати", "честно говоря", "по сути").
        3. Чередуй очень короткие предложения (из 2-4 слов) с длинными.
        4. Избегай строгого академического тона.
        5. Выводи ТОЛЬКО готовый текст.
        """

        response = await self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.7
        )

        rewritten = response.choices[0].message.content.strip()
        return HumanizeResponse(humanized_text=rewritten)