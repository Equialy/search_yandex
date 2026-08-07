
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
    keyword: str = Field(..., example="купить кофемашину для дома")
    limit: int = Field(default=3, ge=1, le=10)


class GenerateArticleRequest(BaseDTO):
    topic: str = Field(..., example="Топ 10 кофемашин 2026 года")
    instructions: str = Field(default="", example="Добавь таблицу сравнения цен")


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
    summary: str | None = None


class ProjectAnalysisResponse(BaseDTO):
    project_id: uuid.UUID
    keyword: str
    found_urls: list[str]
    competitors: list[CompetitorDetailDTO] = []
    status: str