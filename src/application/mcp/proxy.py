from __future__ import annotations
import json
from typing import Any

import httpx
from fastapi import FastAPI
from httpx import ASGITransport

_app: FastAPI | None = None


def set_mcp_app(app: FastAPI) -> None:
    global _app
    _app = app


def _require_app() -> FastAPI:
    if _app is None:
        raise RuntimeError("MCP app is not initialized")
    return _app


async def call_internal_api(
        *,
        method: str,
        path: str,
        api_key: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    app = _require_app()
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://internal",
    ) as client:
        resp = await client.request(
            method,
            path,
            headers=headers,
            json=json_body,
            params=params,
        )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = resp.text
    return resp.status_code, body