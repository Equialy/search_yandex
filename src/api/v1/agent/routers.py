from __future__ import annotations

import json

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.api.v1.agent import schemas
from src.application.use_cases.agent_chat import AgentChatUseCase

router = APIRouter(prefix="/v1/agent", tags=["SEO Agent"], route_class=DishkaRoute)


@router.post(
    "/chat",
    summary="Чат с SEO-агентом (LLM + инструменты анализа/статьи)",
)
async def agent_chat(
    payload: schemas.AgentChatRequest,
    use_case: FromDishka[AgentChatUseCase],
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
