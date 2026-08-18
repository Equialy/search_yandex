from dataclasses import dataclass
from datetime import datetime
import uuid

from src.application.uow import UnitOfWorkProtocol


@dataclass
class ProjectListItem:
    id: uuid.UUID
    keyword: str
    created_at: datetime
    updated_at: datetime
    competitors_count: int
    articles_count: int


class ListProjectsUseCase:
    def __init__(self, uow: UnitOfWorkProtocol):
        self._uow = uow

    async def execute(self, user_id: uuid.UUID) -> list[ProjectListItem]:
        async with self._uow as uow:
            projects = await uow.projects.get_all_ordered_by_updated(user_id=user_id)
            return [
                ProjectListItem(
                    id=p.id,
                    keyword=p.keyword,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                    competitors_count=len(p.competitors or []),
                    articles_count=len(p.articles or []),
                )
                for p in projects
            ]