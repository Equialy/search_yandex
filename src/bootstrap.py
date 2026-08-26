from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.infrastructure.tasks.broker import broker
from src.api.v1.agent.routers import router as agent_router
from src.api.v1.competitors.routers import router as competitors_router
from src.api.v1.text_router.routers import router as text_router
from src.application.mcp.router import router as mcp_connect_router
from src.api.v1.tasks.routers import router as tasks_router
from src.api.v1.reports_api.routers import router as reports_router

# Импорты MCP для bootstrap
from src.application.mcp.server import mount_mcp
from src.application.mcp.proxy import set_mcp_app


from src.api.v1.auth.routers import router as auth_router

from src.config.settings import BASE_DIR

DIST_DIR = BASE_DIR / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not broker.is_worker_process:
        await broker.startup()

    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    timeout = httpx.Timeout(60.0)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)

    set_mcp_app(app)

    mcp_app = mount_mcp()

    try:
        async with mcp_app.lifespan(app):
            yield
    finally:
        await app.state.http_client.aclose()
        if not broker.is_worker_process:
            await broker.shutdown()


def apply_routes(app: FastAPI) -> FastAPI:
    app.include_router(auth_router)
    app.include_router(competitors_router)
    app.include_router(text_router)
    app.include_router(agent_router)
    app.include_router(mcp_connect_router)
    app.include_router(tasks_router)
    app.include_router(reports_router)

    app.mount("/mcp", mount_mcp())

    static_dir = BASE_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    if DIST_DIR.is_dir():
        assets_dir = DIST_DIR / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")

        index_file = DIST_DIR / "index.html"
        if index_file.is_file():
            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa_fallback(full_path: str):
                if full_path in ("api", "v1", "static") or full_path.startswith(("api/", "v1/", "static/")):
                    raise HTTPException(status_code=404, detail="Not found")

                if any(part.startswith('.') for part in full_path.split('/')):
                    raise HTTPException(status_code=404, detail="Not found")

                file = DIST_DIR / full_path
                if file.is_file():
                    return FileResponse(file)
                return FileResponse(index_file)

    return app