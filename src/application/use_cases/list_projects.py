
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.competitors import Project


class ListProjectsUseCase:
    """Получение списка всех проектов/сессий для выбора на фронтенде."""

    def __init__(self, uow: UnitOfWorkProtocol):
        self._uow = uow

    async def execute(self) -> list[Project]:
        async with self._uow as uow:
            return await uow.projects.get_all_ordered_by_updated()