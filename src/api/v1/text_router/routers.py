
from fastapi import APIRouter, HTTPException, status
from dishka.integrations.fastapi import FromDishka, DishkaRoute

from src.api.v1.text_router import schema
from src.api.v1.text_router.schema import DetectResponse, TextRequest, HumanizeResponse
from src.api.v1.text_router.service import TextAiService
from src.infrastructure.database.models import User

router = APIRouter(
    prefix="/v1/text",
    tags=["Text Humanizer & AI Detector"],
    route_class=DishkaRoute,
)


@router.post("/detect", response_model=DetectResponse)
async def detect_ai(
    req: TextRequest,
    service: FromDishka[TextAiService],
    user: FromDishka[User],
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
    user: FromDishka[User],
):
    if not req.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Текст не может быть пустым"
        )
    return await service.humanize_text(req.text)

@router.post(
    "/nausea",
    response_model=schema.CalculateNauseaResponse,
    status_code=status.HTTP_200_OK,
    summary="Расчет классической и академической тошнотности текста"
)
async def calculate_nausea(
    payload: schema.CalculateNauseaRequest,
    service: FromDishka[TextAiService],
    user: FromDishka[User]
):
    return service.calculate_nausea(payload)