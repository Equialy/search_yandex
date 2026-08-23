# src/application/use_cases/generate_article.py

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import (
    ARTICLE_HTML_FORMAT_TEXT,
    SEO_GENERATE_ARTICLE,
    GENERATE_IMAGE_PROMPT_TEMPLATE,
)
from src.application.article_format import normalize_article_html, inject_image_to_article
from src.application.uow import UnitOfWorkProtocol
from src.config.settings import BASE_DIR
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.openai_gateway import OpenAiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.image_gateway import ImageGenerationGateway

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


@dataclass
class GenerateArticleResult:
    article: Article
    target_site: str | None
    target_site_parse: dict[str, Any] | None
    image_url: str | None = None


def save_article_to_html(article: Article) -> Path:
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
            image_gateway: ImageGenerationGateway,  # <-- Добавили ImageGateway
    ):
        self._uow = uow
        self._kie = ai_gateway
        self._parser = parser_gateway
        self._image_gateway = image_gateway

    async def execute(
            self,
            project_id: uuid.UUID,
            topic: str,
            instructions: str = "",
            target_site: str = "",
            user_id: uuid.UUID | None = None
    ) -> GenerateArticleResult:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id, user_id=user_id)
            if not project:
                raise ValueError("Проект не найден")

            company_name = target_site if target_site else "Наша компания"
            target_data_prompt = ""
            target_site_parse: dict[str, Any] | None = None

            if target_site and (target_site.startswith("http://") or target_site.startswith("https://")):
                print(f"[GenerateArticleUseCase]: Скачиваем реальные прайсы вашего сайта {target_site}...")
                parsed_target = await self._parser.parse_site_to_graph(target_site)
                target_site_parse = build_target_site_parse(target_site, parsed_target)

                if parsed_target and parsed_target.get("body_text"):
                    company_name = parsed_target.get("title") or target_site
                    target_data_prompt = f"""
                    РЕАЛЬНЫЕ ДАННЫЕ И ПРАЙСЫ НАШЕГО САЙТА ({target_site}):
                    
                    Настоящие тексты и цены с нашего сайта:
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


            prompt = f"""Напиши коммерческую SEO-статью / страницу услуги на тему '{topic}' СПЕЦИАЛЬНО ДЛЯ НАШЕЙ КОМПАНИИ: '{company_name}'.

                    {target_data_prompt}
                    {volume_instruction}

                    СТРОГИЕ ПРАВИЛА И СТРУКТУРА:
                    {SEO_GENERATE_ARTICLE}

                    ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ:
                    {instructions}

                    {ARTICLE_HTML_FORMAT_TEXT}
                    """

            content, reasoning, updated_history = await self._kie.completion_with_history(
                history=list(project.chat_history),
                user_prompt=prompt
            )

            content = normalize_article_html(content)

            image_relative_url = None
            try:
                img_prompt_request = GENERATE_IMAGE_PROMPT_TEMPLATE.format(
                    topic=topic,
                    company_name=company_name
                )
                image_prompt = await self._kie.generate_completion(
                    [{"role": "user", "content": img_prompt_request}]
                )

                image_relative_url = await self._image_gateway.generate_and_save_image(
                    prompt=image_prompt.strip(),
                    filename_prefix=f"proj_{project.id.hex[:6]}"
                )

                content = inject_image_to_article(
                    html_content=content,
                    image_url=image_relative_url,
                    alt_text=f"{topic} - {company_name}",
                )
            except Exception as img_err:
                print(f" [Image Generation Warning]: Не удалось сгенерировать изображение: {img_err}")

            project.chat_history = updated_history
            flag_modified(project, "chat_history")

            article = Article(
                project_id=project.id,
                title=topic,
                content=content,
                reasoning=reasoning
            )
            await uow.articles.add(article)

            saved_article_file = save_article_to_html(article)
            print(f"[Article Saved to File]: {saved_article_file}")

            return GenerateArticleResult(
                article=article,
                target_site=target_site or None,
                target_site_parse=target_site_parse,
                image_url=image_relative_url,
            )