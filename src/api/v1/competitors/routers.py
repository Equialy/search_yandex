import uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, status

from src.api.v1.competitors import schemas
from src.application.use_cases.analyze_competitors import AnalyzeCompetitorsUseCase
from src.application.use_cases.chat_context import ContinueContextChatUseCase
from src.application.use_cases.generate_article import GenerateArticleUseCase, build_target_site_parse
from src.application.use_cases.get_project import GetProjectUseCase
from src.application.use_cases.list_projects import ListProjectsUseCase
from src.infrastructure.gateways.site_parser import SiteParserGateway

router = APIRouter(prefix="/v1/competitors", tags=["Competitor Analysis"], route_class=DishkaRoute)


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
    summary="Детали проекта: конкуренты и сгенерированные статьи",
)
async def get_project(
    project_id: uuid.UUID,
    use_case: FromDishka[GetProjectUseCase],
):
    try:
        project = await use_case.execute(project_id)
        return schemas.ProjectDetailDTO(
            id=project.id,
            keyword=project.keyword,
            competitors=[
                schemas.CompetitorDetailDTO.model_validate(c)
                for c in (project.competitors or [])
            ],
            articles=[
                schemas.ArticleResponse.model_validate(a)
                for a in (project.articles or [])
            ],
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