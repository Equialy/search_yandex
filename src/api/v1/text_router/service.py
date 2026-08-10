
import json

from src.api.v1.text_router.schema import DetectResponse, HumanizeResponse
from src.infrastructure.gateways.openai_gateway import OpenAiGateway
import math
import re
from collections import Counter
import pymorphy3

from src.api.v1.text_router.schema import (
    CalculateNauseaRequest,
    CalculateNauseaResponse,
    WordFrequencyDTO,
)
STOP_POS = {'PREP', 'CONJ', 'PRCL', 'NPRO', 'INTJ'}
class TextAiService:
    def __init__(self, ai_gateway: OpenAiGateway,     morph: pymorphy3.MorphAnalyzer,):
        self.openai = ai_gateway
        self._morph = morph

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

        raw_content = await self.openai.generate_completion(messages, reasoning_effort="low")
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

        rewritten = await self.openai.generate_completion(messages, reasoning_effort="high")
        return HumanizeResponse(humanized_text=rewritten.strip())

    def calculate_nausea(self, payload: CalculateNauseaRequest) -> CalculateNauseaResponse:
        text = payload.text

        # 1. Извлекаем слова
        words = re.findall(r'\b[а-яА-Яa-zA-Z0-9]+\b', text.lower())
        total_words = len(words)

        if total_words == 0:
            return CalculateNauseaResponse(
                total_words=0,
                unique_words=0,
                classic_nausea=0.0,
                academic_nausea=0.0,
                top_words=[]
            )

        significant_lemmas = []
        all_lemmas = []

        for w in words:
            parsed = self._morph.parse(w)[0]
            lemma = parsed.normal_form
            all_lemmas.append(lemma)

            if parsed.tag.POS not in STOP_POS and len(lemma) > 1:
                significant_lemmas.append(lemma)

        significant_counts = Counter(significant_lemmas)
        all_counts = Counter(all_lemmas)

        # 2. КЛАССИЧЕСКАЯ ТОШНОТА (корень из самого частого слова)
        if significant_counts:
            most_common_word, max_freq = significant_counts.most_common(1)[0]
            classic_nausea = math.sqrt(max_freq)
        else:
            classic_nausea = 0.0

        # 3. АКАДЕМИЧЕСКАЯ ТОШНОТА (по методологии Адвего)
        # Учитываем только самые частотные ключевые слова (с частотой >= 2% или топ-5)
        # Для текстов < 100 слов порог = 2 повтора, для длинных текстов = ~2% от объема
        min_threshold = max(2, math.ceil(total_words * 0.02))

        top_keyword_counts = [
            freq for word, freq in significant_counts.items()
            if freq >= min_threshold
        ]

        # Если частых ключевых слов мало, берем топ-5 значимых слов
        if len(top_keyword_counts) < 3:
            top_keyword_counts = [freq for _, freq in significant_counts.most_common(5)]

        academic_nausea = (sum(top_keyword_counts) / total_words) * 100

        # 4. Топ-10 частых значимых слов
        top_words = [
            WordFrequencyDTO(
                word=lemma,
                count=freq,
                frequency_percent=round((freq / total_words) * 100, 2)
            )
            for lemma, freq in significant_counts.most_common(10)
        ]

        return CalculateNauseaResponse(
            total_words=total_words,
            unique_words=len(all_counts),
            classic_nausea=round(classic_nausea, 2),
            academic_nausea=round(academic_nausea, 2),
            top_words=top_words
        )