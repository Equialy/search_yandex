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