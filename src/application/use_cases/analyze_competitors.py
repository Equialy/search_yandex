
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import SEO_GUIDELINE_TEXT
from src.application.uow import UnitOfWorkProtocol
from src.config.settings import BASE_DIR
from src.infrastructure.database.models.competitors import CompetitorData, Project
from src.infrastructure.gateways.openai_gateway import OpenAiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway

EXPORTS_DIR = BASE_DIR / "exports" / "analysis"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_analysis_to_txt(project_id: uuid.UUID, keyword: str, competitors: list[CompetitorData]) -> Path:
    """Сохраняет результаты анализа в .txt файл на диске в формате JSON с датой и временем."""
    export_payload = {
        "projectId": str(project_id),
        "keyword": keyword,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "competitorsCount": len(competitors),
        "competitors": [
            {
                "id": str(c.id),
                "url": c.url,
                "title": c.title,
                "seoMeta": c.graph_data,
                "summary": c.summary,
                "createdAt": c.created_at.isoformat() if c.created_at else None,
            }
            for c in competitors
        ]
    }

    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_path = EXPORTS_DIR / f"analysis_{now_str}_{project_id}.txt"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(export_payload, f, ensure_ascii=False, indent=2)

    return file_path


class AnalyzeCompetitorsUseCase:
    """Сценарий поиска/парсинга конкурентов, LSA-анализа и пополнения базы знаний проекта."""

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

        if url:
            search_items = [{"url": url.strip(), "title": "", "description": ""}]
        elif keyword:
            search_items = await self._yandex.search(keyword, limit=limit)
        else:
            raise ValueError("Укажите ключевое слово (keyword) или ссылку (url)")

        async with self._uow as uow:
            # 2. Загружаем или создаем проект
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
            created_competitors: list[CompetitorData] = []

            print(f"\n[AnalyzeCompetitors]: Начинаем обработку {len(search_items)} сайтов...")

            # 3. Чистый лаконичный цикл
            for idx, item in enumerate(search_items, 1):
                site_url = item["url"]
                yandex_title = item.get("title", "")
                yandex_desc = item.get("description", "")

                if not site_url:
                    continue

                print(f"  [{idx}/{len(search_items)}]  Парсинг {site_url}...")

                parsed_site = await self._parser.parse_site_to_graph(
                    url=site_url,
                    fallback_title=yandex_title,
                    fallback_desc=yandex_desc
                )

                # Пропускаем маркетплейсы/заблокированные сайты
                if not parsed_site or parsed_site.get("is_blocked") or len(parsed_site.get("body_text", "")) < 150:
                    print(f"  ❌ [{idx}/{len(search_items)}] Пропущен маркетплейс / заблокированный сайт: {site_url}")
                    continue

                print(f"  [{idx}/{len(search_items)}] Глубокая LSA-выжимка ИИ...")
                summary = await self._kie.summarize_site(parsed_site)

                site_title = parsed_site.get("title") or yandex_title or site_url
                site_desc = parsed_site.get("description") or yandex_desc or ""

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
                    summary=summary
                )
                await uow.competitors.add(competitor)
                created_competitors.append(competitor)

                print(f"  [{idx}/{len(search_items)}] Успешно сохранен в БД: {site_url}\n")

                summaries.append(
                    f"Сайт: {site_url}\nTitle: {site_title}\nDescription: {site_desc}\n\nАнализ LSA и коммерческих факторов:\n{summary}"
                )

            if summaries:
                label = f"по ключу '{keyword}'" if keyword else f"по прямому URL {url}"
                context_prompt = f"Дополнительный глубокий анализ конкурентов {label}:\n\n" + "\n\n---\n\n".join(summaries)

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

            saved_file_path = save_analysis_to_txt(
                project_id=project.id,
                keyword=project.keyword,
                competitors=all_project_competitors
            )
            print(f"[Analysis Saved to File]: {saved_file_path}\n")

        return project.id, all_urls, all_project_competitors