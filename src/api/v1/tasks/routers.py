import uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, status

from src.api.v1.tasks import schemas
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models import User
from src.infrastructure.database.models.tasks import GenerationTask, TaskStatus
from src.infrastructure.tasks.tasks import generate_full_article_pipeline_task

router = APIRouter(prefix="/v1/tasks", tags=["Background Tasks"], route_class=DishkaRoute)


@router.post("", response_model=schemas.TaskResponseDTO, status_code=status.HTTP_201_CREATED)
async def create_generation_task(
    payload: schemas.CreateTaskRequest,
    uow: FromDishka[UnitOfWorkProtocol],
    user: FromDishka[User],
):
    """Создает задачу в БД и отправляет ее в очередь RabbitMQ."""
    task = GenerationTask(
        user_id=user.id,
        project_id=payload.project_id,
        keyword=payload.keyword,
        target_site=payload.target_site,
        topic=payload.topic or payload.keyword,
        instructions=payload.instructions,
        sites_limit=payload.sites_limit,
        status=TaskStatus.PENDING,
        progress_message="Задача поставлена в очередь",
    )
    async with uow:
        await uow.tasks.add(task)
        await uow.commit()

    # Отправляем в RabbitMQ через Taskiq
    await generate_full_article_pipeline_task.kiq(
        task_id_str=str(task.id),
        user_id_str=str(user.id),
        keyword=payload.keyword,
        target_site=payload.target_site,
        topic=payload.topic,
        instructions=payload.instructions,
        sites_limit=payload.sites_limit,
        project_id_str=str(payload.project_id) if payload.project_id else None,
    )

    return schemas.TaskResponseDTO.model_validate(task)


@router.get("", response_model=list[schemas.TaskResponseDTO])
async def list_user_tasks(
    uow: FromDishka[UnitOfWorkProtocol],
    user: FromDishka[User],
):
    """Возвращает список всех фоновых задач пользователя."""
    async with uow:
        tasks = await uow.tasks.get_all_by_user(user.id)
        return [schemas.TaskResponseDTO.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=schemas.TaskResponseDTO)
async def get_task_status(
    task_id: uuid.UUID,
    uow: FromDishka[UnitOfWorkProtocol],
    user: FromDishka[User],
):
    """Получает текущий статус задачи (для опроса фронтендом)."""
    async with uow:
        task = await uow.tasks.get_by_id(task_id)
        if not task or task.user_id != user.id:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        return schemas.TaskResponseDTO.model_validate(task)