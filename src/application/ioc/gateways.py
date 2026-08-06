from dishka import Provider, Scope, provide

from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.llm_gateway import LLMGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway


class GatewaysProvider(Provider):

    yandex_gateway = provide(
        YandexSearchGateway,
        scope=Scope.APP,
    )

    site_parser = provide(
        SiteParserGateway,
        scope=Scope.APP,
    )


    kie_gateway = provide(
        KieApiGateway,
        scope=Scope.APP,
    )