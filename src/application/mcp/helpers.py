from __future__ import annotations
import json
from typing import Any
from mcp.server.auth.middleware.auth_context import get_access_token
from src.application.mcp.proxy import call_internal_api


def require_api_key() -> str:
    access = get_access_token()
    if not access or not access.token:
        raise RuntimeError("MCP authentication required: Bearer JWT / API key")
    return access.token


def tool_result(status: int, body: Any) -> str:
    return json.dumps({"status": status, "data": body}, ensure_ascii=False, default=str)


async def call_api(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    api_key = require_api_key()
    status, body = await call_internal_api(
        method=method,
        path=path,
        api_key=api_key,
        json_body=json_body,
        params=params,
    )
    return tool_result(status, body)