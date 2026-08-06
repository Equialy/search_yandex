import logging

import uvicorn
from fastapi import FastAPI

from src.application.ioc.competitors import CompetitorsProvider
from src.application.ioc.gateways import GatewaysProvider
from src.application.ioc.infrastructure import InfrastructureProvider
from src.bootstrap import apply_routes, lifespan
from src.middlewares import apply_middleware
from dishka.integrations.fastapi import setup_dishka, FastapiProvider
from dishka import make_async_container
from src.config.settings import settings, config_logging




container = make_async_container(
    InfrastructureProvider(),
    GatewaysProvider(),
    CompetitorsProvider(),
    FastapiProvider(),
)


def create_app() -> FastAPI:
    config_logging(level=logging.INFO)
    app = FastAPI(
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/docs.json",
        lifespan=lifespan
    )
    app = apply_routes(apply_middleware(app))
    setup_dishka(container, app)
    # register_exceptions_hanlder(app)
    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("src.main:app", host=settings.app_host, port=settings.app_port, reload=False)
