import uuid
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.kie_api import KieApiGateway


class GenerateArticleUseCase:
    def __init__(self, uow: UnitOfWorkProtocol, kie_gateway: KieApiGateway):
        self._uow = uow
        self._kie = kie_gateway

    async def execute(self, project_id: uuid.UUID, topic: str, instructions: str) -> Article:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id)
            if not project:
                raise ValueError("Проект не найден")

            prompt = f"Напиши SEO-статью на тему '{topic}'. Используй контекст конкурентов. Инструкции: {instructions}"

            content, updated_history = await self._kie.completion_with_history(
                history=list(project.chat_history),
                user_prompt=prompt
            )

            project.chat_history = updated_history

            article = Article(
                project_id=project.id,
                title=topic,
                content=content
            )
            await uow.articles.add(article)

            return article