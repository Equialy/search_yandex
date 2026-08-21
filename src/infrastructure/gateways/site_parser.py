import json
import re
from typing import Any
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup, Tag

try:
    from curl_cffi.requests import AsyncSession

    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

_BEGET_CHALLENGE_MARKERS = ("beget=begetok", "set_cookie()", "location.reload()")

_NAV_CHROME_TAGS = frozenset({"nav", "header", "footer", "aside"})
_NAV_ROLES = frozenset({"navigation", "banner", "contentinfo", "menubar"})

_NAV_CLASS_PATTERN = re.compile(
    r"(?:^|\s)(?:navbar|megamenu|breadcrumb|breadcrumbs|topbar|main-menu|header-menu|footer-menu|mobile-header)(?:\s|$)",
    re.I,
)

_PRODUCT_CONTAINER_CLASSES = re.compile(
    r"product|catalog|item-product|hikashop_product|goods|shop-item",
    re.I,
)


def _is_beget_challenge(html: str) -> bool:
    """Beget отдаёт пустую страницу с JS, который ставит cookie beget=begetok."""
    if not html or len(html) > 5000:
        return False
    lowered = html.lower()
    return all(marker.lower() in lowered for marker in _BEGET_CHALLENGE_MARKERS)


def _prepare_content_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    """Копия DOM без навигации, шапки и подвала — только контент для анализа."""
    content = BeautifulSoup(str(soup), "html.parser")

    # 1. Удаляем явные теги шапок/навигации
    for tag_name in _NAV_CHROME_TAGS:
        for tag in content.find_all(tag_name):
            tag.decompose()

    # 2. Удаляем блоки по ARIA-ролям навигации
    for tag in content.find_all(attrs={"role": True}):
        role = (tag.get("role") or "").lower()
        if role in _NAV_ROLES and role != "main":
            tag.decompose()

    # 3. Удаляем меню и навигацию по классам (не трогая товарные контейнеры)
    for tag in content.find_all(class_=_NAV_CLASS_PATTERN):
        classes = " ".join(tag.get("class", []))
        if not _PRODUCT_CONTAINER_CLASSES.search(classes):
            tag.decompose()

    main = (
            content.find("main")
            or content.find("article")
            or content.find(attrs={"role": "main"})
            or content.find(class_=re.compile(r"content|main-content|fon-write", re.I))
    )
    return main or content.find("body") or content


def _is_navigation_list(ul_tag: Tag, items: list[str]) -> bool:
    """
    Навигационный список обычно состоит почти целиком из коротких ссылок <a>
    ('Главная', 'Контакты' и т.д.). Списки характеристик и описаний — контентные.
    """
    if len(items) < 2:
        return True

    # Проверяем, являются ли пункты преимущественно ссылками навигации
    links = ul_tag.find_all("a")
    if len(links) >= len(items) * 0.8:
        # Если все пункты короткие ссылки — это меню навигации
        avg_len = sum(len(i) for i in items) / len(items)
        if avg_len < 30 and any(
                i.lower() in {"главная", "home", "о компании", "контакты", "доставка", "акции", "корзина"} for i in
                items):
            return True

    return False


def _extract_products(content_root: Tag | BeautifulSoup, base_url: str = "") -> list[dict[str, Any]]:
    """Извлекает структурированную информацию о товарах (HikaShop, Schema.org, WooCommerce и др.)."""
    products = []

    # Поиск контейнеров товаров
    prod_elements = content_root.find_all(
        lambda tag: tag.name in ["div", "li", "article"] and (
                tag.get("itemtype") in ["http://schema.org/Product", "http://schema.org/ItemList",
                                        "https://schema.org/Product"]
                or any(
            "hikashop_product" in cls or "product-item" in cls or "product-card" in cls for cls in tag.get("class", []))
        )
    )

    seen_names = set()

    for el in prod_elements:
        # 1. Название товара
        name_el = (
                el.find(class_=re.compile(r"product_name|product-title|title", re.I))
                or el.find(["h2", "h3", "h4"])
                or el.find(attrs={"itemprop": "name"})
        )
        name = name_el.get_text(" ", strip=True) if name_el else ""
        if not name or len(name) < 2 or name in seen_names:
            continue

        seen_names.add(name)

        # 2. Цена товара
        price_el = (
                el.find(class_=re.compile(r"price|product_price|cost", re.I))
                or el.find(attrs={"itemprop": "price"})
        )
        price = price_el.get_text(" ", strip=True) if price_el else ""

        # 3. Ссылка на товар
        link_el = el.find("a", href=True)
        link = urljoin(base_url, link_el["href"]) if link_el else ""

        # 4. Описание и характеристики
        desc_el = (
                el.find(class_=re.compile(r"product_desc|description|specs|details", re.I))
                or el.find(attrs={"itemprop": "description"})
        )

        specs = []
        short_desc = ""
        if desc_el:
            # Извлекаем пункты списков внутри товара
            for li in desc_el.find_all("li"):
                txt = li.get_text(" ", strip=True)
                if len(txt) > 3:
                    specs.append(txt)

            # Текст без списков
            paragraphs = [p.get_text(" ", strip=True) for p in desc_el.find_all(["p", "div", "span"]) if
                          p.get_text(strip=True)]
            short_desc = " ".join(paragraphs[:3]) if paragraphs else desc_el.get_text(" ", strip=True)
            short_desc = re.sub(r"\s+", " ", short_desc)[:400]

        products.append({
            "name": name,
            "price": price,
            "url": link,
            "description": short_desc,
            "specs": specs[:15],  # ключевые характеристики
        })

    return products


class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client

    async def parse_site_to_graph(
            self,
            url: str,
            fallback_title: str = "",
            fallback_desc: str = ""
    ) -> dict[str, Any]:
        """Глубокий структурированный парсинг страницы (включая каталоги и списки товаров)."""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc or url

        html_text = ""

        try:
            html_text = await self._fetch_html(url)

            # Beget anti-bot: первый ответ — JS+cookie, второй с cookie — нормальная страница
            if _is_beget_challenge(html_text):
                print(f"[SiteParserGateway]: Beget challenge detected for {url}, retrying with cookie...")
                html_text = await self._fetch_html(url, cookies={"beget": "begetok"})

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

                # --- 3.2. Извлечение товаров каталога ---
                products = _extract_products(content_root, base_url=url)

                # --- 3.3. Дерево Заголовков H1-H4 ---
                headings = []
                for h in content_root.find_all(["h1", "h2", "h3", "h4"]):
                    h_text = h.get_text(" ", strip=True)
                    if h_text and len(h_text) > 3:
                        headings.append({"level": h.name.upper(), "text": h_text})

                # --- 3.4. Таблицы в формате Markdown ---
                tables_markdown = []
                for table in content_root.find_all("table")[:10]:
                    rows = []
                    for tr in table.find_all("tr")[:25]:
                        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                        if cells and any(c for c in cells):
                            rows.append(" | ".join(cells))
                    if rows:
                        tables_markdown.append("\n".join(rows))

                # --- 3.5. FAQ Блоки и Аккордеоны ---
                faq_blocks = []
                for details in content_root.find_all(
                        ["details", "div"],
                        class_=re.compile(r"faq|accordion|question|reply|answer", re.I),
                )[:10]:
                    q_text = details.get_text(" ", strip=True)
                    if len(q_text) > 20 and q_text not in faq_blocks:
                        faq_blocks.append(q_text)

                # --- 3.6. Списки UL/OL (характеристики, опции, преимущества) ---
                lists_extracted = []
                for ul in content_root.find_all(["ul", "ol"])[:40]:
                    items = [
                        li.get_text(" ", strip=True)
                        for li in ul.find_all("li")
                        if len(li.get_text(" ", strip=True)) > 3
                    ]
                    # Проверяем, что это список контента, а не меню сайта
                    if len(items) >= 2 and not _is_navigation_list(ul, items):
                        lists_extracted.append(items)
                    if len(lists_extracted) >= 25:
                        break

                # --- 3.7. Текст страницы ---
                body = content_root
                for tag in body(["script", "style", "noscript", "svg", "iframe", "button"]):
                    tag.extract()

                unique_lines = []
                for string in body.stripped_strings:
                    clean_str = string.strip()
                    if len(clean_str) > 3 and (not unique_lines or unique_lines[-1] != clean_str):
                        unique_lines.append(clean_str)

                clean_body_text = "\n".join(unique_lines)

                # --- 3.8. Скомпонованный Markdown отчет для генератора статей ---
                md_report = []
                md_report.append(f"###  Title:\n{final_title}\n")
                if final_desc:
                    md_report.append(f"###  Description:\n{final_desc}\n")

                # Блок товаров (если страница является каталогом)
                if products:
                    md_report.append("### 🛍 Товары в категории / Каталог:")
                    for p in products:
                        price_info = f" — **{p['price']}**" if p['price'] else ""
                        md_report.append(f"####  {p['name']}{price_info}")
                        if p['description']:
                            md_report.append(f"*{p['description']}*")
                        if p['specs']:
                            for spec in p['specs']:
                                md_report.append(f"  - {spec}")
                        md_report.append("")

                if headings:
                    md_report.append("### Структура заголовков (H1–H4):")
                    for h in headings:
                        md_report.append(f"- **[{h['level']}]** {h['text']}")
                    md_report.append("")

                if lists_extracted:
                    md_report.append("### Характеристики, комплектации и особенности:")
                    for lst in lists_extracted:
                        for item in lst:
                            md_report.append(f"* {item}")
                        md_report.append("")

                if tables_markdown:
                    md_report.append("### Таблицы и прайсы:")
                    for tbl in tables_markdown:
                        md_report.append(tbl)
                        md_report.append("")

                if faq_blocks:
                    md_report.append("###Вопросы и ответы (FAQ):")
                    for faq in faq_blocks:
                        md_report.append(f"> {faq}")
                    md_report.append("")

                if clean_body_text:
                    md_report.append("---\n### Сплошной текст страницы:\n")
                    md_report.append(clean_body_text)

                structured_raw_text = "\n".join(md_report)

                if len(structured_raw_text.strip()) > 50:
                    print(
                        f"[SiteParserGateway Success]: Скомпонован структурированный отчет ({len(structured_raw_text)} симв., найдено товаров: {len(products)}) для {domain}!")
                    return {
                        "url": url,
                        "title": final_title,
                        "description": final_desc,
                        "seo_meta": {
                            "title": final_title,
                            "description": final_desc,
                        },
                        "products": products,
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

        # ФОЛБЕК
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
            "products": [],
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
