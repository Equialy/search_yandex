import json
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

_BEGET_CHALLENGE_MARKERS = ("beget=begetok", "set_cookie()", "location.reload()")

_NAV_CHROME_TAGS = frozenset({
    "nav", "header", "footer", "aside", "form", "button",
    "script", "style", "noscript", "svg", "iframe", "dialog"
})
_NAV_ROLES = frozenset({"navigation", "banner", "contentinfo", "menubar", "dialog"})
_NAV_CLASS_PATTERN = re.compile(
    r"(?:^|[\s_-])(?:nav|navbar|menu|megamenu|breadcrumb|topbar|sidebar|site-nav|header-menu|footer|modal|popup|cookie|policy)(?:$|[\s_-])",
    re.I,
)
_GARBAGE_TEXT_PATTERN = re.compile(
    r"^(?:подробнее|отправить заявку|перезвоните мне|согласен на обработку|политика конфиденциальности|\+?\d[\d\s\-\(\)]{8,}\d)$",
    re.I
)


def _is_beget_challenge(html: str) -> bool:
    if not html or len(html) > 5000:
        return False
    lowered = html.lower()
    return all(marker.lower() in lowered for marker in _BEGET_CHALLENGE_MARKERS)


def _prepare_content_root(soup: BeautifulSoup) -> Any:
    """Очищает DOM от шапок, подвалов, форм, модалок и cookie-баннеров."""
    content = BeautifulSoup(str(soup), "html.parser")

    for tag_name in _NAV_CHROME_TAGS:
        for tag in content.find_all(tag_name):
            if isinstance(tag, Tag):
                tag.decompose()

    for tag in content.find_all(True):
        if not isinstance(tag, Tag) or not isinstance(tag.attrs, dict):
            continue

        role = str(tag.attrs.get("role", "")).lower()
        if role in _NAV_ROLES:
            tag.decompose()
            continue

        classes = tag.attrs.get("class", [])
        if isinstance(classes, list):
            class_str = " ".join(classes)
        else:
            class_str = str(classes)

        if class_str and _NAV_CLASS_PATTERN.search(class_str):
            tag.decompose()
            continue

        tag_id = str(tag.attrs.get("id", ""))
        if tag_id and _NAV_CLASS_PATTERN.search(tag_id):
            tag.decompose()
            continue

    def _is_main_role(t: Any) -> bool:
        return isinstance(t, Tag) and isinstance(t.attrs, dict) and t.attrs.get("role") == "main"

    main = (
            content.find("main")
            or content.find("article")
            or content.find(_is_main_role)
    )
    return main or content.find("body") or content

class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient ):
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

            if _is_beget_challenge(html_text):
                print(f"[SiteParserGateway]: Beget challenge detected for {url}, retrying with cookie...")
                html_text = await self._fetch_html(url, cookies={"beget": "begetok"})

            if html_text:
                soup = BeautifulSoup(html_text, "html.parser")

                logo_url = _extract_logo_url(soup, url)
                print(f"[SiteParserGateway] Extracted logo for {url} -> {logo_url}")

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

                content_root = _prepare_content_root(soup)

                headings = []
                for h in content_root.find_all(["h1", "h2", "h3", "h4"]):
                    if isinstance(h, Tag):
                        h_text = h.get_text(" ", strip=True)
                        if h_text and len(h_text) > 3:
                            headings.append({"level": h.name.upper(), "text": h_text})

                # 4. Таблицы с правильной Markdown-разметкой
                tables_markdown = []
                for table in content_root.find_all("table")[:6]:
                    if not isinstance(table, Tag):
                        continue
                    rows = []
                    header_cells_count = 0
                    for tr_idx, tr in enumerate(table.find_all("tr")[:20]):
                        if not isinstance(tr, Tag):
                            continue
                        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"]) if isinstance(td, Tag)]
                        if cells and any(c for c in cells):
                            rows.append(" | ".join(cells))
                            if tr_idx == 0:
                                header_cells_count = len(cells)
                                rows.append(" | ".join(["---"] * header_cells_count))
                    if rows:
                        tables_markdown.append("\n".join(rows))

                # 5. FAQ Аккордеоны
                faq_blocks = []
                for details in content_root.find_all(
                    ["details", "div"],
                    class_=re.compile(r"faq|accordion|question|reply|answer", re.I),
                )[:6]:
                    if isinstance(details, Tag):
                        q_text = details.get_text(" ", strip=True)
                        if len(q_text) > 20 and q_text not in faq_blocks:
                            faq_blocks.append(q_text)

                # 6. Извлечение чистого текста по абзацам
                paragraphs = []
                for elem in content_root.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "span"]):
                    if isinstance(elem, Tag):
                        text = elem.get_text(" ", strip=True)
                        if len(text) > 25 and not _GARBAGE_TEXT_PATTERN.match(text):
                            if not paragraphs or paragraphs[-1] != text:
                                paragraphs.append(text)

                clean_text_paragraphs = "\n\n".join(paragraphs)

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
            import traceback
            print(f"[SiteParserGateway Exception for {url}]: {type(e).__name__} - {e}")
            traceback.print_exc()

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
                print(f"[curl_cffi Warning for {url}]: {e}")

        if not html_text and hasattr(self._client, "get"):
            try:
                res = await self._client.get(url, timeout=12.0, headers=headers, cookies=cookies, follow_redirects=True)
                if res.status_code == 200:
                    html_text = res.text
            except Exception as e:
                print(f"[httpx Warning for {url}]: {e}")

        return html_text