from typing import Any
from pydantic import BaseModel, Field


class ReportSchemaTask(BaseModel):
    id_task: int
    id_site: int
    site_key: str | None = None
    domain: str | None = None
    text_comment: str | None = None


class ReportsArticleResponse(BaseModel):
    success: bool
    task: ReportSchemaTask | None = None


class SendArticleReportPayload(BaseModel):
    id_task: int
    content: str
    text_title: str
    text_description: str
    text_H1: str
    text_count_char: int
    text_toshnota: int
    text_human: int
    concurent_metrix: str


class SendArticleReportResponse(BaseModel):
    success: bool
    message: str | None = None
    id_page: int | None = None
    id_task: int | None = None


class StartReportTaskRequest(BaseModel):
    id_task: int
    id_site: int
    site_key: str
    domain: str
    text_comment: str = ""
    sites_limit: int = Field(default=3, ge=1, le=10)
    topic: str | None = None