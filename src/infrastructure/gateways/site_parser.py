
from typing import Any
import httpx
from bs4 import BeautifulSoup


class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client

    async def parse_site_to_graph(self, url: str) -> dict[str, Any]:
        """Извлекает Title, Description и центральный текст из <body>."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            response = await self._client.get(url, timeout=12.0, headers=headers)
            if response.status_code != 200:
                return {}
        except Exception:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Извлекаем Title
        title = soup.title.string.strip() if soup.title and soup.title.string else url

        # 2. Извлекаем Meta Description
        meta_desc = ""
        meta_tag = (
            soup.find("meta", attrs={"name": "description"})
            or soup.find("meta", attrs={"property": "og:description"})
        )
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag.get("content").strip()

        # 3. Извлекаем текст из <body>
        body = soup.find("body") or soup

        # Вырезаем только скрипты, стили, иконки (НЕ вырезаем header/form, так как у лендингов там главный оффер)
        for tag in body(["script", "style", "aside", "noscript", "svg", "iframe"]):
            tag.extract()

        # Ищем центральный смысловой контейнер (main, article или весь body)
        main_container = body.find("main") or body.find("article") or body

        # Собираем содержательные текстовые блоки
        text_blocks = []
        for tag in main_container.find_all(["p", "h1", "h2", "h3", "h4", "li", "span", "div"]):
            txt = tag.get_text(strip=True)
            if len(txt) > 20 and txt not in text_blocks:
                text_blocks.append(txt)

        central_text = "\n".join(text_blocks[:30])[:3500]

        # Если текст получился пустым — формируем его из Title и Description
        if not central_text.strip():
            central_text = f"Страница услуги: {title}. {meta_desc}".strip()

        return {
            "url": url,
            "title": title,
            "description": meta_desc,
            "body_text": central_text
        }