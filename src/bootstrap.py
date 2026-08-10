# src/bootstrap.py

from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI

from src.api.v1.agent.routers import router as agent_router
from src.api.v1.competitors.routers import router as competitors_router
from src.api.v1.text_router.routers import router as text_router
from src.application.mcp.router import router as mcp_connect_router

# Импорты MCP для bootstrap
from src.application.mcp.server import mount_mcp
from src.application.mcp.proxy import set_mcp_app

from src.config.settings import BASE_DIR

DIST_DIR = BASE_DIR / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Настройка общего HTTP-клиента FastAPI
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    timeout = httpx.Timeout(60.0)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)

    # 2. Настройка проксирования вызовов MCP к FastAPI-роутам
    set_mcp_app(app)

    # 3. Запускаем lifespan MCP приложения
    mcp_app = mount_mcp()
    async with mcp_app.lifespan(app):
        yield

    # Очистка ресурсов при выключении сервера
    await app.state.http_client.aclose()


def apply_routes(app: FastAPI) -> FastAPI:
    app.include_router(competitors_router)
    app.include_router(text_router)
    app.include_router(agent_router)
    app.include_router(mcp_connect_router)

    # Монтируем единственный экземпляр на /mcp
    app.mount("/mcp", mount_mcp())

    return app