from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

from src.application.harness.article_harness import VerificationReport
from src.application.use_cases.generate_article.dto import (
    ArticleVolumeTarget,
    TargetSiteContext,
)
from src.infrastructure.database.models.competitors import Article


class TargetBrandResolver(Protocol):
    async def resolve(self, target_site: str) -> TargetSiteContext: ...


class ArticleDraftGenerator(Protocol):
    async def generate_draft(
        self,
        *,
        topic: str,
        primary_keyword: str,
        company_name: str,
        brand_context: str = "",
        instructions: str,
        volume: ArticleVolumeTarget,
        competitors_block: str,
    ) -> tuple[str, str, str]:
        """Возвращает (raw_html, reasoning, used_prompt)."""
        ...


class ArticleVerifier(Protocol):
    async def verify_and_refine(
        self,
        raw_html: str,
        *,
        topic: str,
        primary_keyword: str,
        target_min_chars: int | None = None,
        target_max_chars: int | None = None,
    ) -> VerificationReport: ...


class ArticleIllustrator(Protocol):
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
        """Возвращает (html_with_images, image_urls)."""
        ...


class ArticleFileExporter(Protocol):
    def save(self, article: Article) -> Path: ...