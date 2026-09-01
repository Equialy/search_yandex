import base64
import enum
import logging
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import httpx
from src.config.settings import settings

logger = logging.getLogger(__name__)

AGGREGATOR_DOMAINS = frozenset({
    "ozon.ru", "www.ozon.ru",
    "wildberries.ru", "www.wildberries.ru",
    "vseinstrumenti.ru", "www.vseinstrumenti.ru",
    "avito.ru", "www.avito.ru",
    "market.yandex.ru", "megamarket.ru",
    "lemanapro.ru", "nizhniy-novgorod.lemanapro.ru",
    "dns-shop.ru", "www.dns-shop.ru",
    "kwork.ru", "www.kwork.ru",
    "aliexpress.ru", "www.aliexpress.ru",
    "sbermegamarket.ru",

    "uslugi.yandex.ru", "yandex.ru/uslugi",
    "profi.ru", "www.profi.ru",
    "youdo.com", "youdo.ru",
    "fl.ru", "freelance.ru", "habr.com",

    "2gis.ru", "www.2gis.ru", "2gis.com",
    "zoon.ru", "www.zoon.ru",
    "flamp.ru", "www.flamp.ru",
    "yandex.ru",
    "yell.ru", "www.yell.ru",
    "spravker.ru", "orgpage.ru", "yp.ru",

    "otzovik.com", "irecommend.ru",
    "hh.ru", "superjob.ru", "rabota.ru",
    "cian.ru", "domclick.ru", "realty.yandex.ru"
})


class SearchTypeEnum(str, enum.Enum):
    RU = "SEARCH_TYPE_RU"


class FormatTypeEnum(str, enum.Enum):
    XML = "FORMAT_XML"
    HTML = "FORMAT_HTML"


class YandexSearchGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._httpx_client = http_client
        self.api_key_yandex = settings.YANDEX_API_KEY
        self.folder_id_yandex = settings.YANDEX_FOLDER_ID
        self._v2_url_yandex = "https://searchapi.api.cloud.yandex.net/v2/web/search"

    @staticmethod
    def _is_aggregator(url: str) -> bool:
        """Проверяет, является ли домен маркетплейсом или каталогом."""
        try:
            domain = urlparse(url.lower()).netloc
            return any(agg in domain for agg in AGGREGATOR_DOMAINS)
        except Exception:
            return False

    async def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        headers = {
            "Authorization": f"Api-Key {self.api_key_yandex}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }

        payload = {
            "folderId": self.folder_id_yandex,
            "query": {
                "searchType": SearchTypeEnum.RU.value,
                "queryText": query,
            },
            "groupSpec": {
                "groupsOnPage": limit + 15,
                "groupMode": "GROUP_MODE_FLAT"
            },
            "responseFormat": FormatTypeEnum.XML.value,
        }

        try:
            response = await self._httpx_client.post(
                url=self._v2_url_yandex,
                headers=headers,
                timeout=15.0,
                json=payload
            )
            response.raise_for_status()

            raw_base64 = response.json().get("rawData", "")
            if not raw_base64:
                return []

            xml_string = base64.b64decode(raw_base64).decode("utf-8", errors="ignore")
            root = ET.fromstring(xml_string)

            results = []
            for doc in root.findall(".//doc"):
                url_node = doc.find("url")
                title_node = doc.find("title")
                passage_node = doc.find(".//passage")

                url = url_node.text.strip() if (url_node is not None and url_node.text) else ""

                if not url or self._is_aggregator(url):
                    continue

                title = "".join(title_node.itertext()).strip() if title_node is not None else url
                description = "".join(passage_node.itertext()).strip() if passage_node is not None else ""

                results.append({
                    "url": url,
                    "title": title,
                    "description": description
                })

                if len(results) >= limit:
                    break

            logger.info(f"YandexSearch: найдено {len(results)} реальных сайтов по ключу '{query}'")
            return results

        except Exception as e:
            logger.error(f"YandexSearch error: {e}")
            raise e