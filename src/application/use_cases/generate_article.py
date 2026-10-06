import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm.attributes import flag_modified

from src.api.v1.text_router.schema import CalculateNauseaRequest
from src.api.v1.text_router.service import TextAiService
from src.application.article_format import (
    has_styled_article_html,
    inject_multiple_images_to_article,
    normalize_article_html,
)
from src.application.prompts import (
    ARTICLE_HTML_FORMAT_TEXT,
    GENERATE_MULTIPLE_IMAGES_PROMPT_TEMPLATE,
    SEO_GENERATE_ARTICLE,
)
from src.application.uow import UnitOfWorkProtocol
from src.config.settings import BASE_DIR
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.image_kie_gateway import ImageKieGenerationGateway
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.utils.extract_data import (
    convert_svg_to_png_bytes,
    extract_html_metadata,
    normalize_logo_png,
    remove_meta_block_from_html,
)

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
    meta_title: str = ""
    meta_description: str = ""
    meta_h1: str = ""


def save_article_to_html(article: Article) -> Path:
    """
    Сохраняет сгенерированную HTML-статью на диск для резервной копии.
    """
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_path = EXPORTS_ARTICLES_DIR / f"article_{now_str}_{article.id}.html"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(article.content)
    return file_path


def save_article_to_txt(article: Article) -> Path:
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    data = {
        "id": str(article.id),
        "projectId": str(article.project_id),
        "title": article.title,
        "content": article.content,
        "reasoning": article.reasoning,
        "createdAt": article.created_at.isoformat() if article.created_at else datetime.now(timezone.utc).isoformat(),
    }

    file_path = EXPORTS_ARTICLES_DIR / f"article_{now_str}_{article.id}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return file_path


class GenerateArticleUseCase:
    def __init__(
            self,
            uow: UnitOfWorkProtocol,
            ai_gateway: KieApiGateway,
            parser_gateway: SiteParserGateway,
            image_gateway: ImageKieGenerationGateway,
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
            cdn_logo_url = None

            if target_site and target_site.startswith("http"):
                parsed_target = await self._parser.parse_site_to_graph(target_site)
                target_site_parse = build_target_site_parse(target_site, parsed_target)
                
                if parsed_target and parsed_target.get("body_text"):
                    company_name = parsed_target.get("title") or target_site
                    target_data_prompt = f"""
ДАННЫЕ И ПРАЙСЫ НАШЕГО САЙТА ({target_site}):
Title: {parsed_target.get('title')}
Description: {parsed_target.get('description')}
Текст и прайсы компании:
{parsed_target.get('body_text')}
"""

                logo_url = parsed_target.get("logo_url") if parsed_target else None
                if logo_url:
                    try:
                        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http_client:
                            logo_res = await http_client.get(logo_url)
                            if logo_res.status_code == 200 and len(logo_res.content) > 50:
                                raw_logo = logo_res.content
                                if logo_url.lower().endswith(".svg") or b"<svg" in raw_logo[:100].lower():
                                    raw_logo = convert_svg_to_png_bytes(raw_logo)

                                cdn_logo_url = await self._image_gateway.upload_image_to_cdn(raw_logo)
                    except Exception as err:
                        print(f"[Logo Upload Error]: {err}")

            competitor_lengths = []
            for c in (project.competitors or []):
                text = (c.graph_data.get("body_text") or c.raw_text or "").strip()
                if 200 < len(text) < 40000:
                    competitor_lengths.append(len(text))

            if competitor_lengths:
                avg_chars = sum(competitor_lengths) // len(competitor_lengths)
                target_chars = min(max(avg_chars, 5000), 20000)
                min_chars = int(target_chars * 0.85)
                max_chars = int(target_chars * 1.15)

                volume_instruction = f"""
ТРЕБОВАНИЕ К ОБЪЕМУ СТАТЬИ:
• Целевой ориентир объема: ~{target_chars} символов с пробелами (диапазон от {min_chars} до {max_chars} символов).
• Статья должна быть глубокой, полностью завершенной, с подробным раскрытием каждого этапа, списков и таблиц.
"""
            else:
                target_chars = 7500
                volume_instruction = "ТРЕБОВАНИЕ К ОБЪЕМУ: Напиши развернутую статью объемом 6000–9000 символов с пробелами. Обязательно доведи мысль до конца."

            print(f"[GenerateArticleUseCase]: Скорректирован безопасный объем: {target_chars} символов")

            primary_keyword = (project.keyword or topic).strip()

            prompt = f"""Ты — Senior Frontend & SEO разработчик и профессиональный коммерческий копирайтер.
Сгенерируй ГОТОВУЮ коммерческую статью / страницу услуги на тему '{topic}' СПЕЦИАЛЬНО ДЛЯ НАШЕЙ КОМПАНИИ: '{company_name}'.

{target_data_prompt}

{volume_instruction}

ЖЕСТКИЕ ТРЕБОВАНИЯ К HTML-РАЗМЕТКЕ (КАТЕГОРИЧЕСКИ ЗАПРЕЩЕН ГОЛЫЙ ТЕКСТ):
1. Весь ответ — единый HTML-код со стилями. Начни ответ СТРОГО с тега '<style>' и закончи тегом '</div>'.
2. Сразу после блока </style> помести открывающий тег:
   <div class="seo-article">
3. Мета-блок оформи строго внутри тегов:
   <div class="seo-article__meta">
     <p><strong>Title:</strong> {primary_keyword}</p>
     <p><strong>Description:</strong> 140–160 символов: главный ключ {primary_keyword} + {company_name} + конкретные выгоды.</p>
   </div>
4. Главный заголовок: СТРОГО один тег <h1>{primary_keyword}</h1>.
5. КАЖДЫЙ абзац статьи ОБЯЗАТЕЛЬНО оборачивай в тег <p>...</p>. Запрещено выводить неразмеченный текст!
6. Подзаголовки блоков — СТРОГО в тегах <h2>...</h2> и <h3>...</h3>.
7. Списки — только в <ul><li>...</li></ul> или <ol><li>...</li></ol>.
8. Таблицы — только валидный HTML: <table class="seo-article__table"><thead><tr><th>...</th></tr></thead><tbody><tr><td>...</td></tr></tbody></table>. Не используй псевдографику!
9. В самом конце статьи обязательно закрой корневой тег: </div>.

СТРОГИЕ ПРАВИЛА И СТИЛЬ:
{SEO_GENERATE_ARTICLE}

ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ:
{instructions}

{ARTICLE_HTML_FORMAT_TEXT}
"""

            content, reasoning, updated_history = await self._kie.completion_with_history(
                history=list(project.chat_history),
                user_prompt=prompt,
                reasoning_effort="high"
            )

            if len(content.strip()) < 1500 or not has_styled_article_html(content):
                print(f"[GenerateArticleUseCase Warning]: Модель прислала некорректную структуру ({len(content)} симв.). Запуск принудительного исправления...")
                retry_prompt = (
                    "ОШИБКА: Твой ответ не является валидным HTML или в нем отсутствуют теги <p> и <h2>!\n"
                    f"Напиши ПОЛНУЮ готовую статью на тему '{topic}' объемом ~{target_chars} символов. "
                    "Начни ответ СТРОГО со строки '<style>' и обязательно оберни КАЖДЫЙ абзац в тег <p>...</p>, "
                    "а каждый раздел в <h2>...</h2>!"
                )
                content, reasoning, updated_history = await self._kie.completion_with_history(
                    history=updated_history,
                    user_prompt=retry_prompt,
                    reasoning_effort="high"
                )

            if len(content.strip()) < 1000 or not has_styled_article_html(content):
                print(f"[GenerateArticleUseCase Warning]: Модель прислала отписку ({len(content)} симв.). Запускаем принудительный дожим...")
                retry_prompt = (
                    "ОШИБКА: Ты прислал короткое текстовое обещание/план вместо самой статьи!\n"
                    "ЗАПРЕЩЕНО писать любые комментарии. Начни ответ СТРОГО с тега '<style>' "
                    f"и сгенерируй ПОЛНУЮ готовую HTML-статью на тему '{topic}' целевым объемом ~{target_chars} символов прямо сейчас!"
                )
                content, reasoning, updated_history = await self._kie.completion_with_history(
                    history=updated_history,
                    user_prompt=retry_prompt
                )

            # 4. Очистка и нормализация HTML
            content = re.sub(r"cite[a-zA-Z0-9_:]+", "", content)
            content = re.sub(r"【\d+[:†]?\d*†?[^】]*】", "", content)

            content = normalize_article_html(content)
            h1_val, title_val, desc_val = extract_html_metadata(content, topic)
            content = remove_meta_block_from_html(content)

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
                print(f"[SEO Metrics]: Символов={char_count}, Тошнота={nausea_res.academic_nausea}%, Человечность={detect_res.human_percentage}%")
            except Exception as metric_err:
                print(f"⚠️ [SEO Metrics Warning]: {metric_err}")

            # 6. Генерация картинок через KIE.AI (Nano Banana 2 Lite)
            generated_images = []
            try:
                img_prompt_req = GENERATE_MULTIPLE_IMAGES_PROMPT_TEMPLATE.format(
                    topic=topic,
                    company_name=company_name,
                    images_count=images_count,
                )
                prompts_raw = await self._kie.generate_completion([{"role": "user", "content": img_prompt_req}])

                json_match = re.search(r"\[\s*\{.*\}\s*\]", prompts_raw or "", re.DOTALL)
                if json_match:
                    image_configs = json.loads(json_match.group(0))[:images_count]
                else:
                    image_configs = [
                        {
                            "prompt": f"Commercial 4K photography, specialist with {company_name} logo on uniform, {topic}, photorealistic",
                            "alt": topic,
                            "caption": "",
                        }
                        for _ in range(images_count)
                    ]

                async def generate_single(idx: int, item: dict[str, str]):
                    try:
                        url = await self._image_gateway.generate_and_save_image(
                            prompt=item["prompt"],
                            filename_prefix=f"proj_{project.id.hex[:6]}_img{idx}",
                            image_url=cdn_logo_url,
                        )
                        return {"url": url, "alt": item.get("alt", topic), "caption": item.get("caption", "")}
                    except Exception as err:
                        print(f"[Image {idx} Error]: {err}")
                        return None

                tasks = [generate_single(i, c) for i, c in enumerate(image_configs, 1)]
                results = await asyncio.gather(*tasks)
                generated_images = [r for r in results if r]

                if generated_images:
                    content = inject_multiple_images_to_article(content, generated_images)
            except Exception as err:
                print(f"[Images Generation Error]: {err}")

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
            save_article_to_txt(article)

            return GenerateArticleResult(
                article=article,
                target_site=target_site or None,
                target_site_parse=target_site_parse,
                images_urls=[img["url"] for img in generated_images],
                meta_title=title_val,
                meta_description=desc_val,
                meta_h1=h1_val,
            )