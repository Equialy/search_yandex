import httpx
from dishka import Provider, Scope, provide
from openai import AsyncOpenAI

from src.infrastructure.gateways.image_gateway import ImageGenerationGateway
from src.infrastructure.gateways.kie_api import KieApiGateway
from src.infrastructure.gateways.llm_gateway import LLMGateway
from src.infrastructure.gateways.openai_gateway import OpenAiGateway
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