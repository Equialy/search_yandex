import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.application.services.reports_api.poller import start_reports_polling_loop
from src.infrastructure.gateways.reports_article import ReportsArticleGateway
from src.infrastructure.tasks.broker import broker
from src.api.v1.agent.routers import router as agent_router
from src.api.v1.competitors.routers import router as competitors_router
from src.api.v1.text_router.routers import router as text_router
from src.application.mcp.router import router as mcp_connect_router
from src.api.v1.tasks.routers import router as tasks_router
from src.api.v1.reports_api.routers import router as reports_router
from src.api.v1.auth.routers import router as auth_router

from src.application.mcp.server import mount_mcp
from src.application.mcp.proxy import set_mcp_app

from src.config.settings import BASE_DIR, settings

DIST_DIR = BASE_DIR / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not broker.is_worker_process:
        await broker.startup()

    container = app.state.dishka_container
    reports_gateway = await container.get(ReportsArticleGateway)
    session_maker = await container.get(async_sessionmaker[AsyncSession])

    poller_task = asyncio.create_task(
        start_reports_polling_loop(
            gateway=reports_gateway,
            session_maker=session_maker,
            poll_interval_seconds=settings.reports.POOL_INTERVAL_SECONDS,
        )
    )

    set_mcp_app(app)
    mcp_app = getattr(app.state, "mcp_app", None)

    try:
        if mcp_app and hasattr(mcp_app, "lifespan"):
            async with mcp_app.lifespan(app):
                yield
        else:
            yield
    finally:
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass

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

    mcp_app = mount_mcp()
    app.state.mcp_app = mcp_app
    app.mount("/mcp", mcp_app)

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