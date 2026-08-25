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


class ParseSiteRequest(BaseDTO):
    url: str = Field(..., example="https://my-site.ru")


class TargetSiteParseDTO(BaseDTO):
    url: str
    title: str | None = None
    description: str | None = None
    raw_text: str | None = None
    is_blocked: bool = False


class ChatContextRequest(BaseDTO):
    prompt: str = Field(..., example="Напиши краткое содержание ранее сгенерированной статьи")


class ChatHistoryMessageDTO(BaseDTO):
    role: str
    content: str
    message_type: str = "message"
    is_truncated: bool = False
    has_image: bool = False
    html_content: str | None = None
    article_version: int | None = None

class SeoMetricsDTO(BaseDTO):
    classic_nausea: float | None = None
    academic_nausea: float | None = None
    total_words: int | None = None
    unique_words: int | None = None
    ai_percentage: int | None = None
    human_percentage: int | None = None
    ai_reason: str | None = None
    top_words: list[Any] = Field(default_factory=list)

class ArticleHistoryItemDTO(BaseDTO):
    id: uuid.UUID
    title: str
    content_preview: str = ""
    reasoning: str | None = None
    created_at: datetime
    content: str
    seo_metrics: SeoMetricsDTO | None = None


class ArticleResponse(BaseDTO):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    content: str
    reasoning: str | None = None
    created_at: datetime
    target_site: str | None = None
    target_site_parse: TargetSiteParseDTO | None = None
    content_preview: str | None = None
    seo_metrics: SeoMetricsDTO | None = None


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
    chat_history: list[ChatHistoryMessageDTO] = []
    generation_history: list[ArticleHistoryItemDTO] = []
    latest_article_content: str | None = None
    latest_article_title: str | None = None
    created_at: datetime
    updated_at: datetime
