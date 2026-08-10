
from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.config.settings import settings
from src.application.mcp.auth import mcp_resource_server_url

router = APIRouter(prefix="/api-keys/mcp", tags=["mcp"])


class McpConnectInfo(BaseModel):
    url: str = Field(description="MCP endpoint URL (Streamable HTTP)")
    transport: str = "streamable-http"
    auth_type: str = Field(default="bearer", alias="authType")
    auth_header: str = Field(
        default="Authorization: Bearer YOUR_JWT_KEY",
        alias="authHeader",
    )
    cursor_config_example: dict = Field(alias="cursorConfigExample")
    claude_desktop_config_example: dict = Field(alias="claudeDesktopConfigExample")
    tools: list[str] = Field(description="Available MCP tool names")

    model_config = {"populate_by_name": True}


def _mcp_url() -> str:
    return mcp_resource_server_url(settings.base_url)


def _cursor_example() -> dict:
    return {
        "mcpServers": {
            "competitors-analyzer": {
                "url": _mcp_url(),
                "headers": {
                    "Authorization": "Bearer YOUR_JWT_OR_API_KEY",
                },
            },
        },
    }


def _claude_example() -> dict:
    return {
        "mcpServers": {
            "competitors-analyzer": {
                "command": "npx",
                "args": ["-y", "mcp-remote", _mcp_url(), "--header", "Authorization: Bearer YOUR_JWT_OR_API_KEY"],
            },
        },
    }


@router.get("/connect", response_model=McpConnectInfo)
async def get_mcp_connect_info():
    """Инструкция для подключения облачного MCP по Streamable HTTP (SSE)."""
    return McpConnectInfo(
        url=_mcp_url(),
        authType="bearer",
        authHeader="Authorization: Bearer YOUR_JWT_OR_API_KEY",
        cursorConfigExample=_cursor_example(),
        claudeDesktopConfigExample=_claude_example(),
        tools=["analyze_competitors", "generate_seo_article", "continue_chat_refinement"],
    )