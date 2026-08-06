import httpx
from dishka import Provider, Scope, provide
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.application.uow import UnitOfWork, UnitOfWorkProtocol
from src.config.settings import settings
from src.infrastructure.database.engine import new_engine, new_session_maker
from src.infrastructure.gateways.llm_gateway import LLMGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway
from src.infrastructure.gateways.yandex_search import YandexSearchGateway


class InfrastructureProvider(Provider):
    # Singleton ресурсы ( Scope.APP )
    @provide(scope=Scope.APP)
    def get_engine(self) -> AsyncEngine:
        return new_engine(settings.DATABASE_URL)

    @provide(scope=Scope.APP)
    def get_session_maker(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return new_session_maker(engine)

    @provide(scope=Scope.APP)
    async def get_http_client(self) -> httpx.AsyncClient:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            yield client

    @provide(scope=Scope.APP)
    def get_openai_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    @provide(scope=Scope.APP)
    def get_llm_gateway(self, openai_client: AsyncOpenAI) -> LLMGateway:
        return LLMGateway(openai_client, model=settings.OPENAI_MODEL)

    @provide(scope=Scope.APP)
    def get_yandex_gateway(self, http_client: httpx.AsyncClient) -> YandexSearchGateway:
        return YandexSearchGateway(http_client, settings.YANDEX_API_KEY, settings.YANDEX_FOLDER_ID)

    @provide(scope=Scope.APP)
    def get_site_parser(self, http_client: httpx.AsyncClient) -> SiteParserGateway:
        return SiteParserGateway(http_client)

    # Scoped ресурсы под один HTTP Запрос ( Scope.REQUEST )
    @provide(scope=Scope.REQUEST)
    async def get_session(self, session_maker: async_sessionmaker[AsyncSession]) -> AsyncSession:
        async with session_maker() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    def get_uow(self, session: AsyncSession) -> UnitOfWorkProtocol:
        return UnitOfWork(session)