import asyncio
import logging
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.config.settings import settings
from src.infrastructure.database.models.users import User, UserRole
from src.infrastructure.gateways.reports_article import ReportsArticleGateway
from src.infrastructure.tasks.tasks import generate_reports_article_pipeline_task

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 1800


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
    logger.info("[Reports Poller] Запущен фоновый опросник API (интервал: %d сек)...", poll_interval_seconds)
    redis_client = aioredis.from_url(settings.redis.backend_url, decode_responses=True)

    try:
        while True:
            try:
                response = await gateway.get_task()

                if response.success and response.task and response.task.id_task:
                    task = response.task
                    task_id = task.id_task
                    lock_key = f"reports:task_lock:{task_id}"

                    acquired = await redis_client.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS)
                    if not acquired:
                        logger.debug("[Reports Poller] Задача #%d уже в работе (Redis lock), пропускаем...", task_id)
                    else:
                        try:
                            admin_user_id = await _get_default_admin_id(session_maker)
                            await generate_reports_article_pipeline_task.kiq(
                                id_task=task_id,
                                user_id_str=admin_user_id,
                                site_key=task.site_key or "",
                                domain=task.domain or "",
                                instructions=task.text_comment or "",
                                sites_limit=4,
                                topic=task.site_key,
                            )
                            logger.info("[Reports Poller] Задача #%d отправлена в очередь!", task_id)
                        except Exception:
                            await redis_client.delete(lock_key)
                            raise
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[Reports Poller] Ошибка при опросе Reports API: %s", e)

            await asyncio.sleep(poll_interval_seconds)
    finally:
        await redis_client.aclose()