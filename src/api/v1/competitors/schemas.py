# src/api/v1/competitors/schemas.py

import uuid
from datetime import datetime
from typing import Any
from pydantic import AliasChoices, AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class BaseDTO(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=lambda field_name: AliasChoices(field_name, to_camel(field_name)),
            serialization_alias=to_camel,
        ),
    )


class AnalyzeCompetitorsRequest(BaseDTO):
    keyword: str | None = Field(default=None, example="купить кофемашину для дома")
    url: str | None = Field(default=None, example="https://mysite.ru/my-landing")
    limit: int = Field(default=3, ge=1, le=10)
    project_id: uuid.UUID | None = Field(default=None, description="Если указан, добавляем анализ в существующий проект")


class GenerateArticleRequest(BaseDTO):
    topic: str = Field(..., example="Топ 10 кофемашин 2026 года")
    instructions: str = Field(default="", example="Добавь таблицу сравнения цен")
    target_site: str | None = Field(default="", example="https://my-site.ru")


class ChatContextRequest(BaseDTO):
    prompt: str = Field(..., example="Напиши краткое содержание ранее сгенерированной статьи")


class ArticleResponse(BaseDTO):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    content: str
    reasoning: str | None = None
    created_at: datetime


class CompetitorDetailDTO(BaseDTO):
    id: uuid.UUID
    url: str
    title: str | None = None
    graph_data: Any = None
    raw_text: str | None = None
    summary: str | None = None


class ProjectAnalysisResponse(BaseDTO):
    project_id: uuid.UUID
    keyword: str
    found_urls: list[str]
    competitors: list[CompetitorDetailDTO] = []
    status: str


class ProjectListItemDTO(BaseDTO):
    id: uuid.UUID
    keyword: str
    created_at: datetime
    updated_at: datetime
    competitors_count: int = 0
    articles_count: int = 0


class ProjectDetailDTO(BaseDTO):
    id: uuid.UUID
    keyword: str
    competitors: list[CompetitorDetailDTO] = []
    articles: list[ArticleResponse] = []
    created_at: datetime
    updated_at: datetime
