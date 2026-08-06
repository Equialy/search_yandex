from fastapi import APIRouter, HTTPException, status, Depends
from dishka.integrations.fastapi import FromDishka, DishkaRoute

from src.api.v1.text_router.schema import DetectResponse, HumanizeResponse, TextRequest
from src.api.v1.text_router.service import TextAiService
from src.config.settings import settings

router = APIRouter(
    prefix=settings.api.v1.api_v1 + "/text",
    tags=["Text"],
    route_class=DishkaRoute,
)

@router.post("/detect", response_model=DetectResponse)
async def detect_ai(
    req: TextRequest,
    service: FromDishka[TextAiService],
):
    if not req.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Текст не может быть пустым"
        )
    return await service.detect_ai(req.text)


@router.post("/humanize", response_model=HumanizeResponse)
async def humanize(
    req: TextRequest,
    service: FromDishka[TextAiService],
):
    if not req.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Текст не может быть пустым"
        )
    return await service.humanize_text(req.text)