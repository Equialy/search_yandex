from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from src.infrastructure.database.models.competitors import Article
from pydantic import BaseModel, ConfigDict, Field

@dataclass(slots=True, frozen=True)
class GenerateArticleDTO:
    project_id: uuid.UUID
    topic: str
    instructions: str = ""
    target_site: str = ""
    user_id: uuid.UUID | None = None
    images_count: int = 2


@dataclass(slots=True, frozen=True)
class TargetSiteContext:
    target_site: str | None
    target_site_parse: dict[str, Any] | None
    cdn_logo_url: str | None
    company_name: str
    brand_fact_sheet: BrandFactSheet | None = None

@dataclass(slots=True, frozen=True)
class ArticleVolumeTarget:
    min_chars: int
    max_chars: int
    prompt_instruction: str


@dataclass(slots=True)
class GenerateArticleResult:
    article: Article
    target_site: str | None
    target_site_parse: dict[str, Any] | None
    images_urls: list[str] | None = None
    meta_title: str = ""
    meta_description: str = ""
    meta_h1: str = ""


class CompetitorContextDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    title: str | None = None
    graph_data: dict[str, Any] = Field(default_factory=dict)
    raw_text: str | None = None
    summary: str | None = None


class ProjectSnapshotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    keyword: str
    competitors: list[CompetitorContextDTO] = Field(default_factory=list)

class BrandLinkDTO(BaseModel):
    url: str
    anchor: str


class BrandFactSheet(BaseModel):
    company_name: str = "Наша компания"
    city_or_region: str = ""
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    usp_and_experience: list[str] = Field(default_factory=list)
    services_summary: str = ""
    internal_links: list[BrandLinkDTO] = Field(default_factory=list)

    def to_prompt_block(self) -> str:
        lines = [f"- Название компании / бренда: {self.company_name}"]
        if self.city_or_region:
            lines.append(f"- Город / регион работы: {self.city_or_region}")
        if self.services_summary:
            lines.append(f"- Специализация: {self.services_summary}")
        if self.phones:
            lines.append(f"- Телефоны: {', '.join(self.phones)}")
        if self.emails:
            lines.append(f"- Email: {', '.join(self.emails)}")
        if self.usp_and_experience:
            lines.append("- Подтверждённые факты, опыт, лицензии, УТП:")
            lines.extend(f"  • {fact}" for fact in self.usp_and_experience[:6])
        if self.internal_links:
            lines.append(
                "- ВНУТРЕННЯЯ ПЕРЕЛИНКОВКА (органично вставь 2–4 подходящие по смыслу ссылки в текст статьи "
                'как <a href="URL">анкор</a>; использовать можно ТОЛЬКО эти URL):'
            )
            lines.extend(f"  • {link.anchor} — {link.url}" for link in self.internal_links[:5])
        return "\n".join(lines)