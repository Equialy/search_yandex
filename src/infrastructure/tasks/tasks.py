import logging
from uuid import UUID
from dishka.integrations.taskiq import FromDishka, inject

from src.infrastructure.tasks.broker import broker
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.tasks import TaskStatus
from src.application.use_cases.analyze_competitors import AnalyzeCompetitorsUseCase
from src.application.use_cases.generate_article import GenerateArticleUseCase

logger = logging.getLogger(__name__)


@broker.task(task_name="generate_full_article_pipeline")
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
    """
    Фоновый пайплайн полного цикла:
    1. Поиск и LSA-анализ конкурентов в Яндекс.
    2. Парсинг сайта компании и расчет оптимального объема.
    3. Генерация коммерческой SEO-статьи.
    4. Параллельная генерация и интеграция иллюстраций.
    """
    logger.info(
        "[Pipeline Task] ▶ START | task_id=%s | user_id=%s | keyword='%s' | target_site=%s",
        task_id_str, user_id_str, keyword, target_site
    )

    task_id = UUID(task_id_str)
    user_id = UUID(user_id_str)
    existing_project_id = UUID(project_id_str) if project_id_str else None
    final_topic = topic.strip() if topic and topic.strip() else keyword

    async with uow:
        task = await uow.tasks.get_by_id(task_id)
        if not task:
            logger.error("[Pipeline Task] Task not found in DB | task_id=%s", task_id)
            return

        try:
            task.status = TaskStatus.PROCESSING
            task.progress_message = "Поиск и глубокий LSA-анализ конкурентов в Яндекс..."
            await uow.commit()

            logger.info("[Pipeline Task] [1/3] Запуск анализа конкурентов в выдаче Яндекс...")
            project_id, found_urls, competitors = await analyze_uc.execute(
                user_id=user_id,
                keyword=keyword,
                limit=sites_limit,
                project_id=existing_project_id,
            )
            logger.info(
                "[Pipeline Task] [1/3] Анализ завершен | project_id=%s | competitors_found=%d",
                project_id, len(competitors)
            )

            task.project_id = project_id
            task.progress_message = "Генерация текста статьи и параллельное создание иллюстраций..."
            await uow.commit()

            logger.info("[Pipeline Task] [2/3] Запуск генерации статьи (тема: '%s')...", final_topic)
            gen_result = await generate_uc.execute(
                project_id=project_id,
                topic=final_topic,
                instructions=instructions or "",
                target_site=target_site or "",
                user_id=user_id,
            )
            logger.info(
                "[Pipeline Task]  [2/3] Статья успешно создана | article_id=%s | images_count=%d",
                gen_result.article.id,
                len(gen_result.images_urls or [])
            )

            task.article_id = gen_result.article.id
            task.status = TaskStatus.COMPLETED
            task.progress_message = "Статья и изображения успешно созданы!"
            await uow.commit()

            logger.info("[Pipeline Task]  FINISHED SUCCESS | task_id=%s | project_id=%s", task_id, project_id)

        except Exception as e:
            logger.exception("[Pipeline Task]  FAILED | task_id=%s | error=%s", task_id, e)
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.progress_message = f"Ошибка: {str(e)}"
            await uow.commit()