# src/application/use_cases/analyze_competitors.py

import uuid
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import SEO_GUIDELINE_TEXT
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.competitors import CompetitorData, Project
from src.infrastructure.gateways.openai_gateway import OpenAiGateway  # или KieApiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway


class AnalyzeCompetitorsUseCase:
    def __init__(
            self,
            uow: UnitOfWorkProtocol,
            yandex_gateway: YandexSearchGateway,
            parser_gateway: SiteParserGateway,
            ai_gateway: OpenAiGateway
    ):
        self._uow = uow
        self._yandex = yandex_gateway
        self._parser = parser_gateway
        self._kie = ai_gateway

    async def execute(
            self,
            keyword: str | None = None,
            url: str | None = None,
            limit: int = 3,
            project_id: uuid.UUID | None = None
    ) -> tuple[uuid.UUID, list[str], list[CompetitorData]]:

        # Определяем список URL для анализа
        urls_to_analyze = []
        if url:
            urls_to_analyze = [url.strip()]
        elif keyword:
            urls_to_analyze = await self._yandex.search(keyword, limit=limit)
        else:
            raise ValueError("Укажите ключевое слово (keyword) или ссылку (url)")

        async with self._uow as uow:
            # 1. Если передали project_id — загружаем существующий проект, иначе создаем новый
            if project_id:
                project = await uow.projects.get_with_relations(project_id)
                if not project:
                    raise ValueError("Проект не найден")
            else:
                initial_history = [
                    {
                        "role": "system",
                        "content": f"""Ты — главный коммерческий SEO-копирайтер и эксперт по анализу конкурентов.
Твоя задача — накапливать выжимки сайтов конкурентов и сайта пользователя, а затем создавать материалы по методичке:

{SEO_GUIDELINE_TEXT}
"""
                    }
                ]
                project = Project(keyword=keyword or url or "Анализ", chat_history=initial_history)
                await uow.projects.add(project)
                await uow.commit()

            summaries = []

            # 2. Анализируем новые сайты
            for site_url in urls_to_analyze:
                parsed_site = await self._parser.parse_site_to_graph(site_url)
                if not parsed_site:
                    continue

                summary = await self._kie.summarize_site(parsed_site)

                site_title = parsed_site.get("title") or site_url
                site_desc = parsed_site.get("description") or ""

                competitor = CompetitorData(
                    project_id=project.id,
                    url=site_url,
                    title=site_title,
                    graph_data={
                        "title": site_title,
                        "description": site_desc,
                        "body_text": parsed_site.get("body_text")
                    },
                    summary=summary
                )
                await uow.competitors.add(competitor)

                summaries.append(
                    f"Сайт: {site_url}\nTitle: {site_title}\nDescription: {site_desc}\n\nАнализ LSA и коммерческих факторов:\n{summary}"
                )

            if summaries:
                label = f"по ключу '{keyword}'" if keyword else f"по прямому URL {url}"
                context_prompt = f"Дополнительный глубокий анализ конкурентов {label}:\n\n" + "\n\n---\n\n".join(
                    summaries)

                history = list(project.chat_history)
                history.append({"role": "user", "content": context_prompt})
                history.append({"role": "assistant",
                                "content": f"Новые данные {label} успешно изучены и добавлены в общий контекст сравнения."})

                project.chat_history = history
                flag_modified(project, "chat_history")

            all_project_competitors = await uow.competitors.get_by_project_id(project.id)
            all_urls = [c.url for c in all_project_competitors]

        return project.id, all_urls, all_project_competitors