from dishka import Provider, Scope, provide

from src.infrastructure.gateways.yandex_search import YandexSearchGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.llm_gateway import LLMGateway

from src.application.use_cases.analyze_competitors import AnalyzeCompetitorsUseCase
from src.application.use_cases.generate_article import GenerateArticleUseCase


class CompetitorsProvider(Provider):

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