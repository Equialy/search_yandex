import base64
import uuid

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from src.api.v1.competitors import schemas
from src.application.services.competitors.project_history import (
    build_article_preview,
    format_chat_history_for_ui,
    get_latest_article_html,
)
from src.application.use_cases.analyze_competitors import AnalyzeCompetitorsUseCase
from src.application.use_cases.chat_context import ContinueContextChatUseCase
from src.application.use_cases.generate_article import GenerateArticleUseCase, build_target_site_parse
from src.application.use_cases.get_project import GetProjectUseCase
from src.application.use_cases.list_projects import ListProjectsUseCase
from src.infrastructure.gateways.site_parser import SiteParserGateway

router = APIRouter(prefix="/v1/competitors", tags=["Competitor Analysis"], route_class=DishkaRoute)

MAX_CHAT_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_CHAT_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.post(
    "/analyze",
    response_model=schemas.ProjectAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="1. Поиск/анализ конкурентов и пополнение контекста проекта"
)
async def analyze_competitors(
        payload: schemas.AnalyzeCompetitorsRequest,
        use_case: FromDishka[AnalyzeCompetitorsUseCase]
):
    try:
        project_id, urls, competitors = await use_case.execute(
            keyword=payload.keyword,
            url=payload.url,
            limit=payload.limit,
            project_id=payload.project_id
        )

        competitor_dtos = [
            schemas.CompetitorDetailDTO.model_validate(c) for c in competitors
        ]

        return schemas.ProjectAnalysisResponse(
            project_id=project_id,
            keyword=payload.keyword or payload.url or "Мульти-анализ",
            found_urls=urls,
            competitors=competitor_dtos,
            status="Данные проанализированы и добавлены в общий контекст."
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
        result = await use_case.execute(
            project_id=project_id,
            topic=payload.topic,
            instructions=payload.instructions,
            target_site=payload.target_site
        )
        parse_dto = None
        if result.target_site_parse:
            parse_dto = schemas.TargetSiteParseDTO.model_validate(result.target_site_parse)

        article = result.article
        return schemas.ArticleResponse(
            id=article.id,
            project_id=article.project_id,
            title=article.title,
            content=article.content,
            reasoning=article.reasoning,
            created_at=article.created_at,
            target_site=result.target_site,
            target_site_parse=parse_dto,
        )
    except ValueError as e:
        if "Проект не найден" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/parse-site",
    response_model=schemas.TargetSiteParseDTO,
    summary="Парсинг целевого сайта для предпросмотра raw_text",
)
async def parse_site(
    payload: schemas.ParseSiteRequest,
    parser: FromDishka[SiteParserGateway],
):
    parsed = await parser.parse_site_to_graph(payload.url)
    return schemas.TargetSiteParseDTO.model_validate(build_target_site_parse(payload.url, parsed))


@router.post(
    "/projects/{project_id}/chat",
    summary="3. Чат и доработка статьи в контексте проекта (multipart: prompt + опционально image)",
)
async def chat_with_context(
    project_id: uuid.UUID,
    use_case: FromDishka[ContinueContextChatUseCase],
    prompt: str = Form(..., description="Текст запроса к статье"),
    image: UploadFile | None = File(None, description="Скриншот сайта для стилизации статьи"),
):
    try:
        image_base64: str | None = None
        image_mime_type = "image/png"

        if image and image.filename:
            raw = await image.read()
            if len(raw) > MAX_CHAT_IMAGE_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail="Изображение слишком большое (максимум 5 МБ)",
                )
            mime = image.content_type or "image/png"
            if mime not in ALLOWED_CHAT_IMAGE_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Неподдерживаемый формат изображения: {mime}",
                )
            image_base64 = base64.b64encode(raw).decode("ascii")
            image_mime_type = mime

        response_text = await use_case.execute(
            project_id=project_id,
            user_prompt=prompt,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
        )
        return {"response": response_text}
    except ValueError as e:
        if "Проект не найден" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/projects",
    response_model=list[schemas.ProjectListItemDTO],
    summary="Получить список всех проектов с датами создания и обновления"
)
async def list_projects(
    use_case: FromDishka[ListProjectsUseCase]
):
    projects = await use_case.execute()
    return [schemas.ProjectListItemDTO.model_validate(p) for p in projects]


@router.get(
    "/projects/{project_id}",
    response_model=schemas.ProjectDetailDTO,
    summary="Детали проекта: конкуренты, статьи, история чата и генераций",
)
async def get_project(
    project_id: uuid.UUID,
    use_case: FromDishka[GetProjectUseCase],
):
    try:
        project = await use_case.execute(project_id)
        articles = sorted(
            project.articles or [],
            key=lambda article: article.created_at,
            reverse=True,
        )
        article_responses = []
        generation_history = []

        for article in articles:
            preview = build_article_preview(article.content)
            article_responses.append(schemas.ArticleResponse(
                id=article.id,
                project_id=article.project_id,
                title=article.title,
                content=article.content,
                reasoning=article.reasoning,
                created_at=article.created_at,
                content_preview=preview,
            ))
            generation_history.append(schemas.ArticleHistoryItemDTO(
                id=article.id,
                title=article.title,
                content_preview=preview,
                reasoning=article.reasoning,
                created_at=article.created_at,
                content=article.content,
            ))

        chat_history = [
            schemas.ChatHistoryMessageDTO.model_validate(item)
            for item in format_chat_history_for_ui(project.chat_history)
        ]

        fallback_article = articles[0] if articles else None
        latest_article_content = get_latest_article_html(
            project.chat_history,
            fallback_article.content if fallback_article else None,
        )
        latest_article_title = fallback_article.title if fallback_article else project.keyword

        return schemas.ProjectDetailDTO(
            id=project.id,
            keyword=project.keyword,
            competitors=[
                schemas.CompetitorDetailDTO.model_validate(c)
                for c in (project.competitors or [])
            ],
            articles=article_responses,
            chat_history=chat_history,
            generation_history=generation_history,
            latest_article_content=latest_article_content,
            latest_article_title=latest_article_title,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
    except ValueError as e:
        if "Проект не найден" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))



@router.post(
    "/debug-parser",
    summary="Отладка парсера: Посмотреть, что собирается с сайта"
)
async def debug_parser(
    url: str,
    parser: FromDishka[SiteParserGateway]
):
    return await parser.parse_site_to_graph(url)