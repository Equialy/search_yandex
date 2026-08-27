import io
import re

from PIL import Image
from bs4 import BeautifulSoup, Tag


def extract_html_metadata(html_content: str, fallback_title: str) -> tuple[str, str, str]:
    """Извлекает H1, Title и Description из сгенерированного HTML."""
    h1_text = fallback_title
    title_text = fallback_title
    desc_text = ""

    if not html_content:
        return h1_text, title_text, desc_text

    # 1. Извлечение H1
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, flags=re.IGNORECASE | re.DOTALL)
    if h1_match:
        h1_text = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()

    # 2. Извлечение Title и Description из блока .seo-article__meta
    title_match = re.search(r"<strong>Title:</strong>\s*(.*?)</p>", html_content, flags=re.IGNORECASE | re.DOTALL)
    if title_match:
        title_text = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()

    desc_match = re.search(r"<strong>Description:</strong>\s*(.*?)</p>", html_content, flags=re.IGNORECASE | re.DOTALL)
    if desc_match:
        desc_text = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip()

    return h1_text, title_text, desc_text




from urllib.parse import urljoin, urlparse


def _extract_logo_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Гарантированно находит логотип сайта."""
    if not soup:
        return None

    try:
        # 1. Поиск по ссылкам логотипа (как на твоем скриншоте: a.isar-logo-link > img)
        for a_tag in soup.find_all("a", class_=re.compile(r"logo|brand|home", re.I)):
            img = a_tag.find("img")
            if isinstance(img, Tag):
                src = img.get("src") or img.get("data-src")
                if src and isinstance(src, str):
                    return urljoin(base_url, src.strip())

        # 2. Поиск картинок с классом logo / brand (как .isar-logo-img)
        for img in soup.find_all("img", class_=re.compile(r"logo|brand|header", re.I)):
            src = img.get("src") or img.get("data-src")
            if src and isinstance(src, str):
                return urljoin(base_url, src.strip())

        # 3. Поиск любого img со словом logo в src или alt (например, logo_matrix_white.png)
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            alt = img.get("alt") or ""
            full_str = f"{src} {alt}".lower()
            if "logo" in full_str or "логотип" in full_str:
                if not any(exc in full_str for exc in ["icon", "social", "flag"]):
                    return urljoin(base_url, str(src).strip())

        # 4. Поиск в шапке (первая адекватная картинка в header)
        header = soup.find("header") or soup.find(class_=re.compile(r"header|top", re.I))
        if header and isinstance(header, Tag):
            for img in header.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if src and isinstance(src, str):
                    return urljoin(base_url, src.strip())

        # 5. OpenGraph
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if isinstance(og, Tag) and og.get("content"):
            return urljoin(base_url, str(og["content"]).strip())

    except Exception as e:
        print(f"[Logo Error]: {e}")

    return None



def _prepare_image_png_bytes(raw_bytes: bytes) -> bytes:
    """Конвертирует изображение в валидный PNG RGBA формат для OpenAI API."""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        out = io.BytesIO()
        img.convert("RGBA").save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return raw_bytes
