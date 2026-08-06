import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.base_repository import BaseRepository
from src.infrastructure.database.models.competitors import Article, CompetitorData, Project


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, session: AsyncSession):
        super().__init__(Project, session)

    async def get_with_relations(self, project_id: uuid.UUID) -> Project | None:
        stmt = (
            select(Project)
            .where(Project.id == project_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class CompetitorRepository(BaseRepository[CompetitorData]):
    def __init__(self, session: AsyncSession):
        super().__init__(CompetitorData, session)


class ArticleRepository(BaseRepository[Article]):
    def __init__(self, session: AsyncSession):
        super().__init__(Article, session)