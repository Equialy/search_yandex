
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

    async def execute(self, keyword: str, limit: int) -> tuple[uuid.UUID, list[str], list[CompetitorData]]:
        urls = await self._yandex.search(keyword, limit=limit)

        async with self._uow as uow:
            initial_history = [
                {
                    "role": "system",
                    "content": f"""Ты — главный коммерческий SEO-копирайтер и эксперт по услугам.
Твоя задача — анализировать конкурентов по ключевому слову '{keyword}' и создавать готовые материалы, СТРОГО СОБЛЮДАЯ МЕТОДИЧКУ:

{SEO_GUIDELINE_TEXT}
"""
                }
            ]
            project = Project(keyword=keyword, chat_history=initial_history)
            await uow.projects.add(project)
            await uow.commit()

            summaries = []
            created_competitors = []


            for url in urls:
                parsed_site = await self._parser.parse_site_to_graph(url)
                if not parsed_site:
                    continue

                summary = await self._kie.summarize_site(parsed_site)

                site_title = parsed_site.get("title") or url
                site_desc = parsed_site.get("description") or ""

                competitor = CompetitorData(
                    project_id=project.id,
                    url=url,
                    title=site_title,
                    graph_data={
                        "title": site_title,
                        "description": site_desc,
                        "body_text": parsed_site.get("body_text")
                    },
                    summary=summary
                )
                await uow.competitors.add(competitor)
                created_competitors.append(competitor)

                summaries.append(
                    f"Сайт: {url}\nTitle: {site_title}\nDescription: {site_desc}\n\nАнализ LSA и коммерческих факторов:\n{summary}"
                )

            if not summaries:
                summaries.append(
                    f"По ключу '{keyword}' были найдены сайты {urls}. Сделай упор на коммерческие факторы и LSA семантику страницы услуг.")

            context_prompt = "Вот глубокий LSA и коммерческий анализ конкурентов по методичке:\n\n" + "\n\n---\n\n".join(
                summaries)

            history = list(project.chat_history)
            history.append({"role": "user", "content": context_prompt})
            history.append({"role": "assistant",
                            "content": "Контекст конкурентов полностью усвоен. Я изучил Title, Description, LSA-семантику и коммерческие факторы. Готов писать статью по методичке."})

            project.chat_history = history
            flag_modified(project, "chat_history")

        return project.id, urls, created_competitors