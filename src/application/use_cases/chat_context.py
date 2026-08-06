# src/application/use_cases/chat_context.py

import uuid
from sqlalchemy.orm.attributes import flag_modified

from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.gateways.kie_api import KieApiGateway


class ContinueContextChatUseCase:
    """Продолжение диалога/доработка статьи с сохранением всего контекста."""

    def __init__(self, uow: UnitOfWorkProtocol, kie_gateway: KieApiGateway):
        self._uow = uow
        self._kie = kie_gateway

    async def execute(self, project_id: uuid.UUID, user_prompt: str) -> str:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id)
            if not project:
                raise ValueError("Проект не найден")

            # Отправляем накопительный контекст в KIE.AI
            response_text, updated_history = await self._kie.completion_with_history(
                history=list(project.chat_history),
                user_prompt=user_prompt
            )

            # Обновляем историю сообщений и сохраняем
            project.chat_history = updated_history
            flag_modified(project, "chat_history")

            return response_text