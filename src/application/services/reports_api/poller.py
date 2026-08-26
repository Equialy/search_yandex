import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.infrastructure.database.models.users import User, UserRole
from src.infrastructure.gateways.reports_article import ReportsArticleGateway
from src.infrastructure.tasks.tasks import generate_reports_article_pipeline_task

logger = logging.getLogger(__name__)

_ACTIVE_TASKS: set[int] = set()


async def _get_default_admin_id(session_maker: async_sessionmaker[AsyncSession]) -> str:
    """Получает ID первого администратора в системе для привязки проекта."""
    async with session_maker() as session:
        stmt = select(User).where(User.role == UserRole.ADMIN).limit(1)
        res = await session.execute(stmt)
        admin = res.scalar_one_or_none()
        if admin:
            return str(admin.id)
        stmt_any = select(User).limit(1)
        res_any = await session.execute(stmt_any)
        any_user = res_any.scalar_one_or_none()
        return str(any_user.id) if any_user else "00000000-0000-0000-0000-000000000000"


async def start_reports_polling_loop(
    gateway: ReportsArticleGateway,
    session_maker: async_sessionmaker[AsyncSession],
    poll_interval_seconds: int = 60,
):
    """
    Бесконечный фоновый цикл:
    1. Опрашивает Reports API раз в 60 секунд.
    2. При наличии задачи отправляет ее на генерацию (4 сайта конкурентов).
    """
    logger.info(" [Reports Poller] Запущен фоновый опросник API (интервал: %d сек)...", poll_interval_seconds)

    while True:
        try:
            response = await gateway.get_task()

            if response.success and response.task and response.task.id_task:
                task = response.task
                task_id = task.id_task

                if task_id in _ACTIVE_TASKS:
                    logger.debug("[Reports Poller] Задача #%d уже находится в процессе генерации, пропускаем...", task_id)
                else:
                    logger.info(
                        " [Reports Poller] Найдена новая задача #%d | Ключ: '%s' | Домен: '%s'",
                        task_id, task.site_key, task.domain
                    )

                    admin_user_id = await _get_default_admin_id(session_maker)
                    _ACTIVE_TASKS.add(task_id)

                    await generate_reports_article_pipeline_task.kiq(
                        id_task=task_id,
                        user_id_str=admin_user_id,
                        site_key=task.site_key or "",
                        domain=task.domain or "",
                        instructions=task.text_comment or "",
                        sites_limit=4,
                        topic=task.site_key,
                    )
                    logger.info("⚡ [Reports Poller] Задача #%d успешно отправлена в очередь генерации!", task_id)

            else:
                logger.debug("[Reports Poller] Очередь задач в Reports пуста.")

        except Exception as e:
            logger.warning("[Reports Poller] Ошибка при опросе Reports API: %s", e)

        await asyncio.sleep(poll_interval_seconds)