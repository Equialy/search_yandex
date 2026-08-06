from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from src.api.v1.competitors.routers import router as competitors_router


from src.config.settings import BASE_DIR

DIST_DIR = BASE_DIR / "dist"






@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    timeout = httpx.Timeout(60.0)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)

    # if not broker.is_worker_process:
    #     await broker.startup()
    #
    yield
    #
    # if not broker.is_worker_process:
    #     await broker.shutdown()
    await app.state.http_client.aclose()


def apply_routes(app: FastAPI) -> FastAPI:
    app.include_router(competitors_router)

    return app
