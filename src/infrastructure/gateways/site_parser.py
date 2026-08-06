from typing import Any
import httpx

from bs4 import BeautifulSoup
import networkx as nx


class SiteParserGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client

    async def parse_site_to_graph(self, url: str) -> dict[str, Any]:
        """Парсит H1-H3 и строит графовую иерархию контента с помощью NetworkX."""
        try:
            response = await self._client.get(url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                return {}
        except Exception:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.extract()

        title = soup.title.string.strip() if soup.title and soup.title.string else url

        # Строим граф структуры с помощью NetworkX
        g = nx.DiGraph()
        g.add_node("Root", label=title)

        headings = soup.find_all(["h1", "h2", "h3"])
        current_h1, current_h2 = "Root", "Root"
        nodes_list = []

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
                g.add_edge(current_h2, text)
                nodes_list.append({"level": "H3", "text": text, "parent": current_h2})

        # Главные абзацы
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 50]

        return {
            "url": url,
            "title": title,
            "graph": {
                "nodes_count": g.number_of_nodes(),
                "edges_count": g.number_of_edges(),
                "hierarchy": nodes_list
            },
            "content_sample": "\n".join(paragraphs[:8])
        }