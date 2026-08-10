# src/application/use_cases/generate_article.py

import uuid
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import SEO_GUIDELINE_TEXT
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.openai_gateway import OpenAiGateway  # или KieApiGateway


class GenerateArticleUseCase:
    def __init__(self, uow: UnitOfWorkProtocol, ai_gateway: OpenAiGateway):
        self._uow = uow
        self._kie = ai_gateway

    async def execute(
        self,
        project_id: uuid.UUID,
        topic: str,
        instructions: str = "",
        target_site: str = ""
    ) -> Article:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id)
            if not project:
                raise ValueError("Проект не найден")

            company_name = target_site if target_site else "Наша компания"

            prompt = f"""Напиши коммерческую SEO-статью / страницу услуги на тему '{topic}' СПЕЦИАЛЬНО ДЛЯ НАШЕЙ КОМПАНИИ: '{company_name}'.

ОБЯЗАТЕЛЬНАЯ СТРУКТУРА СТАТЬИ ПО МЕТОДИЧКЕ (СТРОГО ВКЛЮЧИ ВСЕ РАЗДЕЛЫ):

1. TITLE И DESCRIPTION:
   - Title (до 70 симв.): главный ключ + '{company_name}' + выгода.
   - Description (150-160 симв.): главный ключ + '{company_name}' + условия/цена.

2. H1: Единый главный заголовок страницы с главным ключом.

3. ВВОДНЫЙ БЛОК И ОПИСАНИЕ УСЛУГИ:
   - Первый абзац обязательно содержит главный ключ и название компании '{company_name}'.

4. ОБЯЗАТЕЛЬНЫЙ РАЗДЕЛ: "АНАЛИЗ И СРАВНЕНИЕ С КОНКУРЕНТАМИ РЫНКА":
   - Проведи прямой разбор сильных и слабых сторон конкурентов на рынке по данному запросу.
   - Укажи минус и слабые места большинства конкурентов (скрытые наценки, затянутые сроки, отсутствие гарантий, шаблонный подход).
   - Покажи, как компания '{company_name}' устраняет эти слабые стороны.
   - Построй Markdown-ТАБЛИЦУ сравнения: "Критерий | Конкуренты на рынке | Наша компания ({company_name})".

5. НАШИ ПРЕИМУЩЕСТВА И ПОЗИЦИОНИРОВАНИЕ:
   - Маркированный список преимуществ с конкретными фактами и цифрами.

6. ЭТАПЫ РАБОТ И ФАКТОРЫ СТОИМОСТИ:
   - Четкие шаги оказания услуги и таблица цен/пакетов.

7. КЕЙСЫ, ДОКАЗАТЕЛЬСТВА И ГАРАНТИИ:
   - Конкретные результаты, цифры и официальные гарантии договора.

8. ФИНАЛЬНЫЙ АБЗАЦ:
   - Последний абзац обязательно содержит главный ключ и название компании '{company_name}'.

СТРОГИЕ ПРАВИЛА ВЕРСТКИ И МЕТОДИЧКИ:
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