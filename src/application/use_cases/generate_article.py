# src/application/use_cases/generate_article.py

import uuid
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import SEO_GUIDELINE_TEXT  # <--- ИМПОРТ МЕТОДИЧКИ
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

            # Формируем запрос, внедряя полную методичку
            prompt = f"""Напиши экспертную SEO-статью / страницу услуги на тему '{topic}'.
            
            ВЫПОЛНЯЙ ВСЕ ТРЕБОВАНИЯ СТРОГО ПО МЕТОДИЧКЕ НИЖЕ:
            
            {SEO_GUIDELINE_TEXT}
            
            ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ:
            {instructions}
            """

            content, reasoning, updated_history = await self._kie.completion_with_history(
                history=list(project.chat_history),
                user_prompt=prompt
            )

            project.chat_history = updated_history
            flag_modified(project, "chat_history")

            article = Article(
                project_id=project.id,
                title=topic,
                content=content,
                reasoning=reasoning
            )
            await uow.articles.add(article)

            return article