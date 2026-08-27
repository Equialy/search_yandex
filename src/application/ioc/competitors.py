from dishka import Provider, Scope, provide

from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.gateways.image_kie_gateway import ImageKieGenerationGateway
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.api.v1.text_router.service import TextAiService
from src.application.use_cases.chat_context import ContinueContextChatUseCase
from src.application.use_cases.list_projects import ListProjectsUseCase
from src.infrastructure.gateways.yandex_search import YandexSearchGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.llm_gateway import LLMGateway

from src.application.use_cases.agent_chat import AgentChatUseCase
from src.application.use_cases.analyze_competitors import AnalyzeCompetitorsUseCase
from src.application.use_cases.generate_article import GenerateArticleUseCase
from src.application.use_cases.get_project import GetProjectUseCase


class CompetitorsProvider(Provider):

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

    @provide(scope=Scope.REQUEST)
    def get_generate_article_use_case(
            self,
            uow: UnitOfWorkProtocol,
            kie_gateway: KieApiGateway,
            parser_gateway: SiteParserGateway,
            image_gateway: ImageKieGenerationGateway,
            text_ai_service: TextAiService,
    ) -> GenerateArticleUseCase:
        return GenerateArticleUseCase(
            uow=uow,
            ai_gateway=kie_gateway,
            parser_gateway=parser_gateway,
            image_gateway=image_gateway,
            text_ai_service=text_ai_service,
        )

    yandex_gateway = provide(
        YandexSearchGateway,
        scope=Scope.APP,
    )

    parser_gateway = provide(
        SiteParserGateway,
        scope=Scope.APP,
    )

    llm_gateway = provide(
        LLMGateway,
        scope=Scope.APP,
    )

    analyze_competitors_use_case = provide(
        AnalyzeCompetitorsUseCase,
        scope=Scope.REQUEST,
    )

    generate_article_use_case = provide(
        GenerateArticleUseCase,
        scope=Scope.REQUEST,
    )

    chat_context_use_case = provide(
        ContinueContextChatUseCase,
        scope=Scope.REQUEST,
    )

    text_ai_service = provide(
        TextAiService,
        scope=Scope.REQUEST,
    )

    list_projects_use_case = provide(
        ListProjectsUseCase,
        scope=Scope.REQUEST,
    )

    get_project_use_case = provide(
        GetProjectUseCase,
        scope=Scope.REQUEST,
    )

    agent_chat_use_case = provide(
        AgentChatUseCase,
        scope=Scope.REQUEST,
    )
