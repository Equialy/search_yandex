import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from src.api.v1.competitors.schemas import BaseDTO


class CreateTaskRequest(BaseDTO):
    keyword: str = Field(..., example="бухгалтерские услуги в Москве")
    target_site: str | None = Field(default=None, example="https://my-site.ru")
    topic: str | None = Field(default=None, example="Бухгалтерское обслуживание бизнеса")
    instructions: str = Field(default="", example="Сделай упор на тарифы и гарантии")
    sites_limit: int = Field(default=3, ge=1, le=10)
    project_id: uuid.UUID | None = Field(default=None, description="Если указан, добавляем в проект")


class TaskResponseDTO(BaseDTO):
    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None = None
    article_id: uuid.UUID | None = None
    keyword: str
    target_site: str | None = None
    topic: str | None = None
    instructions: str | None = None
    sites_limit: int
    status: str
    progress_message: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime