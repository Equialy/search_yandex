# src/application/use_cases/chat_context.py

import uuid
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import CHAT_HTML_REFINEMENT_HINT
from src.application.uow import UnitOfWorkProtocol
from src.application.article_format import normalize_article_html
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.openai_gateway import OpenAiGateway


class ContinueContextChatUseCase:
    """Продолжение диалога/доработка статьи с сохранением всего контекста."""

    def __init__(self, uow: UnitOfWorkProtocol, ai_gateway: OpenAiGateway):
        self._uow = uow
        self._openai = ai_gateway

    async def execute(self, project_id: uuid.UUID, user_prompt: str) -> str:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id)
            if not project:
                raise ValueError("Проект не найден")

            # РАСПАКОВЫВАЕМ 3 ПЕРЕМЕННЫЕ: response_text, reasoning, updated_history
            wrapped_prompt = f"{user_prompt.strip()}\n\n{CHAT_HTML_REFINEMENT_HINT}"

            response_text, reasoning, updated_history = await self._openai.completion_with_history(
                history=list(project.chat_history),
                user_prompt=wrapped_prompt
            )

            stripped = response_text.strip()
            if stripped.startswith("```") or stripped.startswith("<"):
                response_text = normalize_article_html(response_text)

            project.chat_history = updated_history
            flag_modified(project, "chat_history")

            return response_text