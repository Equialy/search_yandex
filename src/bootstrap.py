from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.api.v1.agent.routers import router as agent_router
from src.api.v1.competitors.routers import router as competitors_router
from src.api.v1.text_router.routers import router as text_router
from src.application.mcp.router import router as mcp_connect_router

# Импорты MCP для bootstrap
from src.application.mcp.server import mount_mcp
from src.application.mcp.proxy import set_mcp_app


from src.api.v1.auth.routers import router as auth_router

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
    app.include_router(auth_router)
    app.include_router(competitors_router)
    app.include_router(text_router)
    app.include_router(agent_router)
    app.include_router(mcp_connect_router)

    app.mount("/mcp", mount_mcp())
    # 3. Раздача React SPA фронтенда
    index_file = DIST_DIR / "index.html"
    assets_dir = DIST_DIR / "assets"

    print(
        f"[Bootstrap]: Проверка статики -> DIST_DIR: {DIST_DIR} (exists: {DIST_DIR.exists()}), index.html: {index_file.is_file()}")

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

    if index_file.is_file():
        # Явный маршрут для корня сайта (http://185.200.176.45:8000/)
        @app.get("/", include_in_schema=False)
        async def serve_root():
            return FileResponse(index_file)

        # Маршрут для всех внутренних страниц React Router (/login, /projects, /agent и т.д.)
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Пропускаем системные API роуты
            if full_path in ("api", "v1", "docs", "redoc", "openapi.json") or full_path.startswith(("api/", "v1/")):
                raise HTTPException(status_code=404, detail="API not found")

            # Если запрошен конкретный файл (favicon.ico, manifest.json)
            file = DIST_DIR / full_path
            if file.is_file():
                return FileResponse(file)

            # Для всех остальных путей отдаем index.html
            return FileResponse(index_file)
    else:
        print(
            "⚠️ [Bootstrap Warning]: Файл index.html НЕ найден в папке dist! Проверьте, что вы загрузили файлы фронтенда на сервер.")

    return app