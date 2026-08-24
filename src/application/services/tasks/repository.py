
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.infrastructure.database.base_repository import BaseRepository
from src.infrastructure.database.models.tasks import GenerationTask


class TaskRepository(BaseRepository[GenerationTask]):
    def __init__(self, session: AsyncSession):
        super().__init__(GenerationTask, session)

    async def get_all_by_user(self, user_id: uuid.UUID) -> list[GenerationTask]:
        stmt = (
            select(GenerationTask)
            .where(GenerationTask.user_id == user_id)
            .order_by(GenerationTask.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())