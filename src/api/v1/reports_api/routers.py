from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, HTTPException, status

from src.api.v1.reports_api import schemas
from src.infrastructure.database.models import User
from src.infrastructure.gateways.reports_article import ReportsArticleGateway
from src.infrastructure.tasks.tasks import generate_reports_article_pipeline_task

router = APIRouter(prefix="/v1/reports", tags=["Reports"], route_class=DishkaRoute)


@router.get(
    "/tasks",
    status_code=status.HTTP_200_OK,
    response_model=schemas.ReportsArticleResponse,
    summary="Получить текущую задачу из внешнего сервиса Reports"
)
async def get_tasks(
    gateway: FromDishka[ReportsArticleGateway],
    user: FromDishka[User],
) -> schemas.ReportsArticleResponse:
    try:
        return await gateway.get_task()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка внешнего сервиса: {str(e)}")


@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить фоновую генерацию статьи для задачи из Reports"
)
async def start_report_generation(
    payload: schemas.StartReportTaskRequest,
    user: FromDishka[User],
):
    """Ставит задачу в очередь Taskiq для генерации и отправки во внешний сервис."""
    await generate_reports_article_pipeline_task.kiq(
        id_task=payload.id_task,
        user_id_str=str(user.id),
        site_key=payload.site_key,
        domain=payload.domain,
        instructions=payload.text_comment,
        sites_limit=payload.sites_limit,
        topic=payload.topic,
    )
    return {
        "success": True,
        "message": f"Задача #{payload.id_task} ({payload.site_key}) успешно отправлена в очередь генерации."
    }