
import base64
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import httpx
from src.config.settings import settings

AGGREGATOR_DOMAINS = {
    "ozon.ru", "www.ozon.ru",
    "wildberries.ru", "www.wildberries.ru",
    "vseinstrumenti.ru", "www.vseinstrumenti.ru",
    "avito.ru", "www.avito.ru",
    "market.yandex.ru", "megamarket.ru",
    "lemanapro.ru", "nizhniy-novgorod.lemanapro.ru",
    "dns-shop.ru", "www.dns-shop.ru",
    "kwork.ru", "www.kwork.ru",
    "aliexpress.ru", "www.aliexpress.ru"
}


class YandexSearchGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._api_key = settings.YANDEX_API_KEY
        self._folder_id = settings.YANDEX_FOLDER_ID
        self._v2_url = "https://searchapi.api.cloud.yandex.net/v2/web/search"

    @staticmethod
    def _clean_tags(text: str) -> str:
        return re.sub(r'<[^>]+>', '', text).strip()

    @staticmethod
    def _is_aggregator(url: str) -> bool:
        """Проверяет, является ли сайт маркетплейсом или агрегатором."""
        try:
            domain = urlparse(url).netloc.lower()
            return any(agg in domain for agg in AGGREGATOR_DOMAINS)
        except Exception:
            return False

    async def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        fallback_results = [
                               {
                                   "url": "https://ru.wikipedia.org/wiki/Эспрессо",
                                   "title": "Эспрессо — Википедия",
                                   "description": "Эспрессо — напиток из кофе."
                               }
                           ][:limit]

        if not self._api_key or self._api_key == "YOUR_YANDEX_API_KEY":
            return fallback_results

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
                "groupsOnPage": limit + 7
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
                results: list[dict[str, str]] = []

                if "rawData" in data and data["rawData"]:
                    xml_bytes = base64.b64decode(data["rawData"])
                    xml_str = xml_bytes.decode("utf-8")
                    root = ET.fromstring(xml_str)

                    for doc in root.findall(".//doc"):
                        url_node = doc.find("url")
                        title_node = doc.find("title")
                        passage_node = doc.find(".//passage")

                        url_text = url_node.text if url_node is not None and url_node.text else ""

                        if not url_text or self._is_aggregator(url_text):
                            print(f"[YandexSearchGateway Skipping Aggregator]: {url_text}")
                            continue

                        title_text = ""
                        if title_node is not None:
                            title_raw = ET.tostring(title_node, encoding="utf-8").decode("utf-8")
                            title_text = self._clean_tags(title_raw)

                        desc_text = ""
                        if passage_node is not None:
                            desc_raw = ET.tostring(passage_node, encoding="utf-8").decode("utf-8")
                            desc_text = self._clean_tags(desc_raw)

                        results.append({
                            "url": url_text,
                            "title": title_text or url_text,
                            "description": desc_text
                        })

                if results:
                    filtered_results = results[:limit]
                    print(
                        f"\n[YandexSearchGateway V2 Success]: По запросу '{query}' отобрано {len(filtered_results)} РЕАЛЬНЫХ КОМПАНИЙ (маркетплейсы отфильтрованы):")
                    for idx, res in enumerate(filtered_results, 1):
                        print(f"  {idx}. {res['url']}")
                    print()
                    return filtered_results

            return fallback_results

        except Exception as e:
            print(f"[YandexSearchGateway Error]: {type(e).__name__} - {e}")
            return fallback_results