from __future__ import annotations

import json
import uuid

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.api.v1.agent import schemas
from src.application.uow import UnitOfWorkProtocol
from src.application.use_cases.agent_chat import AgentChatUseCase
from src.infrastructure.database.models import User

router = APIRouter(prefix="/v1/agent", tags=["SEO Agent"], route_class=DishkaRoute)


@router.post(
    "/chat",
    summary="Чат с SEO-агентом (LLM + инструменты анализа/статьи)",
)
async def agent_chat(
    payload: schemas.AgentChatRequest,
    use_case: FromDishka[AgentChatUseCase],
        user: FromDishka[User],
):
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    async def event_stream():
        async for event in use_case.stream(messages):
            yield (
                f"event: {event['type']}\n"
                f"data: {json.dumps(event.get('data') or {}, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )



@router.get("/chats", response_model=list[schemas.AgentChatListItemDTO], summary="Получить список всех сессий чата Агента из БД")
async def list_agent_chats(uow: FromDishka[UnitOfWorkProtocol],   user: FromDishka[User],):
    async with uow:
        chats = await uow.agent_chats.get_all_ordered_by_updated()
        return [schemas.AgentChatListItemDTO.model_validate(c) for c in chats]

@router.get("/chats/{chat_id}", response_model=schemas.AgentChatDetailDTO, summary="Загрузить историю сообщений сессии из БД")
async def get_agent_chat_detail(chat_id: uuid.UUID, uow: FromDishka[UnitOfWorkProtocol],   user: FromDishka[User],):
    async with uow:
        chat = await uow.agent_chats.get_by_id(chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Сессия чата не найдена")
        return schemas.AgentChatDetailDTO.model_validate(chat)
