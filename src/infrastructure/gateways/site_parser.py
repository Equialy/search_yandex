import json
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

_BEGET_CHALLENGE_MARKERS = ("beget=begetok", "set_cookie()", "location.reload()")

_NAV_CHROME_TAGS = frozenset({"nav", "header", "footer", "aside"})
_NAV_ROLES = frozenset({"navigation", "banner", "contentinfo", "menubar"})
_NAV_CLASS_PATTERN = re.compile(
    r"(?:^|[\s_-])(?:nav|navbar|menu|megamenu|breadcrumb|topbar|sidebar|site-nav|main-menu|header-menu|footer-menu)(?:$|[\s_-])",
    re.I,
)
_MAX_LIST_ITEM_LEN = 200
_MAX_LIST_TOTAL_LEN = 800


def _is_beget_challenge(html: str) -> bool:
    """Beget отдаёт пустую страницу с JS, который ставит cookie beget=begetok."""
    if not html or len(html) > 5000:
        return False
    lowered = html.lower()
    return all(marker.lower() in lowered for marker in _BEGET_CHALLENGE_MARKERS)


def _prepare_content_root(soup: BeautifulSoup) -> Any:
    """Копия DOM без навигации, шапки и подвала — только контент для анализа."""
    content = BeautifulSoup(str(soup), "html.parser")

    for tag_name in _NAV_CHROME_TAGS:
        for tag in content.find_all(tag_name):
            tag.decompose()

    for tag in content.find_all(attrs={"role": True}):
        role = (tag.get("role") or "").lower()
        if role in _NAV_ROLES:
            tag.decompose()

    for tag in content.find_all(class_=_NAV_CLASS_PATTERN):
        tag.decompose()

    for tag in content.find_all(id=_NAV_CLASS_PATTERN):
        tag.decompose()

    main = (
        content.find("main")
        or content.find("article")
        or content.find(attrs={"role": "main"})
    )
    return main or content.find("body") or content


def _is_navigation_list(items: list[str]) -> bool:
    if len(items) < 2:
        return True
    joined = " ".join(items)
    if len(joined) > _MAX_LIST_TOTAL_LEN:
        return True
    if any(len(item) > _MAX_LIST_ITEM_LEN for item in items):
        return True
    if len(items) <= 5 and items[0].lower() in {"главная", "home", "main"}:
        return True
    return False


class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client

    async def parse_site_to_graph(
        self,
        url: str,
        fallback_title: str = "",
        fallback_desc: str = ""
    ) -> dict[str, Any]:
        """Глубокий структурированный парсинг страницы без удаления контейнеров form/header."""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc or url

        html_text = ""

        try:
            html_text = await self._fetch_html(url)

            # Beget anti-bot: первый ответ — JS+cookie, второй с cookie — нормальная страница
            if _is_beget_challenge(html_text):
                print(f"[SiteParserGateway]: Beget challenge detected for {url}, retrying with cookie...")
                html_text = await self._fetch_html(url, cookies={"beget": "begetok"})

            # 3. Извлечение структурированного контента
            if html_text:
                soup = BeautifulSoup(html_text, "html.parser")

                # --- 3.1. Title & Meta Description ---
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
                    or soup.find("meta", attrs={"itemprop": re.compile(r"description$", re.I)})
                )
                if meta_tag and meta_tag.get("content"):
                    meta_desc = meta_tag.get("content").strip()

                final_desc = meta_desc or fallback_desc or ""

                content_root = _prepare_content_root(soup)

                # --- 3.2. Дерево Заголовков H1-H4 (без nav/header) ---
                headings = []
                for h in content_root.find_all(["h1", "h2", "h3", "h4"]):
                    h_text = h.get_text(" ", strip=True)
                    if h_text and len(h_text) > 3:
                        headings.append({"level": h.name.upper(), "text": h_text})

                # --- 3.3. Таблицы в формате Markdown ---
                tables_markdown = []
                for table in content_root.find_all("table")[:5]:
                    rows = []
                    for tr in table.find_all("tr")[:15]:
                        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                        if cells and any(c for c in cells):
                            rows.append(" | ".join(cells))
                    if rows:
                        tables_markdown.append("\n".join(rows))

                # --- 3.4. FAQ Блоки и Аккордеоны ---
                faq_blocks = []
                for details in content_root.find_all(
                    ["details", "div"],
                    class_=re.compile(r"faq|accordion|question|reply|answer", re.I),
                )[:6]:
                    q_text = details.get_text(" ", strip=True)
                    if len(q_text) > 20 and q_text not in faq_blocks:
                        faq_blocks.append(q_text)

                # --- 3.5. Списки UL/OL (контентные, без меню) ---
                lists_extracted = []
                for ul in content_root.find_all(["ul", "ol"])[:20]:
                    items = [
                        li.get_text(" ", strip=True)
                        for li in ul.find_all("li", recursive=False)
                        if len(li.get_text(" ", strip=True)) > 5
                    ]
                    if not items:
                        items = [
                            li.get_text(" ", strip=True)
                            for li in ul.find_all("li")
                            if len(li.get_text(" ", strip=True)) > 5
                        ]
                    if 2 <= len(items) <= 10 and not _is_navigation_list(items):
                        lists_extracted.append(items)
                    if len(lists_extracted) >= 8:
                        break

                # --- 3.6. Текст страницы без nav/header/footer ---
                body = content_root
                for tag in body(["script", "style", "noscript", "svg", "iframe"]):
                    tag.extract()

                unique_lines = []
                for string in body.stripped_strings:
                    clean_str = string.strip()
                    if len(clean_str) > 3 and (not unique_lines or unique_lines[-1] != clean_str):
                        unique_lines.append(clean_str)

                clean_body_text = "\n".join(unique_lines)

                # --- 3.7. Скомпонованный Markdown отчет ---
                md_report = []
                md_report.append(f"###  Title:\n{final_title}\n")
                if final_desc:
                    md_report.append(f"###  Description:\n{final_desc}\n")

                if headings:
                    md_report.append("### 🏷 Структура заголовков (H1–H4):")
                    for h in headings:
                        md_report.append(f"- **[{h['level']}]** {h['text']}")
                    md_report.append("")

                if tables_markdown:
                    md_report.append("###  Таблицы и прайсы:")
                    for tbl in tables_markdown:
                        md_report.append(tbl)
                        md_report.append("")

                if lists_extracted:
                    md_report.append("###  Списки и комплектации:")
                    for lst in lists_extracted:
                        for item in lst:
                            md_report.append(f"* {item}")
                        md_report.append("")

                if faq_blocks:
                    md_report.append("###  Вопросы и ответы (FAQ):")
                    for faq in faq_blocks:
                        md_report.append(f"> {faq}")
                    md_report.append("")

                if clean_body_text:
                    md_report.append("---\n###  Сплошной текст страницы:\n")
                    md_report.append(clean_body_text)

                structured_raw_text = "\n".join(md_report)

                if len(structured_raw_text.strip()) > 50:
                    print(f"[SiteParserGateway Success]: Скомпонован структурированный отчет ({len(structured_raw_text)} симв.) для {domain}!")
                    return {
                        "url": url,
                        "title": final_title,
                        "description": final_desc,
                        "seo_meta": {
                            "title": final_title,
                            "description": final_desc,
                        },
                        "content_structure": {
                            "headings": headings,
                            "tables": tables_markdown,
                            "lists": lists_extracted,
                            "faq_blocks": faq_blocks,
                        },
                        "body_text": structured_raw_text,
                        "is_blocked": False
                    }

        except Exception as e:
            print(f"[SiteParserGateway Exception for {url}]: {type(e).__name__} - {e}")

        # ФОЛБЕК ДЛЯ ЗАБЛОКИРОВАННЫХ СAЙТОВ
        real_title = fallback_title or f"Сайт {domain}"
        real_desc = fallback_desc or f"Страница {domain}"

        return {
            "url": url,
            "title": real_title,
            "description": real_desc,
            "seo_meta": {
                "title": real_title,
                "description": real_desc,
            },
            "content_structure": {
                "headings": [],
                "tables": [],
                "lists": [],
                "faq_blocks": [],
            },
            "body_text": "",
            "is_blocked": True
        }

    async def _fetch_html(
        self,
        url: str,
        *,
        cookies: dict[str, str] | None = None,
    ) -> str:
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
                    res = await session.get(
                        url,
                        timeout=15,
                        allow_redirects=True,
                        headers=headers,
                        cookies=cookies,
                    )
                    if res.status_code == 200:
                        html_text = res.text
            except Exception as e:
                print(f"[curl_cffi Warning for {url}]: {e}")

        if not html_text and hasattr(self._client, "get"):
            try:
                res = await self._client.get(
                    url,
                    timeout=12.0,
                    headers=headers,
                    cookies=cookies,
                    follow_redirects=True,
                )
                if res.status_code == 200:
                    html_text = res.text
            except Exception as e:
                print(f"[httpx Warning for {url}]: {e}")

        return html_text