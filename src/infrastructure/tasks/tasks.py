import logging
from uuid import UUID
from dishka.integrations.taskiq import FromDishka, inject
from taskiq.brokers.shared_broker import async_shared_broker

from src.api.v1.reports_api.schemas import SendArticleReportPayload
from src.config.settings import settings
from src.infrastructure.gateways.reports_article import ReportsArticleGateway
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.tasks import TaskStatus
from src.application.use_cases.analyze_competitors import AnalyzeCompetitorsUseCase
from src.application.use_cases.generate_article import GenerateArticleUseCase
from src.utils.extract_data import extract_html_metadata, remove_meta_block_from_html

logger = logging.getLogger(__name__)





@async_shared_broker.task(task_name="generate_full_article_pipeline")
@inject
async def generate_full_article_pipeline_task(
    task_id_str: str,
    user_id_str: str,
    keyword: str,
    target_site: str | None = None,
    topic: str | None = None,
    instructions: str = "",
    sites_limit: int = 3,
    project_id_str: str | None = None,
    uow: FromDishka[UnitOfWorkProtocol] = None,
    analyze_uc: FromDishka[AnalyzeCompetitorsUseCase] = None,
    generate_uc: FromDishka[GenerateArticleUseCase] = None,
):
    logger.info(
        "[Pipeline Task] ▶ START | task_id=%s | user_id=%s | keyword='%s'",
        task_id_str, user_id_str, keyword
    )

    task_id = UUID(task_id_str)
    user_id = UUID(user_id_str)
    existing_project_id = UUID(project_id_str) if project_id_str else None
    final_topic = topic.strip() if topic and topic.strip() else keyword

    try:
        async with uow:
            task = await uow.tasks.get_by_id(task_id)
            if not task:
                logger.error("[Pipeline Task] Task not found in DB | task_id=%s", task_id)
                return
            task.status = TaskStatus.PROCESSING
            task.progress_message = "Поиск и глубокий LSA-анализ конкурентов в Яндекс..."
            await uow.commit()

        logger.info("[Pipeline Task] [1/3] Запуск анализа конкурентов в Яндекс...")
        project_id, found_urls, competitors = await analyze_uc.execute(
            user_id=user_id,
            keyword=keyword,
            limit=sites_limit,
            project_id=existing_project_id,
        )
        logger.info(
            "[Pipeline Task] [1/3] Анализ завершен | project_id=%s | competitors=%d",
            project_id, len(competitors)
        )

        async with uow:
            task = await uow.tasks.get_by_id(task_id)
            task.project_id = project_id
            task.progress_message = "Генерация текста статьи и параллельное создание иллюстраций..."
            await uow.commit()

        logger.info("[Pipeline Task]  [2/3] Запуск генерации статьи (тема: '%s')...", final_topic)
        gen_result = await generate_uc.execute(
            project_id=project_id,
            topic=final_topic,
            instructions=instructions or "",
            target_site=target_site or "",
            user_id=user_id,
        )
        logger.info(
            "[Pipeline Task] [2/3] Статья создана | article_id=%s",
            gen_result.article.id
        )

        async with uow:
            task = await uow.tasks.get_by_id(task_id)
            task.article_id = gen_result.article.id
            task.project_id = project_id
            task.status = TaskStatus.COMPLETED
            task.progress_message = "Статья и изображения успешно созданы!"
            await uow.commit()

        logger.info("[Pipeline Task] FINISHED SUCCESS | task_id=%s | project_id=%s", task_id, project_id)

    except Exception as e:
        logger.exception("[Pipeline Task] FAILED | task_id=%s | error=%s", task_id, e)
        async with uow:
            task = await uow.tasks.get_by_id(task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                task.progress_message = f"Ошибка: {str(e)}"
                await uow.commit()




@async_shared_broker.task(task_name="generate_reports_article_pipeline")
@inject
async def generate_reports_article_pipeline_task(
    id_task: int,
    user_id_str: str,
    site_key: str,
    domain: str,
    instructions: str = "",
    sites_limit: int = 4,
    topic: str | None = None,
    uow: FromDishka[UnitOfWorkProtocol] = None,
    analyze_uc: FromDishka[AnalyzeCompetitorsUseCase] = None,
    generate_uc: FromDishka[GenerateArticleUseCase] = None,
    reports_gateway: FromDishka[ReportsArticleGateway] = None,
):
    from src.application.services.reports_api.poller import _ACTIVE_TASKS

    logger.info(
        "[Reports Task] ▶ START | id_task=%d | site_key='%s' | domain='%s'",
        id_task, site_key, domain
    )
    user_id = UUID(user_id_str)
    final_topic = topic.strip() if topic and topic.strip() else site_key
    target_site = domain.strip()
    if target_site and not target_site.startswith(("http://", "https://")):
        target_site = f"https://{target_site}"

    try:
        logger.info("[Reports Task] [1/3] Поиск 4 конкурентов в Яндекс по ключу '%s'...", site_key)
        project_id, _, competitors = await analyze_uc.execute(
            user_id=user_id,
            keyword=site_key,
            limit=sites_limit,
        )

        concurent_lines = []
        for c in competitors:
            metrics = c.seo_metrics or {}
            char_count = metrics.get("charCount") or len(c.raw_text or "")
            nausea = int(metrics.get("academicNausea") or 0)
            human = int(metrics.get("humanPercentage") or 80)
            clean_url = c.url.replace("https://", "").replace("http://", "")
            concurent_lines.append(
                f"https://{clean_url} | количество символов: {char_count} | Тошнота текста: {nausea}% | Очеловечивание: {human}%"
            )
        concurent_metrix = "\n".join(concurent_lines)

        # 3. Генерация статьи
        logger.info("[Reports Task]  [2/3] Генерация статьи для '%s'...", target_site)
        gen_result = await generate_uc.execute(
            project_id=project_id,
            topic=final_topic,
            instructions=instructions or "",
            target_site=target_site,
            user_id=user_id,
        )

        article = gen_result.article
        title_val = gen_result.meta_title or final_topic
        desc_val = gen_result.meta_description
        h1_val = gen_result.meta_h1 or final_topic
        clean_html_content = remove_meta_block_from_html(article.content)

        metrics = article.seo_metrics or {}
        char_count = int(metrics.get("charCount") or len(clean_html_content))
        toshnota = int(metrics.get("academicNausea") or 8)
        human = int(metrics.get("humanPercentage") or 85)
        base_public_url = settings.base_url.rstrip("/")

        public_html_content = (
            article.content
            .replace('src="/static/', f'src="{base_public_url}/static/')
            .replace("src='/static/", f"src='{base_public_url}/static/")
        )

        logger.info("[Reports Task]  [3/3] Отправка в Reports API (id_task=%d)...", id_task)
        report_payload = SendArticleReportPayload(
            id_task=id_task,
            content=public_html_content,
            text_title=title_val or final_topic,
            text_description=desc_val,
            text_H1=h1_val or final_topic,
            text_count_char=char_count,
            text_toshnota=toshnota,
            text_human=human,
            concurent_metrix=concurent_metrix,
        )

        response_report = await reports_gateway.send_article(report_payload)
        logger.info("[Reports Task] УСПЕШНО ОТПРАВЛЕНО | id_task=%d | message=%s", id_task, response_report.message)

    except Exception as e:
        logger.exception(" [Reports Task] ОШИБКА | id_task=%d | error=%s", id_task, e)
    finally:
        _ACTIVE_TASKS.discard(id_task)