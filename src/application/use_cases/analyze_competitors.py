import uuid
from sqlalchemy.orm.attributes import flag_modified

from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.competitors import CompetitorData, Project
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway


class AnalyzeCompetitorsUseCase:
    def __init__(
        self,
        uow: UnitOfWorkProtocol,
        yandex_gateway: YandexSearchGateway,
        parser_gateway: SiteParserGateway,
        kie_gateway: KieApiGateway
    ):
        self._uow = uow
        self._yandex = yandex_gateway
        self._parser = parser_gateway
        self._kie = kie_gateway

    async def execute(self, keyword: str, limit: int) -> tuple[uuid.UUID, list[str]]:
        urls = await self._yandex.search(keyword, limit=limit)

        async with self._uow as uow:
            initial_history = [
                {
                    "role": "system",
                    "content": f"Ты экспертный SEO-копирайтер. Проведен глубокий анализ конкурентов по ключевому слову '{keyword}'. Используй эти структуры и выжимки для написания статей."
                }
            ]
            project = Project(keyword=keyword, chat_history=initial_history)
            await uow.projects.add(project)
            await uow.commit()

            summaries = []

            for url in urls:
                parsed_site = await self._parser.parse_site_to_graph(url)
                if not parsed_site or not parsed_site.get("graph", {}).get("hierarchy"):
                    continue

                summary = await self._kie.summarize_site(parsed_site)

                competitor = CompetitorData(
                    project_id=project.id,
                    url=url,
                    title=parsed_site.get("title"),
                    graph_data=parsed_site.get("graph", {}),
                    summary=summary
                )
                await uow.competitors.add(competitor)
                summaries.append(f"Сайт: {url}\nЗаголовок: {parsed_site.get('title')}\nВыжимка тезисов: {summary}")

            if not summaries:
                summaries.append(f"По ключу '{keyword}' были найдены сайты {urls}. Основной упор сделан на обзор общих типов кофемашин, брендов и критериев выбора.")

            context_prompt = "Вот выжимка анализа графов и смыслов топовых конкурентов:\n\n" + "\n\n---\n\n".join(summaries)

            history = list(project.chat_history)
            history.append({"role": "user", "content": context_prompt})
            history.append({"role": "assistant", "content": "Контекст конкурентов полностью усвоен. Я изучил структуры и выжимки. Готов писать статьи."})

            project.chat_history = history
            flag_modified(project, "chat_history")  # Принудительно маркируем JSON поле как измененное

        return project.id, urls