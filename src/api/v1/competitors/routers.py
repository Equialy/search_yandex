import uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, status

from src.api.v1.competitors import schemas
from src.application.use_cases.analyze_competitors import AnalyzeCompetitorsUseCase
from src.application.use_cases.chat_context import ContinueContextChatUseCase
from src.application.use_cases.generate_article import GenerateArticleUseCase

router = APIRouter(prefix="/v1/competitors", tags=["Competitor Analysis"], route_class=DishkaRoute)


@router.post(
    "/analyze",
    response_model=schemas.ProjectAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="1. Запуск анализа конкурентов из Яндекса"
)
async def analyze_competitors(
        payload: schemas.AnalyzeCompetitorsRequest,
        use_case: FromDishka[AnalyzeCompetitorsUseCase]
):
    project_id, urls, competitors = await use_case.execute(keyword=payload.keyword, limit=payload.limit)

    competitor_dtos = [
        schemas.CompetitorDetailDTO.model_validate(c) for c in competitors
    ]

    return schemas.ProjectAnalysisResponse(
        project_id=project_id,
        keyword=payload.keyword,
        found_urls=urls,
        competitors=competitor_dtos,
        status="Графы построены, контекст диалога сохранен."
    )

@router.post(
    "/projects/{project_id}/generate-article",
    response_model=schemas.ArticleResponse,
    summary="2. Генерация статьи в сохраняемом контексте проекта"
)
async def generate_article(
    project_id: uuid.UUID,
    payload: schemas.GenerateArticleRequest,
    use_case: FromDishka[GenerateArticleUseCase]
):
    try:
        article = await use_case.execute(
            project_id=project_id,
            topic=payload.topic,
            instructions=payload.instructions
        )
        return article
    except ValueError as e:
        if "Проект не найден" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post(
    "/projects/{project_id}/chat",
    summary="3. Чат и доработка статьи в контексте проекта"
)
async def chat_with_context(
    project_id: uuid.UUID,
    payload: schemas.ChatContextRequest,
    use_case: FromDishka[ContinueContextChatUseCase]
):
    try:
        response_text = await use_case.execute(
            project_id=project_id,
            user_prompt=payload.prompt
        )
        return {"response": response_text}
    except ValueError as e:
        if "Проект не найден" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))