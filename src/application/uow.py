from typing import Protocol
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.competitors.repositories import ProjectRepository, CompetitorRepository, \
    ArticleRepository, AgentChatRepository
from src.application.services.users.repository import UserRepository


class UnitOfWorkProtocol(Protocol):
    projects: ProjectRepository
    competitors: CompetitorRepository
    articles: ArticleRepository
    agent_chats: AgentChatRepository

    users: UserRepository

    async def __aenter__(self) -> "UnitOfWorkProtocol": ...
    async def __aexit__(self, exc_type, exc_val, exc_tb): ...
    async def commit(self): ...
    async def rollback(self): ...


class UnitOfWork(UnitOfWorkProtocol):
    def __init__(self, session: AsyncSession):
        self.session = session
        self.projects = ProjectRepository(session)
        self.competitors = CompetitorRepository(session)
        self.articles = ArticleRepository(session)
        self.agent_chats = AgentChatRepository(session=session)
        self.users = UserRepository(session=session)


    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
        await self.session.close()

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()