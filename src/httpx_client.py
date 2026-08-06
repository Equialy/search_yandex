from typing import Annotated

import httpx
from fastapi import Request, Depends


async def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


httpxClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]