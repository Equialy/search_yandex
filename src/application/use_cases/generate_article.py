import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm.attributes import flag_modified

from src.api.v1.text_router.schema import CalculateNauseaRequest
from src.api.v1.text_router.service import TextAiService
from src.application.article_format import inject_multiple_images_to_article, normalize_article_html
from src.application.prompts import (
    ARTICLE_HTML_FORMAT_TEXT,
    GENERATE_MULTIPLE_IMAGES_PROMPT_TEMPLATE,
    SEO_GENERATE_ARTICLE,
)
from src.application.uow import UnitOfWorkProtocol
from src.config.settings import BASE_DIR
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.image_gateway import ImageGenerationGateway
from src.infrastructure.gateways.openai_gateway import OpenAiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway

EXPORTS_ARTICLES_DIR = BASE_DIR / "exports" / "articles"
EXPORTS_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)


def build_target_site_parse(url: str, parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Приводит результат парсинга целевого сайта к стандартизированному формату для DTO.
    """
    return {
        "url": url,
        "title": parsed.get("title"),
        "description": parsed.get("description"),
        "raw_text": parsed.get("body_text") or "",
        "is_blocked": bool(parsed.get("is_blocked")),
    }


@dataclass
class GenerateArticleResult:
    """
    Контейнер с результатом выполнения сценария генерации статьи.
    """
    article: Article
    target_site: str | None
    target_site_parse: dict[str, Any] | None
    images_urls: list[str] | None = None


def save_article_to_html(article: Article) -> Path:
    """
    Сохраняет сгенерированную HTML-статью на диск для резервной копии.
    """
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_path = EXPORTS_ARTICLES_DIR / f"article_{now_str}_{article.id}.html"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(article.content)
    return file_path


class GenerateArticleUseCase:
    def __init__(
            self,
            uow: UnitOfWorkProtocol,
            ai_gateway: OpenAiGateway,
            parser_gateway: SiteParserGateway,
            image_gateway: ImageGenerationGateway,
            text_ai_service: TextAiService,

    ):
        self._uow = uow
        self._kie = ai_gateway
        self._parser = parser_gateway
        self._image_gateway = image_gateway
        self._text_ai_service = text_ai_service

    async def execute(
            self,
            project_id: uuid.UUID,
            topic: str,
            instructions: str = "",
            target_site: str = "",
            user_id: uuid.UUID | None = None,
            images_count: int = 2,
    ) -> GenerateArticleResult:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id, user_id=user_id)
            if not project:
                raise ValueError("Проект не найден")

            company_name = target_site if target_site else "Наша компания"
            target_data_prompt = ""
            target_site_parse: dict[str, Any] | None = None
            logo_bytes: bytes | None = None

            if target_site and (target_site.startswith("http://") or target_site.startswith("https://")):
                print(f"[GenerateArticleUseCase]: Скачиваем данные сайта {target_site}...")
                parsed_target = await self._parser.parse_site_to_graph(target_site)
                target_site_parse = build_target_site_parse(target_site, parsed_target)

                logo_url = parsed_target.get("logo_url")
                if logo_url:
                    print(f" [Found Logo URL]: {logo_url} — Скачиваем файл...")
                    try:
                        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http_client:
                            logo_res = await http_client.get(logo_url)
                            if logo_res.status_code == 200 and len(logo_res.content) > 100:
                                logo_bytes = logo_res.content
                                print(f"[Logo Downloaded Successfully]: {len(logo_bytes)} байт")
                    except Exception as logo_err:
                        print(f"[Logo Download Skip]: {logo_err}")

                if parsed_target and parsed_target.get("body_text"):
                    company_name = parsed_target.get("title") or target_site
                    target_data_prompt = f"""
                    РЕАЛЬНЫЕ ДАННЫЕ И ПРАЙСЫ НАШЕГО САЙТА ({target_site}):
                    {parsed_target.get('body_text')}
                    """

            competitor_lengths = [
                len(c.raw_text)
                for c in (project.competitors or [])
                if c.raw_text and len(c.raw_text.strip()) > 200
            ]

            if competitor_lengths:
                avg_chars = sum(competitor_lengths) // len(competitor_lengths)
                min_chars = int(avg_chars * 0.85)
                max_chars = int(avg_chars * 1.15)
                volume_instruction = f"""
                    ТРЕБОВАНИЕ К ОБЪЕМУ СТАТЬИ (НА ОСНОВЕ РАСЧЕТА КОНКУРЕНТОВ):
                    • Средний объем текста у проанализированных конкурентов: ~{avg_chars} символов с пробелами.
                    • ОБЯЗАТЕЛЬНО напиши статью сопоставимого объема: целевой ориентир {avg_chars} символов (диапазон от {min_chars} до {max_chars} символов).
                    • Чтобы набрать этот объем без «воды», подробно раскрывай каждый блок, этапы, нюансы, приводи списки, таблицы и практические пояснения.
                    """
            else:
                volume_instruction = "ТРЕБОВАНИЕ К ОБЪЕМУ: Напиши развернутую статью объемом 5000–8000 символов с пробелами."

            print(
                f"[GenerateArticleUseCase]: Рассчитан целевой объем: {avg_chars if competitor_lengths else 'дефолт'} символов")

            primary_keyword = (project.keyword or topic).strip()
            prompt = f"""Напиши коммерческую SEO-статью / страницу услуги на тему '{topic}' СПЕЦИАЛЬНО ДЛЯ НАШЕЙ КОМПАНИИ: '{company_name}'.

                    {target_data_prompt}

                    {volume_instruction}

                    ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ДЛЯ МЕТА-ТЕГОВ:
                    • В блоке meta:
                        • В блоке meta генерируй ТОЛЬКО Description (140-160 символов, содержит ключ '{primary_keyword}' + '{company_name}').
                        • КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять тег <h1> и поле Title. Начинай статью сразу с первого абзаца и подзаголовков <h2>.
                     
                    СТРОГИЕ ПРАВИЛА И СТРУКТУРА:
                    {SEO_GENERATE_ARTICLE}

                    ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ:
                    {instructions}

                    {ARTICLE_HTML_FORMAT_TEXT}
                    """

            # 2. Генерация текста статьи
            content, reasoning, updated_history = await self._kie.completion_with_history(
                history=list(project.chat_history),
                user_prompt=prompt
            )
            content = normalize_article_html(content)

            # 3. Расчет SEO-метрик
            clean_text = re.sub(r"<style[^>]*>.*?</style>", " ", content, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r"<[^>]+>", " ", clean_text)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()

            char_count = len(clean_text)
            char_count_no_spaces = len(clean_text.replace(" ", ""))

            seo_metrics_dict = {}
            try:
                nausea_res = self._text_ai_service.calculate_nausea(
                    CalculateNauseaRequest(text=clean_text)
                )
                detect_res = await self._text_ai_service.detect_ai(clean_text)

                seo_metrics_dict = {
                    "classicNausea": nausea_res.classic_nausea,
                    "academicNausea": nausea_res.academic_nausea,
                    "totalWords": nausea_res.total_words,
                    "uniqueWords": nausea_res.unique_words,
                    "charCount": char_count,
                    "charCountNoSpaces": char_count_no_spaces,
                    "topWords": [w.model_dump(by_alias=True) for w in nausea_res.top_words],
                    "aiPercentage": detect_res.ai_percentage,
                    "humanPercentage": detect_res.human_percentage,
                    "aiReason": detect_res.reason,
                }
                print(
                    f"[SEO Metrics]: Символов={char_count}, Тошнота={nausea_res.academic_nausea}%, Человечность={detect_res.human_percentage}%")
            except Exception as metric_err:
                print(f"⚠️ [SEO Metrics Warning]: {metric_err}")

            # 4. Генерация картинок с передачей файла логотипа (bytes)
            generated_images: list[dict[str, str]] = []
            try:
                img_prompt_request = GENERATE_MULTIPLE_IMAGES_PROMPT_TEMPLATE.format(
                    topic=topic,
                    company_name=company_name,
                    images_count=images_count,
                )
                prompts_json_text = await self._kie.generate_completion(
                    [{"role": "user", "content": img_prompt_request}]
                )
                clean_json_str = (
                    prompts_json_text.strip()
                    .removeprefix("```json")
                    .removeprefix("```")
                    .removesuffix("```")
                    .strip()
                )
                image_configs = json.loads(clean_json_str)[:images_count]

                async def generate_single(idx: int, item: dict[str, str]) -> dict[str, str] | None:
                    try:
                        url = await self._image_gateway.generate_and_save_image(
                            prompt=item["prompt"],
                            filename_prefix=f"proj_{project.id.hex[:6]}_img{idx}",
                            image_reference_bytes=logo_bytes,
                        )
                        return {
                            "url": url,
                            "alt": item.get("alt", topic),
                            "caption": item.get("caption", ""),
                        }
                    except Exception as err:
                        print(f"⚠️ [Image {idx} Error]: {err}")
                        return None

                tasks = [generate_single(i, c) for i, c in enumerate(image_configs, 1)]
                results = await asyncio.gather(*tasks)
                generated_images = [r for r in results if r is not None]

                if generated_images:
                    content = inject_multiple_images_to_article(content, generated_images)
            except Exception as img_err:
                print(f"⚠️ [Images Warning]: {img_err}")

            # 5. Сохранение в БД
            if updated_history and updated_history[-1].get("role") == "assistant":
                updated_history[-1]["content"] = content

            project.chat_history = updated_history
            flag_modified(project, "chat_history")

            article = Article(
                project_id=project.id,
                title=topic,
                content=content,
                reasoning=reasoning,
                seo_metrics=seo_metrics_dict,
            )
            await uow.articles.add(article)
            save_article_to_html(article)

            return GenerateArticleResult(
                article=article,
                target_site=target_site or None,
                target_site_parse=target_site_parse,
                images_urls=[img["url"] for img in generated_images],
            )