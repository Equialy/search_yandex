import uuid
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.competitors import CompetitorData, Project
from src.infrastructure.gateways.llm_gateway import LLMGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway


class AnalyzeCompetitorsUseCase:
    def __init__(
            self,
            uow: UnitOfWorkProtocol,
            yandex_gateway: YandexSearchGateway,
            parser_gateway: SiteParserGateway,
            llm_gateway: LLMGateway
    ):
        self._uow = uow
        self._yandex = yandex_gateway
        self._parser = parser_gateway
        self._llm = llm_gateway

    async def execute(self, keyword: str, limit: int) -> tuple[uuid.UUID, list[str]]:
        # 1. Поиск в Яндексе
        urls = await self._yandex.search(keyword, limit=limit)

        async with self._uow as uow:
            # 2. Инициализация проекта с системным контекстом
            initial_history = [
                {
                    "role": "system",
                    "content": f"Ты SEO-аналитик. Проведен анализ конкурентов по ключу '{keyword}'. Используй эти данные для написания статей."
                }
            ]
            project = Project(keyword=keyword, chat_history=initial_history)
            await uow.projects.add(project)
            await uow.commit()  # Получаем project.id

            summaries = []

            # 3. Парсинг каждого сайта и выжимка
            for url in urls:
                parsed_site = await self._parser.parse_site_to_graph(url)
                if not parsed_site:
                    continue

                summary = await self._llm.summarize_site(parsed_site)

                competitor = CompetitorData(
                    project_id=project.id,
                    url=url,
                    title=parsed_site.get("title"),
                    graph_data=parsed_site.get("graph", {}),
                    summary=summary
                )
                await uow.competitors.add(competitor)
                summaries.append(f"Сайт: {url}\nЗаголовок: {parsed_site.get('title')}\nВыжимка: {summary}")

            # 4. Сохраняем выжимку в chat_history (КОНТЕКСТ ДЛЯ БУДУЩИХ СТАТЕЙ)
            context_prompt = "Вот анализ графов и смыслов конкурентов:\n\n" + "\n\n---\n\n".join(summaries)

            history = list(project.chat_history)
            history.append({"role": "user", "content": context_prompt})
            history.append(
                {"role": "assistant", "content": "Контекст конкурентов полностью усвоен. Готов к генерации статей."})

            project.chat_history = history
            # Commit происходит автоматически при выходе из async with self._uow

        return project.id, urls