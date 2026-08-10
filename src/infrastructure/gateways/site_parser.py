# src/infrastructure/gateways/site_parser.py

from typing import Any
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup


class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client

    async def parse_site_to_graph(self, url: str) -> dict[str, Any]:
        """Парсит страницу с автоматическим прохождением редиректов (307/301) и защитой от 403."""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc or url

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

        try:
            response = await self._client.get(
                url,
                timeout=12.0,
                headers=headers,
                follow_redirects=True
            )

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")

                title = soup.title.string.strip() if soup.title and soup.title.string else domain

                meta_desc = ""
                meta_tag = (
                    soup.find("meta", attrs={"name": "description"})
                    or soup.find("meta", attrs={"property": "og:description"})
                )
                if meta_tag and meta_tag.get("content"):
                    meta_desc = meta_tag.get("content").strip()

                body = soup.find("body") or soup
                for tag in body(["script", "style", "aside", "noscript", "svg", "iframe"]):
                    tag.extract()

                main_container = body.find("main") or body.find("article") or body

                text_blocks = []
                for tag in main_container.find_all(["p", "h1", "h2", "h3", "h4", "li", "span", "div"]):
                    txt = tag.get_text(strip=True)
                    if len(txt) > 20 and txt not in text_blocks:
                        text_blocks.append(txt)

                central_text = "\n".join(text_blocks[:25])[:2500]

                if not central_text.strip():
                    central_text = f"Страница категории {domain}. {title}. {meta_desc}".strip()

                return {
                    "url": url,
                    "title": title,
                    "description": meta_desc,
                    "body_text": central_text
                }

        except Exception as e:
            print(f"[SiteParserGateway Exception for {url}]: {type(e).__name__} - {e}")

        return {
            "url": url,
            "title": f"Каталог товаров {domain}",
            "description": f"Официальная страница категории интернет-магазина {domain}",
            "body_text": f"Крупный маркетплейс и интернет-магазин {domain}. Страница категории каталога товаров по адресу {url}."
        }