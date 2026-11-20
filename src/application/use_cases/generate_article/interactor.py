from __future__ import annotations

import uuid
from sqlalchemy.orm.attributes import flag_modified

from src.application.uow import UnitOfWorkProtocol
from src.application.use_cases.generate_article.dto import (
    GenerateArticleDTO,
    GenerateArticleResult,
)
from src.application.use_cases.generate_article.interfaces import (
    ArticleDraftGenerator,
    ArticleFileExporter,
    ArticleIllustrator,
    ArticleVerifier,
    TargetBrandResolver,
)
from src.application.use_cases.generate_article.services import (
    build_competitors_block,
    build_volume_target,
)
from src.infrastructure.database.models.competitors import Article


class GenerateArticleInteractor:
    """Сценарий генерации SEO-статьи (только оркестрация шагов)."""

    def __init__(
        self,
        uow: UnitOfWorkProtocol,
        brand_resolver: TargetBrandResolver,
        draft_generator: ArticleDraftGenerator,
        verifier: ArticleVerifier,
        illustrator: ArticleIllustrator,
        exporter: ArticleFileExporter,
    ):
        self._uow = uow
        self._brand_resolver = brand_resolver
        self._draft_generator = draft_generator
        self._verifier = verifier
        self._illustrator = illustrator
        self._exporter = exporter

    async def __call__(self, dto: GenerateArticleDTO) -> GenerateArticleResult:
        # 1. Быстро читаем проект и конкурентов (не держим транзакцию на время AI-вызовов)
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(dto.project_id, user_id=dto.user_id)
            if not project:
                raise ValueError("Проект не найден")
            competitors = list(project.competitors or [])
            primary_keyword = (project.keyword or dto.topic).strip()

        # 2. Сбор контекста и целевых метрик
        brand = await self._brand_resolver.resolve(dto.target_site)
        volume = build_volume_target(competitors)
        competitors_block = build_competitors_block(competitors)
        site_url = brand.target_site or dto.target_site or ""
        brand_context = brand.brand_fact_sheet.to_prompt_block() if brand.brand_fact_sheet else ""

        # 3. Генерация черновика
        raw_html, reasoning, prompt = await self._draft_generator.generate_draft(
            topic=dto.topic,
            primary_keyword=primary_keyword,
            company_name=brand.company_name,
            target_site=site_url,
            brand_context=brand_context,
            instructions=dto.instructions,
            volume=volume,
            competitors_block=competitors_block,
        )

        # 4. Harness-верификация и самоисправление ДО генерации картинок
        report = await self._verifier.verify_and_refine(
            raw_html,
            topic=dto.topic,
            primary_keyword=primary_keyword,
            target_site=site_url,
            target_min_chars=volume.min_chars,
            target_max_chars=volume.max_chars,
        )

        # 5. Иллюстрирование проверенного текста
        final_html, image_urls = await self._illustrator.illustrate(
            report.html,
            project_id=dto.project_id,
            topic=dto.topic,
            company_name=brand.company_name,
            cdn_logo_url=brand.cdn_logo_url,
            images_count=dto.images_count,
        )

        # 6. Атомарное сохранение результата в БД и экспорт на диск
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(dto.project_id, user_id=dto.user_id)
            if not project:
                raise ValueError("Проект не найден")

            history = list(project.chat_history)
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": final_html})
            project.chat_history = history
            flag_modified(project, "chat_history")

            article = Article(
                project_id=project.id,
                title=dto.topic,
                content=final_html,
                reasoning=reasoning,
                seo_metrics=report.seo_metrics,
            )
            await uow.articles.add(article)

        self._exporter.save(article)

        return GenerateArticleResult(
            article=article,
            target_site=brand.target_site,
            target_site_parse=brand.target_site_parse,
            images_urls=image_urls,
            meta_title=report.title,
            meta_description=report.description,
            meta_h1=report.h1,
        )

    # Временный адаптер обратной совместимости для старых вызовов .execute(...)
    async def execute(
        self,
        project_id: uuid.UUID,
        topic: str,
        instructions: str = "",
        target_site: str = "",
        user_id: uuid.UUID | None = None,
        images_count: int = 2,
    ) -> GenerateArticleResult:
        return await self(
            GenerateArticleDTO(
                project_id=project_id,
                topic=topic,
                instructions=instructions,
                target_site=target_site,
                user_id=user_id,
                images_count=images_count,
            )
        )