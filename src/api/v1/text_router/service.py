
import json

from src.api.v1.text_router.schema import DetectResponse, HumanizeResponse
from src.infrastructure.gateways.kie_api import KieApiGateway
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
    def __init__(self, ai_gateway: KieApiGateway,     morph: pymorphy3.MorphAnalyzer,):
        self.openai = ai_gateway
        self._morph = morph

    async def detect_ai(self, text: str) -> DetectResponse:
        system_prompt = """
        Ты — эксперт по анализу текстов. Оцени текст по наличию маркеров ИИ-генерации:
        1. Монотонность ритма (все абзацы и предложения одинаковой длины).
        2. Шаблонные списки ровно по 3 пункта.
        3. Наличие клише ("важно понимать", "является неотъемлемой частью", "в заключение").
        4. Отсутствие конкретики (абстрактные рассуждения вместо фактов).

        Рассчитай:
        - human_percentage: от 0 до 100 (где 100 — живой, нешаблонный человеческий текст с динамичным ритмом).
        - ai_percentage: 100 - human_percentage.
        - reason: конкретные маркеры из текста, которые повлияли на оценку.

        Верни СТРОГО JSON: {"ai_percentage": int, "human_percentage": int, "reason": "str"}
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]

        raw_content = await self.openai.generate_completion(messages, reasoning_effort="low")
        raw_content = raw_content.strip()

        if "```" in raw_content:
            raw_content = raw_content.replace("```json", "").replace("```", "").strip()

        data = json.loads(raw_content)
        return DetectResponse(**data)

    async def humanize_text(self, text: str) -> HumanizeResponse:
        system_prompt = """
         Ты — бескомпромиссный главред. Твоя цель — устранить симптомы сгенерированного ИИ текста и сделать его языком живого эксперта-практика.

УНИВЕРСАЛЬНЫЙ ПРОТОКОЛ РЕДАКТУРЫ:
1. УДАЛЯЙ ПОВТОРЫ И ЗАЦИКЛИВАНИЯ (ANTI-LOOP):
   - Если в тексте несколько раз повторяется одна и та же дежурная мысль («все зависит от конкретной задачи», «стоимость определяется индивидуально», «сначала специалист оценивает ситуацию») — оставь её только ОДИН раз, а в остальных местах удали или замени предметным фактом.
2. ЗАМЕНЯЙ АБСТРАКЦИИ И КАНЦЕЛЯРИТ НА КОНКРЕТИКУ:
   - Заменяй размытые обобщения («необходимые меры», «соответствующие процедуры», «требуемые документы/материалы», «профильные специалисты») на прямые и точные отраслевые понятия, относящиеся к теме текста.
3. СБЕЙ МОНОТОННЫЙ РИТМ (BURSTINESS):
   - Чередуй длину предложений: после длинной сложной конструкции ставь короткую, емкую фразу (3–6 слов).
   - Убери одинаковые слова-связки в начале соседних абзацев («Поэтому», «При этом», «В такой ситуации», «Стоит отметить»).
   - Вырежи пустые анонсы («Ниже мы рассмотрим...») и дежурные микро-итоги («Таким образом...», «Подводя итог...»). Переходи сразу к сути.
4. СОХРАНЯЙ СТРУКТУРУ И ДАННЫЕ:
   - Сохрани HTML-теги, таблицы, списки, контакты, город, название компании и фактические параметры без изменений.

Верни ТОЛЬКО готовый очищенный текст без пояснений и обёрток.
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