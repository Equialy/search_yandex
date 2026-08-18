from typing import AsyncGenerator
import httpx
import pymorphy3
from dishka import Provider, Scope, provide
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.config.settings import settings
from src.infrastructure.database.engine import new_engine, new_session_maker
from src.application.uow import UnitOfWork, UnitOfWorkProtocol


class InfrastructureProvider(Provider):

    @provide(scope=Scope.APP)
    async def get_engine(self) -> AsyncGenerator[AsyncEngine, None]:
        engine = new_engine(settings.db)
        yield engine
        await engine.dispose()


    @provide(scope=Scope.APP)
    def get_session_maker(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return new_session_maker(engine)

    @provide(scope=Scope.REQUEST)
    async def get_session(
            self,
            session_maker: async_sessionmaker[AsyncSession]
    ) -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    @provide(scope=Scope.APP)
    async def get_http_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        async with httpx.AsyncClient(limits=limits, timeout=15.0, trust_env=False) as client:
            yield client
    #
    # @provide(scope=Scope.APP)
    # def get_openai_client(self) -> AsyncOpenAI:
    #     return AsyncOpenAI(api_key=settings.OPENAI.API_KEY)

    @provide(scope=Scope.APP)
    async def get_openai_client(self) -> AsyncGenerator[AsyncOpenAI, None]:
        proxy_url = settings.proxy.HTTP_PROXY if settings.proxy and settings.proxy.HTTP_PROXY else None

        openai_http_client = httpx.AsyncClient(
            proxy=proxy_url,
            timeout=260.0,
            trust_env=True,
        )

        openai_client = AsyncOpenAI(
            api_key=settings.OPENAI.API_KEY,
            http_client=openai_http_client,
        )

        yield openai_client

        await openai_http_client.aclose()

    @provide(scope=Scope.APP)
    def get_morph_analyzer(self) -> pymorphy3.MorphAnalyzer:
        """Словарь загружается 1 раз при старте приложения"""
        return pymorphy3.MorphAnalyzer()

    uow = provide(
        UnitOfWork,
        scope=Scope.REQUEST,
        provides=UnitOfWorkProtocol,
    )