import logging
import re
from typing import Any
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup, Tag

from src.utils.extract_data import _extract_logo_url

try:
    from curl_cffi.requests import AsyncSession

    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

logger = logging.getLogger(__name__)

_BEGET_CHALLENGE_MARKERS = ("beget=begetok", "set_cookie()", "location.reload()")

_NAV_CHROME_TAGS = frozenset({
    "nav", "header", "footer", "aside", "form", "button",
    "script", "style", "noscript", "svg", "iframe", "dialog"
})

_NAV_ROLES = frozenset({"navigation", "banner", "contentinfo", "menubar", "dialog"})

_NAV_CLASS_PATTERN = re.compile(
    r"(?:^|[\s_-])(?:navbar|site-header|header-menu|footer|cookie-banner|cookie-popup|cookie-notice)(?:$|[\s_-])",
    re.I,
)

_GARBAGE_TEXT_PATTERN = re.compile(
    r"^(?:подробнее|отправить заявку|перезвоните мне|согласен на обработку|политика конфиденциальности|заказать звонок|\+?\d[\d\s\-\(\)]{8,}\d)$",
    re.I
)

_TILDA_TEXT_CLASSES = frozenset({
    "tn-atom", "t-descr", "t-text", "t-title", "t-name", "t-card__descr", "t-card__text"
})


def _is_beget_challenge(html: str) -> bool:
    """Проверяет, вернул ли хостинг Beget антибот-заглушку вместо сайта."""
    if not html or len(html) > 5000:
        return False
    lowered = html.lower()
    return all(marker in lowered for marker in _BEGET_CHALLENGE_MARKERS)


def _clean_dom(soup: BeautifulSoup) -> Tag:
    """Очищает DOM-дерево от мусорных тегов, шапок, подвалов и cookie-плашек."""
    # 1. Удаляем технические и сквозные теги
    for tag_name in _NAV_CHROME_TAGS:
        for tag in soup.find_all(tag_name):
            if isinstance(tag, Tag):
                tag.decompose()

    # 2. Удаляем элементы по ролям и специфичным классам навигации/куки
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag) or not isinstance(tag.attrs, dict):
            continue

        role = str(tag.attrs.get("role", "")).lower()
        if role in _NAV_ROLES:
            tag.decompose()
            continue

        classes = tag.attrs.get("class", [])
        class_str = " ".join(classes) if isinstance(classes, list) else str(classes)
        if class_str and _NAV_CLASS_PATTERN.search(class_str):
            tag.decompose()
            continue

    body = soup.find("body")
    return body if isinstance(body, Tag) else soup


class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client

    async def parse_site_to_graph(
            self,
            url: str,
            fallback_title: str = "",
            fallback_desc: str = ""
    ) -> dict[str, Any]:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc or url

        try:
            html_text = await self._fetch_html(url)

            # 1. Проверка и обход Beget Challenge
            if _is_beget_challenge(html_text):
                logger.info(f"[SiteParserGateway] Обнаружен Beget challenge для {url}, повторный запрос с кукой...")
                html_text = await self._fetch_html(url, cookies={"beget": "begetok"})

            if html_text:
                soup = BeautifulSoup(html_text, "html.parser")

                # 2. Извлекаем логотип и мета-данные ДО очистки DOM
                logo_url = _extract_logo_url(soup, url)
                logger.debug(f"[SiteParserGateway] Извлечен логотип для {url} -> {logo_url}")

                title = ""
                if soup.title and hasattr(soup.title, "get_text"):
                    title = soup.title.get_text(" ", strip=True)

                if not title:
                    og_title = soup.find("meta", attrs={"property": re.compile(r"og:title$", re.I)})
                    if isinstance(og_title, Tag):
                        val = og_title.get("content")
                        if val and isinstance(val, str):
                            title = val.strip()

                final_title = title or fallback_title or domain

                meta_desc = ""
                meta_tag = (
                        soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
                        or soup.find("meta", attrs={"property": re.compile(r"description$", re.I)})
                        or soup.find("meta", attrs={"itemprop": re.compile(r"description$", re.I)})
                )
                if isinstance(meta_tag, Tag):
                    val = meta_tag.get("content")
                    if val and isinstance(val, str):
                        meta_desc = val.strip()

                final_desc = meta_desc or fallback_desc or ""

                # 3. Очищаем DOM на месте без повторного создания объекта BeautifulSoup
                content_root = _clean_dom(soup)

                # 4. Извлечение структуры заголовков (H1–H4)
                headings = []
                for h in content_root.find_all(["h1", "h2", "h3", "h4"]):
                    if isinstance(h, Tag):
                        h_text = h.get_text(" ", strip=True)
                        if h_text and len(h_text) > 3:
                            headings.append({"level": h.name.upper(), "text": h_text})

                # 5. Таблицы в Markdown
                tables_markdown = []
                for table in content_root.find_all("table")[:6]:
                    if not isinstance(table, Tag):
                        continue
                    rows = []
                    header_cells_count = 0
                    for tr_idx, tr in enumerate(table.find_all("tr")[:20]):
                        if not isinstance(tr, Tag):
                            continue
                        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"]) if
                                 isinstance(td, Tag)]
                        if cells and any(c for c in cells):
                            rows.append(" | ".join(cells))
                            if tr_idx == 0:
                                header_cells_count = len(cells)
                                rows.append(" | ".join(["---"] * header_cells_count))
                    if rows:
                        tables_markdown.append("\n".join(rows))

                # 6. FAQ Аккордеоны
                faq_blocks = []
                for details in content_root.find_all(
                        ["details", "div"],
                        class_=re.compile(r"faq|accordion|question|reply|answer", re.I),
                )[:8]:
                    if isinstance(details, Tag):
                        q_text = details.get_text(" ", strip=True)
                        if len(q_text) > 15 and q_text not in faq_blocks:
                            faq_blocks.append(q_text)

                # 7. Извлечение чистого текста (стандартные теги + Tilda/Zero blocks + листовые div)
                paragraphs = []
                for elem in content_root.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "span"]):
                    if isinstance(elem, Tag):
                        # Для div берем либо тильдовские текстовые классы, либо блоки без вложенных p/div
                        if elem.name == "div":
                            classes = " ".join(elem.attrs.get("class", []))
                            is_text_div = any(c in classes for c in _TILDA_TEXT_CLASSES)
                            has_no_nested_blocks = not elem.find(["p", "div"])
                            if not (is_text_div or has_no_nested_blocks):
                                continue

                        text = elem.get_text(" ", strip=True)

                        # Порог в 12 символов сохраняет важные короткие буллеты и факты
                        if len(text) >= 12 and not _GARBAGE_TEXT_PATTERN.match(text):
                            if not paragraphs or paragraphs[-1] != text:
                                # Исключаем дублирование вложенного и родительского текста
                                if not any(text in p for p in paragraphs[-3:]):
                                    paragraphs.append(text)

                clean_text_paragraphs = "\n\n".join(paragraphs)

                # 8. Формируем структурированный Markdown-отчет для LLM
                md_report = [
                    f"### Title:\n{final_title}\n",
                    f"### Description:\n{final_desc}\n" if final_desc else "",
                ]

                if headings:
                    md_report.append("### 🏷 Структура заголовков (H1–H4):")
                    for h in headings:
                        md_report.append(f"- **[{h['level']}]** {h['text']}")
                    md_report.append("")

                if tables_markdown:
                    md_report.append("### Таблицы и прайсы:")
                    for tbl in tables_markdown:
                        md_report.append(tbl)
                        md_report.append("")

                if clean_text_paragraphs:
                    md_report.append("---\n###  Смысловой текст страницы:\n")
                    md_report.append(clean_text_paragraphs)

                structured_raw_text = "\n".join(filter(None, md_report))

                return {
                    "url": url,
                    "title": final_title,
                    "description": final_desc,
                    "logo_url": logo_url,
                    "seo_meta": {
                        "title": final_title,
                        "description": final_desc,
                    },
                    "content_structure": {
                        "headings": headings,
                        "tables": tables_markdown,
                        "faq_blocks": faq_blocks,
                    },
                    "body_text": structured_raw_text,
                    "clean_text": clean_text_paragraphs or final_title,
                    "is_blocked": False
                }

        except Exception as e:
            logger.exception(f"[SiteParserGateway Error for {url}]: {e}")

        # Безопасный Fallback при сбое
        real_title = fallback_title or f"Сайт {domain}"
        real_desc = fallback_desc or f"Страница {domain}"

        return {
            "url": url,
            "title": real_title,
            "description": real_desc,
            "logo_url": None,
            "seo_meta": {"title": real_title, "description": real_desc},
            "content_structure": {"headings": [], "tables": [], "faq_blocks": []},
            "body_text": "",
            "clean_text": "",
            "is_blocked": True
        }

    async def _fetch_html(self, url: str, cookies: dict[str, str] | None = None) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        }
        html_text = ""

        if CURL_CFFI_AVAILABLE:
            try:
                async with AsyncSession(impersonate="chrome124") as session:
                    res = await session.get(url, timeout=15, allow_redirects=True, headers=headers, cookies=cookies)
                    if res.status_code == 200:
                        html_text = res.text
            except Exception as e:
                logger.debug(f"[curl_cffi Warning for {url}]: {e}")

        if not html_text and hasattr(self._client, "get"):
            try:
                res = await self._client.get(url, timeout=12.0, headers=headers, cookies=cookies, follow_redirects=True)
                if res.status_code == 200:
                    html_text = res.text
            except Exception as e:
                logger.debug(f"[httpx Warning for {url}]: {e}")

        return html_text