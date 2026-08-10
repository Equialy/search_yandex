import re
from typing import Any
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

try:
    from curl_cffi.requests import AsyncSession
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False


class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client

    async def parse_site_to_graph(
        self,
        url: str,
        fallback_title: str = "",
        fallback_desc: str = ""
    ) -> dict[str, Any]:
        """Извлекает УНИКАЛЬНЫЙ текст со страницы без дублирования родительских тегов."""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc or url

        html_text = ""

        if CURL_CFFI_AVAILABLE:
            try:
                async with AsyncSession(impersonate="chrome124") as session:
                    res = await session.get(url, timeout=15, allow_redirects=True)
                    if res.status_code == 200:
                        html_text = res.text
            except Exception as e:
                print(f"[curl_cffi Warning for {url}]: {e}")

        if not html_text and hasattr(self._client, "get"):
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
                }
                res = await self._client.get(url, timeout=12.0, headers=headers, follow_redirects=True)
                if res.status_code == 200:
                    html_text = res.text
            except Exception as e:
                print(f"[httpx Warning for {url}]: {e}")

        if html_text:
            soup = BeautifulSoup(html_text, "html.parser")

            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            if not title:
                og_title = soup.find("meta", attrs={"property": re.compile(r"og:title$", re.I)})
                if og_title and og_title.get("content"):
                    title = og_title.get("content").strip()

            final_title = title or fallback_title or domain

            meta_desc = ""
            meta_tag = (
                soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
                or soup.find("meta", attrs={"property": re.compile(r"description$", re.I)})
            )
            if meta_tag and meta_tag.get("content"):
                meta_desc = meta_tag.get("content").strip()

            final_desc = meta_desc or fallback_desc or ""

            body = soup.find("body") or soup
            for tag in body(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "iframe", "form"]):
                tag.extract()

            unique_lines = []
            for string in body.stripped_strings:
                clean_str = string.strip()
                if len(clean_str) > 3 and (not unique_lines or unique_lines[-1] != clean_str):
                    unique_lines.append(clean_str)

            clean_body_text = "\n".join(unique_lines)

            if len(clean_body_text.strip()) > 50:
                print(f"[SiteParserGateway Success]: Извлечено {len(clean_body_text)} символов чистого уникального текста с {domain}!")
                return {
                    "url": url,
                    "title": final_title,
                    "description": final_desc,
                    "body_text": clean_body_text
                }

        real_title = fallback_title or f"Сайт {domain}"
        real_desc = fallback_desc or f"Страница {domain}"

        return {
            "url": url,
            "title": real_title,
            "description": real_desc,
            "body_text": f"Заголовок: {real_title}\nОписание: {real_desc}"
        }