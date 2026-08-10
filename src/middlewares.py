from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware



def apply_middleware(app: FastAPI) -> FastAPI:

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
        # Браузерный MCP-клиент обязан прочитать session id из ответа initialize,
        # иначе последующие запросы уходят без сессии и получают 400.
        expose_headers=["mcp-session-id", "mcp-protocol-version"],
    )
    return app
