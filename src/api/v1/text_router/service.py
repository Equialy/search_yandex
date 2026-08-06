
import json

from src.api.v1.text_router.schema import DetectResponse, HumanizeResponse
from src.infrastructure.gateways.kie_api import KieApiGateway


class TextAiService:
    def __init__(self, kie_gateway: KieApiGateway):
        self.kie = kie_gateway

    async def detect_ai(self, text: str) -> DetectResponse:
        system_prompt = """
        Ты — экспертный анализатор текстов и детектора ИИ. Твоя задача — проанализировать текст и определить вероятность того, что он был сгенерирован ИИ.

        Верни результат СТРОГО в формате JSON с ключами:
        - "ai_percentage": целое число от 0 до 100.
        - "human_percentage": целое число от 0 до 100.
        - "reason": краткий анализ (2-3 предложения на русском языке), почему сделан такой вывод.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]

        # Запрос к KIE.AI (GPT 5.2)
        raw_content = await self.kie.generate_completion(messages, reasoning_effort="low")
        raw_content = raw_content.strip()

        # Безопасная очистка от возможной markdown-обертки ```json ... ```
        if "```" in raw_content:
            raw_content = raw_content.replace("```json", "").replace("```", "").strip()

        data = json.loads(raw_content)
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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]

        # Запрос к KIE.AI (GPT 5.2)
        rewritten = await self.kie.generate_completion(messages, reasoning_effort="high")
        return HumanizeResponse(humanized_text=rewritten.strip())