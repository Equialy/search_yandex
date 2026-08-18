import uuid

from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.competitors import Project


class GetProjectUseCase:
    """Загрузка проекта с конкурентами и статьями (без повторной генерации)."""

    def __init__(self, uow: UnitOfWorkProtocol):
        self._uow = uow

    async def execute(self, project_id: uuid.UUID, user_id: uuid.UUID) -> Project:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id, user_id=user_id)
            if not project:
                raise ValueError("Проект не найден")
            return project