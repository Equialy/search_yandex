
from __future__ import annotations
import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from src.config.settings import settings


class CompetitorApiKeyVerifier(TokenVerifier):
    """Декодирует JWT-токен доступа для авторизации вызовов MCP."""

    required_scopes: list[str] = ["mcp"]

    async def verify_token(self, token: str | None) -> AccessToken | None:
        if not token:
            return None

        if settings.IS_LOCAL and token == "test_mcp_key":
            return AccessToken(
                token=token,
                client_id="test",
                scopes=self.required_scopes,
                subject="test"
            )

        try:
            payload = jwt.decode(
                token,
                settings.jwt.secret_key,
                algorithms=[settings.jwt.algorithm]
            )
            user_id = payload.get("sub")
            if not user_id:
                return None

            return AccessToken(
                token=token,
                client_id=str(user_id),
                scopes=self.required_scopes,
                subject=str(user_id),
                claims={"user_id": user_id},
            )
        except Exception:
            return None


def mcp_resource_server_url(api_url: str) -> str:
    base = api_url.rstrip("/")
    return f"{base}/mcp/"