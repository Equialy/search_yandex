import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.infrastructure.database.base_repository import BaseRepository
from src.infrastructure.database.models.agent import AgentChat
from src.infrastructure.database.models.competitors import Article, CompetitorData, Project


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, session: AsyncSession):
        super().__init__(Project, session)

    async def get_with_relations(self, project_id: uuid.UUID, user_id: uuid.UUID| None = None) -> Project | None:
        stmt = (
            select(Project)
            .where(Project.id == project_id)
            .options(
                selectinload(Project.competitors),
                selectinload(Project.articles),
            )
        )
        if user_id is not None:
            stmt = stmt.where(Project.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_ordered_by_updated(self,  user_id: uuid.UUID, skip: int = 0, limit: int = 50) -> list[Project]:
        stmt = (
            select(Project)
            .where(Project.user_id == user_id)
            .options(
                selectinload(Project.competitors),
                selectinload(Project.articles),
            )
            .order_by(Project.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())


class CompetitorRepository(BaseRepository[CompetitorData]):
    def __init__(self, session: AsyncSession):
        super().__init__(CompetitorData, session)

    async def get_by_project_id(self, project_id: uuid.UUID) -> list[CompetitorData]:
        stmt = (
            select(CompetitorData)
            .where(CompetitorData.project_id == project_id)
            .order_by(CompetitorData.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ArticleRepository(BaseRepository[Article]):
    def __init__(self, session: AsyncSession):
        super().__init__(Article, session)

    async def get_by_project_id(self, project_id: uuid.UUID) -> list[Article]:
        stmt = (
            select(Article)
            .where(Article.project_id == project_id)
            .order_by(Article.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())



class AgentChatRepository(BaseRepository[AgentChat]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentChat, session)

    async def get_all_ordered_by_updated(self) -> list[AgentChat]:
        stmt = select(AgentChat).order_by(AgentChat.updated_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())