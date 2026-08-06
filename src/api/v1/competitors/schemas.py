import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class BaseDTO(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True
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
    projectId: uuid.UUID
    title: str
    content: str
    createdAt: datetime


class ProjectAnalysisResponse(BaseDTO):
    projectId: uuid.UUID
    keyword: str
    foundUrls: list[str]
    status: str