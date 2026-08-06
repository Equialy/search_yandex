
import xml.etree.ElementTree as ET
import httpx
from src.config.settings import settings


class YandexSearchGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._api_key = settings.YANDEX_API_KEY
        self._folder_id = settings.YANDEX_FOLDER_ID

    async def search(self, query: str, limit: int = 5) -> list[str]:
        # Если API-ключ не задан — используем РЕАЛЬНЫЕ валидные сайты для теста
        if not self._api_key or self._api_key == "YOUR_YANDEX_API_KEY":
            return [
                "https://ru.wikipedia.org/wiki/Эспрессо",
                "https://ru.wikipedia.org/wiki/Кофемашина",
            ][:limit]

        params = {
            "folderid": self._folder_id,
            "apikey": self._api_key,
            "query": query,
            "groupby": f"attr=d.mode=deep.groups-on-page={limit}.docs-in-group=1",
        }

        try:
            response = await self._client.get("https://yandex.ru/search/xml", params=params, timeout=10.0)
            response.raise_for_status()

            root = ET.fromstring(response.text)
            urls: list[str] = []

            for doc in root.findall(".//doc"):
                url_node = doc.find("url")
                if url_node is not None and url_node.text:
                    urls.append(url_node.text)

            return urls[:limit]
        except Exception as e:
            print(f"[YandexSearchGateway Error]: {e}")
            return []