from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.api.v1.text_router.schema import CalculateNauseaRequest
from src.api.v1.text_router.service import TextAiService
from src.application.article_format import ensure_semantic_html, normalize_article_html
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.utils.extract_data import extract_html_metadata

logger = logging.getLogger(__name__)

# Маркеры брака из SEO_GENERATE_ARTICLE
_FORBIDDEN_PHRASES = (
    "вводный блок",
    "финальный абзац",
    "наши преимущества и позиционирование",
    "кейсы, доказательства и гарантии",
    "важно понимать",
    "является неотъемлемой частью",
    "играет ключевую роль",
    "в современном мире",
    "подводя итог",
    "таким образом,",
)


@dataclass
class ArticleQualityConfig:
    min_chars: int = 4500
    max_chars: int = 22000
    max_academic_nausea: float = 9.5
    max_classic_nausea: float = 4.2
    min_human_percentage: int = 75
    min_desc_len: int = 120
    max_desc_len: int = 170
    max_repair_attempts: int = 2


@dataclass
class VerificationReport:
    html: str
    clean_text: str
    char_count: int
    h1: str
    title: str
    description: str
    seo_metrics: dict[str, Any]
    structural_issues: list[str] = field(default_factory=list)
    needs_humanize: bool = False
    score: float = 0.0

    @property
    def is_passed(self) -> bool:
        return not self.structural_issues and not self.needs_humanize


def _html_to_plain_text(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class ArticleQualityHarness:
    """
    Verification & Self-Correction Loop для автономной генерации SEO-статей.
    """

    def __init__(
        self,
        ai_gateway: KieApiGateway,
        text_ai_service: TextAiService,
        config: ArticleQualityConfig | None = None,
    ):
        self._ai = ai_gateway
        self._text_ai = text_ai_service
        self._cfg = config or ArticleQualityConfig()

    async def verify_and_refine(
        self,
        raw_html: str,
        *,
        topic: str,
        primary_keyword: str,
        target_min_chars: int | None = None,
        target_max_chars: int | None = None,
    ) -> VerificationReport:
        min_chars = target_min_chars or self._cfg.min_chars
        max_chars = target_max_chars or self._cfg.max_chars

        current_html = self._sanitize_html(raw_html, topic)
        best_report = await self._evaluate(
            current_html,
            topic=topic,
            primary_keyword=primary_keyword,
            min_chars=min_chars,
            max_chars=max_chars,
        )

        if best_report.is_passed:
            logger.info("[ArticleHarness] Черновик прошёл все проверки с 1-го раза.")
            return best_report

        for attempt in range(1, self._cfg.max_repair_attempts + 1):
            logger.info(
                "[ArticleHarness] Попытка %d/%d | Проблемы: %s | human=%s%% | acad_nausea=%s%%",
                attempt,
                self._cfg.max_repair_attempts,
                best_report.structural_issues,
                best_report.seo_metrics.get("humanPercentage"),
                best_report.seo_metrics.get("academicNausea"),
            )

            if best_report.structural_issues:
                repaired_raw = await self._repair_issues(
                    best_report.html,
                    issues=best_report.structural_issues,
                    primary_keyword=primary_keyword,
                )
                candidate_html = self._sanitize_html(repaired_raw, topic)
            elif best_report.needs_humanize:
                humanized = await self._text_ai.humanize_text(best_report.html)
                candidate_html = self._sanitize_html(humanized.humanized_text, topic)
            else:
                break

            candidate_report = await self._evaluate(
                candidate_html,
                topic=topic,
                primary_keyword=primary_keyword,
                min_chars=min_chars,
                max_chars=max_chars,
            )

            # Оставляем лучший вариант, чтобы не потерять структуру при неудачном ретрае
            if candidate_report.score >= best_report.score:
                best_report = candidate_report

            if best_report.is_passed:
                logger.info("[ArticleHarness] Все проверки пройдены на попытке %d.", attempt)
                break

        return best_report

    def _sanitize_html(self, raw_html: str, topic: str) -> str:
        cleaned = re.sub(r"cite[a-zA-Z0-9_:]+", "", raw_html or "")
        cleaned = re.sub(r"【\d+[:†]?\d*†?[^】]*】", "", cleaned)
        cleaned = normalize_article_html(cleaned)
        return ensure_semantic_html(cleaned, topic=topic)

    async def _evaluate(
        self,
        html: str,
        *,
        topic: str,
        primary_keyword: str,
        min_chars: int,
        max_chars: int,
    ) -> VerificationReport:
        issues: list[str] = []
        clean_text = _html_to_plain_text(html)
        char_count = len(clean_text)
        char_count_no_spaces = len(clean_text.replace(" ", ""))

        h1_val, title_val, desc_val = extract_html_metadata(html, topic)

        # 1. Проверка HTML-разметки
        h1_matches = re.findall(r"<h1[^>]*>.*?</h1>", html, flags=re.IGNORECASE | re.DOTALL)
        if len(h1_matches) != 1:
            issues.append(f"Должен быть ровно один <h1> (сейчас: {len(h1_matches)})")
        if "<style" not in html.lower() or "seo-article" not in html.lower():
            issues.append("Отсутствует блок <style> или обёртка <div class='seo-article'>")
        if re.search(r"(^|\n)\s*#{1,3}\s+", html) or "**" in clean_text:
            issues.append("В HTML просочился Markdown (** или ###), замени на <strong> и HTML-заголовки")

        # 2. Проверка метатегов и объёма
        if not desc_val or not (self._cfg.min_desc_len <= len(desc_val) <= self._cfg.max_desc_len):
            issues.append(
                f"Description сейчас {len(desc_val)} симв., нужно строго 140–160 символов с главным ключом"
            )
        if char_count < min_chars:
            issues.append(f"Слишком короткий текст ({char_count} симв.), расширь до минимум {min_chars} символов")
        elif char_count > max_chars:
            issues.append(f"Текст слишком длинный ({char_count} симв.), сократи до {max_chars} символов")

        # 3. Проверка запрещённых штампов
        lowered_text = clean_text.lower()
        found_cliches = [p for p in _FORBIDDEN_PHRASES if p in lowered_text]
        if found_cliches:
            issues.append(f"Удали шаблонные/технические фразы: {', '.join(found_cliches[:5])}")

        # 4. Расчёт тошноты (pymorphy3) и AI-детекта
        seo_metrics: dict[str, Any] = {
            "charCount": char_count,
            "charCountNoSpaces": char_count_no_spaces,
        }
        needs_humanize = False

        try:
            nausea_res = self._text_ai.calculate_nausea(CalculateNauseaRequest(text=clean_text))
            seo_metrics.update({
                "classicNausea": nausea_res.classic_nausea,
                "academicNausea": nausea_res.academic_nausea,
                "totalWords": nausea_res.total_words,
                "uniqueWords": nausea_res.unique_words,
                "topWords": [w.model_dump(by_alias=True) for w in nausea_res.top_words],
            })

            if nausea_res.academic_nausea > self._cfg.max_academic_nausea:
                top_spam = [f"'{w.word}' ({w.count}x)" for w in nausea_res.top_words[:4]]
                issues.append(
                    f"Высокая академическая тошнота ({nausea_res.academic_nausea}% > {self._cfg.max_academic_nausea}%). "
                    f"Замени синонимами частые повторы слов: {', '.join(top_spam)}"
                )
            if nausea_res.classic_nausea > self._cfg.max_classic_nausea:
                issues.append(
                    f"Высокая классическая тошнота ({nausea_res.classic_nausea} > {self._cfg.max_classic_nausea})"
                )
        except Exception as err:
            logger.warning("[ArticleHarness] Nausea check error: %s", err)

        try:
            detect_res = await self._text_ai.detect_ai(clean_text[:12000])
            seo_metrics.update({
                "aiPercentage": detect_res.ai_percentage,
                "humanPercentage": detect_res.human_percentage,
                "aiReason": detect_res.reason,
            })
            if detect_res.human_percentage < self._cfg.min_human_percentage:
                needs_humanize = True
        except Exception as err:
            logger.warning("[ArticleHarness] AI detect error: %s", err)

        # Оценка качества для выбора лучшего драфта (макс 100)
        score = 100.0 - len(issues) * 15.0
        if needs_humanize:
            score -= max(0, self._cfg.min_human_percentage - seo_metrics.get("humanPercentage", 70)) * 0.5
        if char_count < min_chars:
            score -= 20.0

        return VerificationReport(
            html=html,
            clean_text=clean_text,
            char_count=char_count,
            h1=h1_val,
            title=title_val,
            description=desc_val,
            seo_metrics=seo_metrics,
            structural_issues=issues,
            needs_humanize=needs_humanize,
            score=score,
        )

    async def _repair_issues(
        self,
        html: str,
        *,
        issues: list[str],
        primary_keyword: str,
    ) -> str:
        issues_text = "\n".join(f"- {item}" for item in issues)
        repair_prompt = f"""Ты — строгий SEO-редактор. Исправь ТОЛЬКО перечисленные ниже ошибки в готовой HTML-статье, сохранив тему, таблицы, факты и CSS-классы seo-article*.

ГЛАВНЫЙ КЛЮЧ: "{primary_keyword}"

СПИСОК ОШИБОК ДЛЯ ИСПРАВЛЕНИЯ:
{issues_text}

ТРЕБОВАНИЯ:
1. Верни ПОЛНЫЙ исправленный HTML от <style> до закрывающего </div>.
2. Без markdown-обёрток ```html и без пояснений.
3. Не сокращай статью ниже нужного объёма, если не указано обратное.

ИСХОДНЫЙ HTML:
{html}"""
        return await self._ai.generate_completion(
            [{"role": "user", "content": repair_prompt}],
            reasoning_effort="low",
        )