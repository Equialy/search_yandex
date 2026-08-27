import uuid
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import ANALYZE_CONCURENTS
from src.application.uow import UnitOfWorkProtocol
from src.config.settings import BASE_DIR
from src.infrastructure.database.models.competitors import CompetitorData, Project
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway
from src.api.v1.text_router.service import TextAiService
from src.api.v1.text_router.schema import CalculateNauseaRequest

EXPORTS_DIR = BASE_DIR / "exports" / "analysis"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


class AnalyzeCompetitorsUseCase:
    def __init__(
            self,
            uow: UnitOfWorkProtocol,
            yandex_gateway: YandexSearchGateway,
            parser_gateway: SiteParserGateway,
            ai_gateway: KieApiGateway,
            text_ai_service: TextAiService,
    ):
        self._uow = uow
        self._yandex = yandex_gateway
        self._parser = parser_gateway
        self._kie = ai_gateway
        self._text_ai = text_ai_service

    async def execute(
            self,
            user_id: uuid.UUID,
            keyword: str | None = None,
            url: str | None = None,
            limit: int = 3,
            project_id: uuid.UUID | None = None
    ) -> tuple[uuid.UUID, list[str], list[CompetitorData]]:

        if url:
            search_items = [{"url": url.strip(), "title": "", "description": ""}]
        elif keyword:
            search_items = await self._yandex.search(keyword, limit=limit)
        else:
            raise ValueError("Укажите ключевое слово (keyword) или ссылку (url)")

        async with self._uow as uow:
            if project_id:
                project = await uow.projects.get_with_relations(project_id, user_id=user_id)
                if not project:
                    raise ValueError("Проект не найден")
            else:
                initial_history = [
                    {
                        "role": "system",
                        "content": f"""Ты — главный коммерческий SEO-копирайтер и эксперт по анализу конкурентов.
                        Твоя задача — накапливать выжимки сайтов конкурентов и сайта пользователя и проанализировать 
                        конкурентов для дальнейшей генерации статьи моего сайта:

                        {ANALYZE_CONCURENTS}
                        """
                    }
                ]

                project = Project(
                    user_id=user_id,
                    keyword=keyword or url or "Анализ",
                    chat_history=initial_history
                )
                await uow.projects.add(project)
                await uow.commit()

            summaries = []
            created_competitors: list[CompetitorData] = []

            print(f"\n[AnalyzeCompetitors]: Начинаем обработку {len(search_items)} сайтов...")

            for idx, item in enumerate(search_items, 1):
                site_url = item["url"]
                yandex_title = item.get("title", "")
                yandex_desc = item.get("description", "")

                if not site_url:
                    continue

                print(f"  [{idx}/{len(search_items)}] Парсинг {site_url}...")

                parsed_site = await self._parser.parse_site_to_graph(
                    url=site_url,
                    fallback_title=yandex_title,
                    fallback_desc=yandex_desc
                )

                if not parsed_site or parsed_site.get("is_blocked") or len(parsed_site.get("body_text", "")) < 150:
                    print(f"   [{idx}/{len(search_items)}] Пропущен маркетплейс / заблокированный сайт: {site_url}")
                    continue

                print(f"  [{idx}/{len(search_items)}] Глубокая LSA-выжимка ИИ...")
                summary = await self._kie.summarize_site(parsed_site)

                site_title = parsed_site.get("title") or yandex_title or site_url
                site_desc = parsed_site.get("description") or yandex_desc or ""
                clean_content = parsed_site.get("clean_text") or parsed_site.get("body_text", "")

                comp_seo_metrics = {}
                try:
                    nausea_res = self._text_ai.calculate_nausea(
                        CalculateNauseaRequest(text=clean_content)
                    )
                    detect_res = await self._text_ai.detect_ai(clean_content)

                    comp_seo_metrics = {
                        "classicNausea": nausea_res.classic_nausea,
                        "academicNausea": nausea_res.academic_nausea,
                        "totalWords": nausea_res.total_words,
                        "uniqueWords": nausea_res.unique_words,
                        "charCount": len(clean_content),
                        "charCountNoSpaces": len(clean_content.replace(" ", "")),
                        "topWords": [w.model_dump(by_alias=True) for w in nausea_res.top_words],
                        "aiPercentage": detect_res.ai_percentage,
                        "humanPercentage": detect_res.human_percentage,
                        "aiReason": detect_res.reason,
                    }
                except Exception as e:
                    print(f"⚠️ [Competitor SEO Metrics Error for {site_url}]: {e}")

                competitor = CompetitorData(
                    project_id=project.id,
                    url=site_url,
                    title=site_title,
                    graph_data={
                        "title": site_title,
                        "description": site_desc,
                        "body_text": parsed_site.get("body_text")
                    },
                    raw_text=parsed_site.get("body_text"),
                    summary=summary,
                    seo_metrics=comp_seo_metrics,
                )
                await uow.competitors.add(competitor)
                created_competitors.append(competitor)

                print(f"  [{idx}/{len(search_items)}] Успешно сохранен в БД: {site_url}\n")

                summaries.append(
                    f"Сайт: {site_url}\nTitle: {site_title}\nDescription: {site_desc}\n\nАнализ LSA и коммерческих факторов:\n{summary}"
                )

            if summaries:
                label = f"по ключу '{keyword}'" if keyword else f"по прямому URL {url}"
                context_prompt = f"Дополнительный глубокий анализ конкурентов {label}:\n\n" + "\n\n---\n\n".join(
                    summaries)

                history = list(project.chat_history)
                history.append({"role": "user", "content": context_prompt})
                history.append({
                    "role": "assistant",
                    "content": f"Новые данные {label} успешно изучены и добавлены в общий контекст сравнения."
                })

                project.chat_history = history
                flag_modified(project, "chat_history")

            all_project_competitors = await uow.competitors.get_by_project_id(project.id)
            all_urls = [c.url for c in all_project_competitors]

        return project.id, all_urls, all_project_competitors