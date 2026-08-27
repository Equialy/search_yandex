import httpx
from dishka import Provider, Scope, provide
from openai import AsyncOpenAI

from src.infrastructure.gateways.image_gateway import ImageGenerationGateway
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.llm_gateway import LLMGateway
from src.infrastructure.gateways.openai_gateway import OpenAiGateway
from src.infrastructure.gateways.reports_article import ReportsArticleGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway


class GatewaysProvider(Provider):

    @provide(scope=Scope.REQUEST)
    def get_image_gateway(
            self,
            openai_client: AsyncOpenAI,
            http_client: httpx.AsyncClient
    ) -> ImageGenerationGateway:
        return ImageGenerationGateway(openai_client=openai_client, http_client=http_client)

    @provide(scope=Scope.APP)
    def get_site_parser(self, http_client: httpx.AsyncClient, openai_gateway: OpenAiGateway) -> SiteParserGateway:
        return SiteParserGateway(http_client=http_client, openai_gateway=openai_gateway)

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


    openai_gateway = provide(
        OpenAiGateway,
        scope=Scope.APP,
    )

    reports_gateway = provide(
        ReportsArticleGateway,
        scope=Scope.APP,
    )
