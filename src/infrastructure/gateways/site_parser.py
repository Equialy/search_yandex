
import re
from typing import Any
import httpx
from bs4 import BeautifulSoup
import networkx as nx


class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client

    async def parse_site_to_graph(self, url: str) -> dict[str, Any]:
        """Глубокий коммерческий и SEO-анализ страницы конкурента."""
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

        html_text = response.text
        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Извлечение Title и Description
        title = soup.title.string.strip() if soup.title and soup.title.string else url
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag.get("content").strip()

        # 2. Поиск коммерческих сигналов (Цены, Гарантии, Реквизиты)
        prices_found = re.findall(r'\b\d[\d\s]*\s*(?:руб|₽|рублей|руб\.)\b', html_text, flags=re.IGNORECASE)
        unique_prices = list(set([p.strip() for p in prices_found]))[:8]

        has_calculator = bool(re.search(r'калькулятор|рассчит|расчет', html_text, re.IGNORECASE))
        has_quiz = bool(re.search(r'квиз|тест|подбор', html_text, re.IGNORECASE))
        has_guarantees = bool(re.search(r'гаранти|договор|возврат', html_text, re.IGNORECASE))
        has_cases = bool(re.search(r'кейс|портфолио|наши работы|выполненные', html_text, re.IGNORECASE))
        has_reviews = bool(re.search(r'отзыв|отклики|клиенты о нас', html_text, re.IGNORECASE))
        has_requisites = bool(re.search(r'ИНН|ОГРН|ООО|ИП|реквизиты', html_text, re.IGNORECASE))

        # 3. Анализ форм и CTA кнопок
        forms_count = len(soup.find_all("form"))
        cta_buttons = [
            btn.get_text(strip=True)
            for btn in soup.find_all(["button", "a"])
            if re.search(r'заказать|купить|заявк|перезвон|рассчит|узнать', btn.get_text(strip=True), re.IGNORECASE)
        ][:6]

        # 4. Анализ таблиц (Цены, Сравнения, Этапы)
        tables_data = []
        for table in soup.find_all("table")[:3]:
            rows = []
            for tr in table.find_all("tr")[:5]:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                tables_data.append("\n".join(rows))

        # 5. Перелинковка и Trust-документы (Лицензии, Сертификаты, Смежные услуги)
        trust_links = []
        related_service_links = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if not text:
                continue

            if re.search(r'лицензи|сертификат|разрешен|документ|политика', text, re.IGNORECASE):
                trust_links.append({"text": text, "href": href})
            elif re.search(r'услуг|каталог|калькулятор|стать|гаранти', text, re.IGNORECASE) and len(text) < 40:
                related_service_links.append(text)

        trust_links = trust_links[:5]
        related_service_links = list(set(related_service_links))[:8]

        # 6. Очистка HTML от скриптов/стилей для анализа текста и списков
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.extract()

        # 7. Анализ списков (UL/OL)
        lists_data = []
        for ul in soup.find_all(["ul", "ol"])[:8]:
            items = [li.get_text(strip=True) for li in ul.find_all("li") if len(li.get_text(strip=True)) > 5]
            if 2 <= len(items) <= 10:
                lists_data.append({"count": len(items), "sample_items": items[:3]})

        # 8. Извлечение H1-H4 и построение Графа
        h1_tags = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
        h1_count = len(h1_tags)
        main_h1 = h1_tags[0] if h1_tags else title

        headings = soup.find_all(["h1", "h2", "h3", "h4"])
        g = nx.DiGraph()
        g.add_node("Root", label=title)

        nodes_list = []
        current_h1, current_h2, current_h3 = "Root", "Root", "Root"

        for tag in headings:
            text = tag.get_text(strip=True)
            if not text:
                continue

            if tag.name == "h1":
                current_h1 = text
                g.add_edge("Root", current_h1)
                nodes_list.append({"level": "H1", "text": text})
            elif tag.name == "h2":
                current_h2 = text
                g.add_edge(current_h1, current_h2)
                nodes_list.append({"level": "H2", "text": text, "parent": current_h1})
            elif tag.name == "h3":
                current_h3 = text
                g.add_edge(current_h2, current_h3)
                nodes_list.append({"level": "H3", "text": text, "parent": current_h2})
            elif tag.name == "h4":
                g.add_edge(current_h3, text)
                nodes_list.append({"level": "H4", "text": text, "parent": current_h3})

        # 9. Главный текст
        paragraphs = [p.get_text(strip=True) for p in soup.find_all(["p", "div"]) if len(p.get_text(strip=True)) > 50]

        return {
            "url": url,
            "seo_meta": {
                "title": title,
                "title_length": len(title),
                "description": meta_desc,
                "description_length": len(meta_desc),
                "h1_count": h1_count,
                "main_h1": main_h1
            },
            "commercial_signals": {
                "prices": unique_prices,
                "forms_count": forms_count,
                "cta_buttons": cta_buttons,
                "has_calculator": has_calculator,
                "has_quiz": has_quiz,
                "has_guarantees": has_guarantees,
                "has_cases": has_cases,
                "has_reviews": has_reviews,
                "has_requisites": has_requisites
            },
            "trust_and_links": {
                "trust_links": trust_links,
                "related_service_links": related_service_links
            },
            "content_structure": {
                "headings_hierarchy": nodes_list,
                "tables_count": len(tables_data),
                "tables_sample": tables_data,
                "lists_count": len(lists_data),
                "lists_sample": lists_data
            },
            "content_sample": "\n".join(paragraphs[:10])[:2000]
        }