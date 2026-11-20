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
import redis.asyncio as aioredis
from urllib.parse import urlparse
from src.application.use_cases.generate_article.dto import (
    ArticleVolumeTarget,
    BrandFactSheet,
    BrandLinkDTO,
    TargetSiteContext,
)

logger = logging.getLogger(__name__)

EXPORTS_ARTICLES_DIR = BASE_DIR / "exports" / "articles"
EXPORTS_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
_ABOUT_LINK_RE = re.compile(r"(?:about|company|o-kompanii|o_kompanii|kompaniya|kontakty|contacts|licenz)", re.I)
BRAND_CACHE_TTL_SECONDS = 60 * 60 * 48  # 48 часов

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
    """Парсит сайт заказчика (главная + о компании), извлекает BrandFactSheet, перелинковку и грузит логотип на CDN."""

    def __init__(
        self,
        parser_gateway: SiteParserGateway,
        image_gateway: ImageKieGenerationGateway,
        http_client: httpx.AsyncClient,
        ai_gateway: KieApiGateway,
        redis_client: aioredis.Redis,
    ):
        self._parser = parser_gateway
        self._image_gateway = image_gateway
        self._http = http_client
        self._ai = ai_gateway
        self._redis = redis_client

    async def resolve(self, target_site: str) -> TargetSiteContext:
        fallback_name = target_site or "Наша компания"
        if not target_site or not target_site.startswith("http"):
            return TargetSiteContext(
                target_site=target_site or None,
                target_site_parse=None,
                cdn_logo_url=None,
                company_name=fallback_name,
                brand_fact_sheet=None,
            )

        domain = urlparse(target_site).netloc.lower().removeprefix("www.")
        cache_key = f"brand:profile:v1:{domain}"

        # 1. Пробуем достать готовый профиль из Redis
        try:
            cached_raw = await self._redis.get(cache_key)
            if cached_raw:
                cached = json.loads(cached_raw)
                fact_sheet = BrandFactSheet.model_validate(cached["brand_fact_sheet"])
                logger.info("[TargetBrandService] Профиль бренда '%s' взят из Redis-кэша.", fact_sheet.company_name)
                return TargetSiteContext(
                    target_site=target_site,
                    target_site_parse=cached.get("target_site_parse"),
                    cdn_logo_url=cached.get("cdn_logo_url"),
                    company_name=fact_sheet.company_name or fallback_name,
                    brand_fact_sheet=fact_sheet,
                )
        except Exception as err:
            logger.debug("[TargetBrandService] Redis read error: %s", err)

        # 2. Парсим главную/целевую страницу
        parsed_main = await self._parser.parse_site_to_graph(target_site)
        site_parse = build_target_site_parse(target_site, parsed_main)
        cdn_logo_url = await self._upload_logo(parsed_main.get("logo_url"))

        # 3. Если есть страница «О компании» / «Контакты», добираем факты с неё
        about_parsed: dict[str, Any] | None = None
        all_links: list[dict[str, str]] = list(parsed_main.get("internal_links") or [])
        about_candidate = next(
            (lnk["url"] for lnk in all_links if _ABOUT_LINK_RE.search(lnk["url"])),
            None,
        )
        if about_candidate and about_candidate.rstrip("/") != target_site.rstrip("/"):
            about_parsed = await self._parser.parse_site_to_graph(about_candidate)
            for lnk in (about_parsed.get("internal_links") or []):
                if all(existing["url"] != lnk["url"] for existing in all_links):
                    all_links.append(lnk)

        # 4. Собираем подтверждённые контакты и извлекаем BrandFactSheet через LLM
        fact_sheet = await self._build_fact_sheet(
            target_site=target_site,
            domain=domain,
            parsed_main=parsed_main,
            about_parsed=about_parsed,
            candidate_links=all_links,
        )

        # 5. Кэшируем в Redis на 48 часов
        try:
            cache_payload = {
                "target_site_parse": {
                    **site_parse,
                    "raw_text": (site_parse.get("raw_text") or "")[:6000],
                },
                "cdn_logo_url": cdn_logo_url,
                "brand_fact_sheet": fact_sheet.model_dump(),
            }
            await self._redis.set(
                cache_key,
                json.dumps(cache_payload, ensure_ascii=False),
                ex=BRAND_CACHE_TTL_SECONDS,
            )
        except Exception as err:
            logger.debug("[TargetBrandService] Redis write error: %s", err)

        return TargetSiteContext(
            target_site=target_site,
            target_site_parse=site_parse,
            cdn_logo_url=cdn_logo_url,
            company_name=fact_sheet.company_name or fallback_name,
            brand_fact_sheet=fact_sheet,
        )

    async def _build_fact_sheet(
        self,
        *,
        target_site: str,
        domain: str,
        parsed_main: dict[str, Any],
        about_parsed: dict[str, Any] | None,
        candidate_links: list[dict[str, str]],
    ) -> BrandFactSheet:
        contacts_main = parsed_main.get("contacts") or {}
        contacts_about = (about_parsed or {}).get("contacts") or {}

        phones = list(dict.fromkeys([*(contacts_main.get("phones") or []), *(contacts_about.get("phones") or [])]))[:4]
        emails = list(dict.fromkeys([*(contacts_main.get("emails") or []), *(contacts_about.get("emails") or [])]))[:3]
        address_hint = contacts_main.get("address_hint") or ""
        # Отбираем ссылки на услуги/разделы (исключая саму about/contacts), максимум 20 кандидатов для LLM
        service_links = [
            lnk for lnk in candidate_links
            if not _ABOUT_LINK_RE.search(lnk["url"])
        ][:20]
        allowed_urls = {lnk["url"]: lnk["anchor"] for lnk in service_links}

        main_text = (parsed_main.get("clean_text") or "")[:5000]
        about_text = ((about_parsed or {}).get("clean_text") or "")[:4000]
        links_text = "\n".join(f"- {lnk['anchor']} | {lnk['url']}" for lnk in service_links) or "Нет ссылок"

        prompt = f"""Извлеки фактическую карточку компании с её сайта ({target_site}).
                ЗАПРЕЩЕНО выдумывать факты, цифры, лицензии или ссылки. Используй ТОЛЬКО то, что есть в тексте ниже.

                TITLE ГЛАВНОЙ: {parsed_main.get("title", "")}
                DESCRIPTION: {parsed_main.get("description", "")}

                ТЕКСТ ГЛАВНОЙ СТРАНИЦЫ:
                {main_text}

                ТЕКСТ СТРАНИЦЫ «О КОМПАНИИ / КОНТАКТЫ»:
                {about_text}

                ШАПКА И ПОДВАЛ САЙТА (адрес, город, слоган):
                {address_hint}

                ДОСТУПНЫЕ ВНУТРЕННИЕ ССЫЛКИ ДЛЯ ПЕРЕЛИНКОВКИ:
                {links_text}

                Верни СТРОГО валидный JSON без markdown-обёрток:
                {{
                "company_name": "Короткое реальное название бренда/компании без URL (например: ООО «Интех» или Интех)",
                "city_or_region": "Город или регион работы (пусто, если не указан)",
                "services_summary": "1-2 предложения: на чём специализируется компания",
                "usp_and_experience": ["Факт 1: лет на рынке / лицензия / гарантия / сертификат / СРО", "Факт 2..."],
                "selected_links": [
                    {{"url": "точная ссылка из списка выше", "anchor": "естественный анкор"}}
                ]
                }}
                В selected_links выбери 3-5 самых полезных страниц смежных услуг/разделов строго из списка выше."""

        try:
            raw = await self._ai.generate_completion(
                [{"role": "user", "content": prompt}],
                reasoning_effort="none",
            )
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            data = json.loads(json_match.group(0) if json_match else cleaned)

            # Белый список URL: не пропускаем ни одной выдуманной ссылки
            verified_links: list[BrandLinkDTO] = []
            for item in data.get("selected_links") or []:
                u = str(item.get("url") or "").strip().rstrip("/")
                if u in allowed_urls:
                    anchor = str(item.get("anchor") or allowed_urls[u]).strip()
                    verified_links.append(BrandLinkDTO(url=u, anchor=anchor))
                if len(verified_links) >= 5:
                    break

            if not verified_links:
                verified_links = [BrandLinkDTO(**lnk) for lnk in service_links[:4]]

            return BrandFactSheet(
                company_name=str(data.get("company_name") or domain).strip(),
                city_or_region=str(data.get("city_or_region") or "").strip(),
                phones=phones,
                emails=emails,
                usp_and_experience=[str(x).strip() for x in (data.get("usp_and_experience") or []) if str(x).strip()][:6],
                services_summary=str(data.get("services_summary") or "").strip(),
                internal_links=verified_links,
            )
        except Exception as err:
            logger.warning("[TargetBrandService] BrandFactSheet LLM fallback: %s", err)
            return BrandFactSheet(
                company_name=domain,
                phones=phones,
                emails=emails,
                internal_links=[BrandLinkDTO(**lnk) for lnk in service_links[:4]],
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
        target_site: str = "",
        brand_context: str = "",
        instructions: str = "",
        volume: ArticleVolumeTarget,
        competitors_block: str = "",
    ) -> tuple[str, str, str]:
        desc_site_ref = (
            target_site.strip().rstrip("/")
            if target_site and target_site.strip()
            else company_name
        )
        brand_block = (
            f"\nДАННЫЕ О КОМПАНИИ ЗАКАЗЧИКА (используй реальный город, факты доверия, контакты и перелинковку):\n"
            f"{brand_context}\n"
            if brand_context
            else ""
        )

        system_instruction = (
            "Ты — профессиональный Senior SEO-копирайтер. Твоя задача — СРАЗУ выдать ПОЛНЫЙ готовый текст статьи. "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать планы, обещания, комментарии («сейчас напишу», «затем соберу», «я учту»). "
            "Сразу начинай с первого абзаца статьи!"
        )
        prompt = f"""Напиши коммерческую SEO-статью / страницу услуги на тему '{topic}' СПЕЦИАЛЬНО ДЛЯ НАШЕЙ КОМПАНИИ: '{company_name}'.

            {volume.prompt_instruction}
            {brand_block}
            {competitors_block}
            ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ДЛЯ МЕТА-ТЕГОВ:
            • В блоке meta:
                - Title: СТРОГО только текст ключа '{primary_keyword}' (без названия компании, URL и знаков препинания в конце).
                - Description: 140-160 символов, содержит ключ '{primary_keyword}' ровно 1 раз + ОБЯЗАТЕЛЬНО URL сайта '{desc_site_ref}' 
                (укажи именно URL '{desc_site_ref}', а НЕ словесное название компании) + выгоды.

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