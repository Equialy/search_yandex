
import base64
import xml.etree.ElementTree as ET
import httpx
from src.config.settings import settings


class YandexSearchGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._api_key = settings.YANDEX_API_KEY
        self._folder_id = settings.YANDEX_FOLDER_ID
        self._v2_url = "https://searchapi.api.cloud.yandex.net/v2/web/search"

    async def search(self, query: str, limit: int = 5) -> list[str]:
        fallback_urls = [
                            "https://r52.ru/website-development/razrabotka-sayta-vizitki/",
                            # "https://ru.wikipedia.org/wiki/Кофемашина",
                        ][:limit]

        if not self._api_key or self._api_key == "YOUR_YANDEX_API_KEY":
            return fallback_urls

        headers = {
            "Authorization": f"Api-Key {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }

        payload = {
            "folderId": self._folder_id,
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": query
            },
            "groupSpec": {
                "groupsOnPage": limit
            }
        }

        try:
            response = await self._client.post(
                self._v2_url,
                json=payload,
                headers=headers,
                timeout=12.0
            )

            if response.status_code == 200:
                data = response.json()
                urls: list[str] = []

                # 1. Распаковываем Base64 rawData от Yandex Search API V2
                if "rawData" in data and data["rawData"]:
                    xml_bytes = base64.b64decode(data["rawData"])
                    xml_str = xml_bytes.decode("utf-8")
                    root = ET.fromstring(xml_str)

                    for doc in root.findall(".//doc"):
                        url_node = doc.find("url")
                        if url_node is not None and url_node.text:
                            urls.append(url_node.text)

                # 2. Фолбек, если ответ пришел без rawData
                elif "groups" in data:
                    for group in data.get("groups", []):
                        for doc in group.get("documents", []):
                            doc_url = doc.get("url")
                            if doc_url:
                                urls.append(doc_url)

                if urls:
                    print(
                        f"[YandexSearchGateway V2 Success]: Успешно получено {len(urls)} живых сайтов из Яндекса: {urls[:limit]}")
                    return urls[:limit]

            print(f"[YandexSearchGateway V2 Error {response.status_code}]: {response.text}")
            return fallback_urls

        except Exception as e:
            print(f"[YandexSearchGateway Error]: {type(e).__name__} - {e}")
            return fallback_urls