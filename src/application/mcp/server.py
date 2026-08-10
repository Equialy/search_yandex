
from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl

from starlette.applications import Starlette

from src.config.settings import settings
from src.application.mcp.auth import CompetitorApiKeyVerifier, mcp_resource_server_url
from src.application.mcp.helpers import call_api



_mcp_resource_url = mcp_resource_server_url(settings.base_url)

# Инициализируем единый провайдер авторизации по стандарту FastMCP 2.x
auth_provider = RemoteAuthProvider(
    token_verifier=CompetitorApiKeyVerifier(),
    authorization_servers=[AnyHttpUrl(settings.base_url.rstrip("/"))],
    base_url=settings.base_url.rstrip("/"),
)

mcp_server = FastMCP(
    "CompetitorAnalyzer",
    instructions=(
        "SEO Competitor Analyzer AI Tools. "
        "Use analyze_competitors to search and scrape competitor websites from Yandex, "
        "then use generate_seo_article to write high-quality articles based on the collected LSA context."
    ),
    website_url=settings.base_url.rstrip("/"),
    auth=auth_provider,
)

mcp_http_app = mcp_server.http_app(path="/")


def mount_mcp() -> Starlette:
    """Возвращает единственный запущенный экземпляр приложения MCP."""
    return mcp_http_app

@mcp_server.tool(
    name="analyze_competitors",
    description="Поиск конкурентов в Яндексе, глубокий LSA и коммерческий анализ по методичке.",
)
async def analyze_competitors(
        keyword: str | None = None,
        url: str | None = None,
        limit: int = 3,
        project_id: str | None = None,
) -> str:
    payload = {"limit": limit}
    if keyword:
        payload["keyword"] = keyword
    if url:
        payload["url"] = url
    if project_id:
        payload["projectId"] = project_id

    return await call_api("POST", "/v1/competitors/analyze", json_body=payload)


@mcp_server.tool(
    name="generate_seo_article",
    description="Генерация коммерческой SEO-статьи по методичке на основе ранее собранной базы знаний проекта.",
)
async def generate_seo_article(
        project_id: str,
        topic: str,
        target_site: str = "",
        instructions: str = "",
) -> str:
    payload = {
        "topic": topic,
        "instructions": instructions,
        "targetSite": target_site
    }
    return await call_api("POST", f"/v1/competitors/projects/{project_id}/generate-article", json_body=payload)


@mcp_server.tool(
    name="continue_chat_refinement",
    description="Внесение правок в готовую статью или диалог с ИИ в контексте проекта.",
)
async def continue_chat_refinement(
        project_id: str,
        prompt: str,
) -> str:
    payload = {"prompt": prompt}
    return await call_api("POST", f"/v1/competitors/projects/{project_id}/chat", json_body=payload)


