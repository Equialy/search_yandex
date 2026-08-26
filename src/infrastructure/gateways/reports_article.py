
import httpx
from src.api.v1.reports_api.schemas import (
    ReportsArticleResponse,
    SendArticleReportPayload,
    SendArticleReportResponse,
)
from src.config.settings import settings


class ReportsArticleGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client
        self._secret_key = settings.reports.SECRET_KEY
        self._base_url = "http://report.joom-cloud2.ru/AI"

    async def get_task(self) -> ReportsArticleResponse:
        """
        GET: Получает задачу из очереди сервиса Reports.
        """
        url = f"{self._base_url}/ai_article.php?key={self._secret_key}"
        response = await self._http_client.get(url, timeout=20.0)
        response.raise_for_status()
        return ReportsArticleResponse.model_validate(response.json())

    async def send_article(
            self,
            payload: SendArticleReportPayload
    ) -> SendArticleReportResponse:
        """
        POST: Отправляет готовую статью в БД сервиса Reports.
        """
        url = f"{self._base_url}/ai_article_to_DB.php?key={self._secret_key}"

        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }

        response = await self._http_client.post(
            url=url,
            json=payload.model_dump(),
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        return SendArticleReportResponse.model_validate(response.json())