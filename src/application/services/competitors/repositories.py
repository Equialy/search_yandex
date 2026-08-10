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
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_ordered_by_updated(self, skip: int = 0, limit: int = 50) -> list[Project]:
        stmt = select(Project).order_by(Project.updated_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CompetitorRepository(BaseRepository[CompetitorData]):
    def __init__(self, session: AsyncSession):
        super().__init__(CompetitorData, session)

    async def get_by_project_id(self, project_id: uuid.UUID) -> list[CompetitorData]:
        stmt = select(CompetitorData).where(CompetitorData.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())



class ArticleRepository(BaseRepository[Article]):
    def __init__(self, session: AsyncSession):
        super().__init__(Article, session)