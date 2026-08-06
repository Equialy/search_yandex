import uuid
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.llm_gateway import LLMGateway


class GenerateArticleUseCase:
    def __init__(self, uow: UnitOfWorkProtocol, llm_gateway: LLMGateway):
        self._uow = uow
        self._llm = llm_gateway

    async def execute(self, project_id: uuid.UUID, topic: str, instructions: str) -> Article:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id)
            if not project:
                raise ValueError("Проект не найден")

            prompt = f"Напиши SEO-статью на тему '{topic}'. Используй контекст конкурентов. Инструкции: {instructions}"

            # Генерация с учетом накапливаемой истории (chat_history)
            content, updated_history = await self._llm.completion_with_history(
                history=list(project.chat_history),
                user_prompt=prompt
            )

            # Обновляем контекст проекта
            project.chat_history = updated_history

            # Сохраняем статью
            article = Article(
                project_id=project.id,
                title=topic,
                content=content
            )
            await uow.articles.add(article)

            return article