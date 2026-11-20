from dishka import Provider, Scope, provide

from src.api.v1.text_router.service import TextAiService
from src.application.harness.article_harness import (
    ArticleQualityConfig,
    ArticleQualityHarness,
)
from src.application.uow import UnitOfWorkProtocol
from src.application.use_cases.agent_chat import AgentChatUseCase
from src.application.use_cases.analyze_competitors import AnalyzeCompetitorsUseCase
from src.application.use_cases.chat_context import ContinueContextChatUseCase
from src.application.use_cases.generate_article import GenerateArticleInteractor
from src.application.use_cases.generate_article.interfaces import (
    ArticleDraftGenerator,
    ArticleFileExporter,
    ArticleIllustrator,
    ArticleVerifier,
    TargetBrandResolver,
)
from src.application.use_cases.generate_article.services import (
    ArticleIllustratorService,
    LlmArticleDraftGenerator,
    LocalArticleHtmlExporter,
    TargetBrandService,
)
from src.application.use_cases.get_project import GetProjectUseCase
from src.application.use_cases.list_projects import ListProjectsUseCase
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.llm_gateway import LLMGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway


class CompetitorsProvider(Provider):
    @provide(scope=Scope.APP)
    def get_article_quality_config(self) -> ArticleQualityConfig:
        return ArticleQualityConfig()



    @provide(scope=Scope.REQUEST)
    def get_article_verifier(
        self,
        ai_gateway: KieApiGateway,
        text_ai_service: TextAiService,
        config: ArticleQualityConfig,
    ) -> ArticleVerifier:
        return ArticleQualityHarness(
            ai_gateway=ai_gateway,
            text_ai_service=text_ai_service,
            config=config,
        )

    target_brand_resolver = provide(
        TargetBrandService,
        scope=Scope.REQUEST,
        provides=TargetBrandResolver,
    )
    article_draft_generator = provide(
        LlmArticleDraftGenerator,
        scope=Scope.REQUEST,
        provides=ArticleDraftGenerator,
    )
    
    article_illustrator = provide(
        ArticleIllustratorService,
        scope=Scope.REQUEST,
        provides=ArticleIllustrator,
    )
    article_exporter = provide(
        LocalArticleHtmlExporter,
        scope=Scope.APP,
        provides=ArticleFileExporter,
    )
    generate_article_interactor = provide(
        GenerateArticleInteractor,
        scope=Scope.REQUEST,
    )

    @provide(scope=Scope.REQUEST)
    def get_analyze_competitors_use_case(
        self,
        uow: UnitOfWorkProtocol,
        yandex_gateway: YandexSearchGateway,
        parser_gateway: SiteParserGateway,
        kie_gateway: KieApiGateway,
        text_ai_service: TextAiService,
    ) -> AnalyzeCompetitorsUseCase:
        return AnalyzeCompetitorsUseCase(
            uow=uow,
            yandex_gateway=yandex_gateway,
            parser_gateway=parser_gateway,
            ai_gateway=kie_gateway,
            text_ai_service=text_ai_service,
        )

    llm_gateway = provide(LLMGateway, scope=Scope.APP)
    chat_context_use_case = provide(ContinueContextChatUseCase, scope=Scope.REQUEST)
    text_ai_service = provide(TextAiService, scope=Scope.REQUEST)
    list_projects_use_case = provide(ListProjectsUseCase, scope=Scope.REQUEST)
    get_project_use_case = provide(GetProjectUseCase, scope=Scope.REQUEST)
    agent_chat_use_case = provide(AgentChatUseCase, scope=Scope.REQUEST)