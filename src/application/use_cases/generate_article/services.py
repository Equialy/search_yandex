from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from src.application.article_format import inject_multiple_images_to_article
from src.application.prompts import (
    ARTICLE_HTML_FORMAT_TEXT,
    GENERATE_MULTIPLE_IMAGES_PROMPT_TEMPLATE,
    SEO_GENERATE_ARTICLE,
)
from src.application.use_cases.generate_article.dto import (
    ArticleVolumeTarget,
    TargetSiteContext,
)
from src.config.settings import BASE_DIR
from src.infrastructure.database.models.competitors import Article, CompetitorData
from src.infrastructure.gateways.image_kie_gateway import ImageKieGenerationGateway
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.utils.extract_data import convert_svg_to_png_bytes

logger = logging.getLogger(__name__)

EXPORTS_ARTICLES_DIR = BASE_DIR / "exports" / "articles"
EXPORTS_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)


def build_target_site_parse(url: str, parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": url,
        "title": parsed.get("title"),
        "description": parsed.get("description"),
        "raw_text": parsed.get("body_text") or "",
        "is_blocked": bool(parsed.get("is_blocked")),
    }


def build_volume_target(competitors: list[CompetitorData]) -> ArticleVolumeTarget:
    """Чистая бизнес-логика расчёта целевого объёма статьи (легко тестируется без моков)."""
    lengths = [
        len((c.graph_data.get("body_text") or c.raw_text or "").strip())
        for c in competitors
        if 200 < len((c.graph_data.get("body_text") or c.raw_text or "").strip()) < 40000
    ]

    if not lengths:
        return ArticleVolumeTarget(
            min_chars=5000,
            max_chars=15000,
            prompt_instruction=(
                "ТРЕБОВАНИЕ К ОБЪЕМУ: Напиши развернутую статью объемом 6000–9000 символов "
                "с пробелами. Обязательно доведи мысль до конца."
            ),
        )

    avg_chars = sum(lengths) // len(lengths)
    target_chars = min(max(avg_chars, 5000), 20000)
    min_chars = int(target_chars * 0.85)
    max_chars = int(target_chars * 1.15)
    return ArticleVolumeTarget(
        min_chars=min_chars,
        max_chars=max_chars,
        prompt_instruction=(
            f"ТРЕБОВАНИЕ К ОБЪЕМУ СТАТЬИ:\n"
            f"• Целевой ориентир: ~{target_chars} символов с пробелами "
            f"(диапазон от {min_chars} до {max_chars} символов).\n"
            f"• Статья должна быть полностью завершенной, с логическим заключением."
        ),
    )


def build_competitors_block(competitors: list[CompetitorData], per_site_limit: int = 1500) -> str:
    """Сжимает выжимки конкурентов для промпта."""
    summaries = [
        f"Конкурент {c.url}:\n{c.summary.strip()[:per_site_limit]}"
        for c in competitors
        if c.summary
    ]
    if not summaries:
        return ""
    joined = "\n\n---\n\n".join(summaries)
    return (
        "\nСЖАТЫЙ АНАЛИЗ КОНКУРЕНТОВ (используй факты, блоки и LSA-термины, не копируя текст):\n"
        f"{joined}\n"
    )


class TargetBrandService:
    """Парсит сайт заказчика и загружает логотип на CDN."""

    def __init__(
        self,
        parser_gateway: SiteParserGateway,
        image_gateway: ImageKieGenerationGateway,
        http_client: httpx.AsyncClient,
    ):
        self._parser = parser_gateway
        self._image_gateway = image_gateway
        self._http = http_client

    async def resolve(self, target_site: str) -> TargetSiteContext:
        company_name = target_site or "Наша компания"
        if not target_site or not target_site.startswith("http"):
            return TargetSiteContext(
                target_site=target_site or None,
                target_site_parse=None,
                cdn_logo_url=None,
                company_name=company_name,
            )

        parsed = await self._parser.parse_site_to_graph(target_site)
        site_parse = build_target_site_parse(target_site, parsed)
        cdn_logo_url = await self._upload_logo(parsed.get("logo_url"))

        return TargetSiteContext(
            target_site=target_site,
            target_site_parse=site_parse,
            cdn_logo_url=cdn_logo_url,
            company_name=company_name,
        )

    async def _upload_logo(self, logo_url: str | None) -> str | None:
        if not logo_url:
            return None
        try:
            res = await self._http.get(logo_url, timeout=15.0, follow_redirects=True)
            if res.status_code != 200 or len(res.content) <= 50:
                return None
            raw_logo = res.content
            if logo_url.lower().endswith(".svg") or b"<svg" in raw_logo[:100].lower():
                raw_logo = convert_svg_to_png_bytes(raw_logo)
            return await self._image_gateway.upload_image_to_cdn(raw_logo)
        except Exception as err:
            logger.warning("[Logo Upload Error]: %s", err)
            return None


class LlmArticleDraftGenerator:
    """Формирует SEO-промпт и генерирует первичный черновик (+ защита от короткой отписки)."""

    def __init__(self, ai_gateway: KieApiGateway):
        self._ai = ai_gateway

    async def generate_draft(
        self,
        *,
        topic: str,
        primary_keyword: str,
        company_name: str,
        instructions: str,
        volume: ArticleVolumeTarget,
        competitors_block: str,
    ) -> tuple[str, str, str]:
        system_instruction = (
            "Ты — профессиональный Senior SEO-копирайтер. Твоя задача — СРАЗУ выдать ПОЛНЫЙ готовый текст статьи. "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать планы, обещания, комментарии («сейчас напишу», «затем соберу», «я учту»). "
            "Сразу начинай с первого абзаца статьи!"
        )
        prompt = f"""Напиши коммерческую SEO-статью / страницу услуги на тему '{topic}' СПЕЦИАЛЬНО ДЛЯ НАШЕЙ КОМПАНИИ: '{company_name}'.

{volume.prompt_instruction}
{competitors_block}
ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ДЛЯ МЕТА-ТЕГОВ:
• В блоке meta:
    - Title: СТРОГО только текст ключа '{primary_keyword}' (без названия компании и без знаков препинания в конце).
    - Description: 140-160 символов, содержит ключ '{primary_keyword}' ровно 1 раз + название компании '{company_name}' + выгоды.

• ЗАГОЛОВОК H1:
    - В самом начале статьи (сразу после мета-блока) создай ровно ОДИН тег <h1> с главным ключом '{primary_keyword}'.

• ПЕРВЫЙ АБЗАЦ СТАТЬИ:
    - В первом вводном абзаце (сразу после <h1>) ОБЯЗАТЕЛЬНО должен присутствовать главный ключ '{primary_keyword}' в естественной форме.

СТРОГИЕ ПРАВИЛА И СТРУКТУРА:
{SEO_GENERATE_ARTICLE}

ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ:
{instructions}

{ARTICLE_HTML_FORMAT_TEXT}"""

        messages = [
            {"role": "developer", "content": system_instruction},
            {"role": "user", "content": prompt},
        ]
        content, reasoning = await self._ai.generate_completion_with_reasoning(
            messages=messages,
            reasoning_effort="low",
        )

        if len(content.strip()) < 1500:
            logger.warning("[DraftGenerator] Короткая отписка (%d симв.), запускаем дожим...", len(content))
            retry_messages = [
                *messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "ОШИБКА: Ты прислал короткое обещание/план вместо самой статьи! "
                        "Запрещено писать любые комментарии. Выведи ПОЛНЫЙ текст статьи "
                        f"на тему '{topic}' объемом от {volume.min_chars} символов ПРЯМО СЕЙЧАС, начиная с тега <style>!"
                    ),
                },
            ]
            content, reasoning = await self._ai.generate_completion_with_reasoning(
                messages=retry_messages,
                reasoning_effort="high",
            )

        return content, reasoning, prompt


class ArticleIllustratorService:
    """Генерирует промпты иллюстраций, картинки (FLUX 3 Klein) и вставляет их в HTML."""

    def __init__(
        self,
        ai_gateway: KieApiGateway,
        image_gateway: ImageKieGenerationGateway,
    ):
        self._ai = ai_gateway
        self._image_gateway = image_gateway

    async def illustrate(
        self,
        html_content: str,
        *,
        project_id: uuid.UUID,
        topic: str,
        company_name: str,
        cdn_logo_url: str | None,
        images_count: int,
    ) -> tuple[str, list[str]]:
        if images_count <= 0:
            return html_content, []

        try:
            configs = await self._build_image_configs(topic, company_name, images_count)

            async def _gen_one(idx: int, item: dict[str, str]) -> dict[str, str] | None:
                try:
                    url = await self._image_gateway.generate_and_save_image(
                        prompt=item["prompt"],
                        filename_prefix=f"proj_{project_id.hex[:6]}_img{idx}",
                        image_url=cdn_logo_url,
                    )
                    return {
                        "url": url,
                        "alt": item.get("alt", topic),
                        "caption": item.get("caption", ""),
                    }
                except Exception as err:
                    logger.warning("[Image %d Error]: %s", idx, err)
                    return None

            results = await asyncio.gather(*(_gen_one(i, c) for i, c in enumerate(configs, 1)))
            valid_images = [r for r in results if r]

            if not valid_images:
                return html_content, []

            updated_html = inject_multiple_images_to_article(html_content, valid_images)
            return updated_html, [img["url"] for img in valid_images]
        except Exception as err:
            logger.warning("[Images Generation Error]: %s", err)
            return html_content, []

    async def _build_image_configs(
        self,
        topic: str,
        company_name: str,
        images_count: int,
    ) -> list[dict[str, str]]:
        prompt_req = GENERATE_MULTIPLE_IMAGES_PROMPT_TEMPLATE.format(
            topic=topic,
            company_name=company_name,
            images_count=images_count,
        )
        prompts_raw = await self._ai.generate_completion([{"role": "user", "content": prompt_req}])
        json_match = re.search(r"\[\s*\{.*\}\s*\]", prompts_raw or "", re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))[:images_count]

        return [
            {
                "prompt": f"Commercial 4K photography, specialist with {company_name} logo on uniform, {topic}, photorealistic",
                "alt": topic,
                "caption": "",
            }
            for _ in range(images_count)
        ]


class LocalArticleHtmlExporter:
    """Экспортирует готовую статью в локальный .html файл."""

    def save(self, article: Article) -> Path:
        now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_path = EXPORTS_ARTICLES_DIR / f"article_{now_str}_{article.id}.html"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(article.content)
        return file_path