import io
import re
from urllib.parse import urljoin
from PIL import Image
from bs4 import BeautifulSoup, Tag
try:
    from resvg_py import svg_to_bytes
    RESVG_AVAILABLE = True
except ImportError:
    RESVG_AVAILABLE = False

_EXCLUDE_KEYWORDS = ("icon", "social", "flag", "pixel", "counter", "banner", "avatar")


def extract_html_metadata(html_content: str, fallback_title: str) -> tuple[str, str, str]:
    """Извлекает H1, Title и Description из сгенерированного HTML."""
    h1_text = fallback_title
    title_text = fallback_title
    desc_text = ""

    if not html_content:
        return h1_text, title_text, desc_text

    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, flags=re.IGNORECASE | re.DOTALL)
    if h1_match:
        h1_text = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()

    title_match = re.search(r"(?:<strong>|<b>)?Title:?(?:</strong>|</b>)?\s*(.*?)(?:</p>|</div>|\n)", html_content, flags=re.IGNORECASE | re.DOTALL)
    if title_match:
        title_text = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()

    desc_match = re.search(r"(?:<strong>|<b>)?Description:?(?:</strong>|</b>)?\s*(.*?)(?:</p>|</div>|\n)", html_content, flags=re.IGNORECASE | re.DOTALL)
    if desc_match:
        desc_text = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip()

    return h1_text, title_text, desc_text


def remove_meta_block_from_html(html_content: str) -> str:
    """Удаляет блок .seo-article__meta и его CSS-класс из HTML-разметки."""
    if not html_content:
        return html_content

    # Удаляем сам блок div с метатегами
    cleaned = re.sub(
        r'<div[^>]*class=["\'][^"\']*seo-article__meta[^"\']*["\'][^>]*>.*?</div>',
        "",
        html_content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Удаляем упоминания стилей .seo-article__meta { ... }
    cleaned = re.sub(
        r'\.seo-article__meta\s*\{[^}]*\}',
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return cleaned.strip()


def _get_img_src(img_tag: Tag) -> str | None:
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        src = img_tag.get(attr)
        if src and isinstance(src, str) and not src.startswith("data:image"):
            return src.strip()
    return None


def _extract_logo_url(soup: BeautifulSoup, base_url: str) -> str | None:
    if not soup:
        return None
    try:
        header = soup.find("header") or soup.find(class_=re.compile(r"header|topbar|navbar", re.I))
        search_scopes = [header, soup] if header else [soup]

        for scope in search_scopes:
            if not scope or not isinstance(scope, Tag):
                continue

            for a_tag in scope.find_all("a", class_=re.compile(r"logo|brand|home", re.I)):
                if isinstance(a_tag, Tag):
                    img = a_tag.find("img")
                    if isinstance(img, Tag):
                        src = _get_img_src(img)
                        if src:
                            return urljoin(base_url, src)

            for img in scope.find_all("img", class_=re.compile(r"logo|brand", re.I)) + \
                       scope.find_all("img", id=re.compile(r"logo|brand", re.I)):
                if isinstance(img, Tag):
                    src = _get_img_src(img)
                    if src and not any(k in src.lower() for k in _EXCLUDE_KEYWORDS):
                        return urljoin(base_url, src)

            for img in scope.find_all("img"):
                if isinstance(img, Tag):
                    src = _get_img_src(img)
                    alt = str(img.get("alt", "")).lower()
                    if src:
                        full_str = f"{src.lower()} {alt}"
                        if ("logo" in full_str or "логотип" in full_str) and not any(k in full_str for k in _EXCLUDE_KEYWORDS):
                            return urljoin(base_url, src)

        og = soup.find("meta", property=re.compile(r"og:image", re.I)) or \
             soup.find("meta", attrs={"name": re.compile(r"og:image", re.I)})
        if isinstance(og, Tag) and og.get("content"):
            return urljoin(base_url, str(og["content"]).strip())

    except Exception as e:
        print(f"[Logo Extract Error]: {e}")

    return None

def _prepare_image_png_bytes(raw_bytes: bytes, target_size: int = 1024) -> bytes:
    """
    Приводит любое изображение логотипа к строгому стандарту OpenAI images/edits:
    - Конвертирует в RGBA PNG
    - Вписывает прямоугольный логотип по центру квадратного прозрачного холста (target_size x target_size)
    - Гарантирует правильный формат без искажения пропорций
    """
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img = img.convert("RGBA")
            orig_w, orig_h = img.size

            max_logo_dimension = int(target_size * 0.75)
            scale = min(max_logo_dimension / orig_w, max_logo_dimension / orig_h)
            new_w = max(1, int(orig_w * scale))
            new_h = max(1, int(orig_h * scale))

            resized_logo = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            square_canvas = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))

            offset_x = (target_size - new_w) // 2
            offset_y = (target_size - new_h) // 2
            square_canvas.paste(resized_logo, (offset_x, offset_y), mask=resized_logo.split()[-1])

            out = io.BytesIO()
            square_canvas.save(out, format="PNG", optimize=True)
            return out.getvalue()

    except Exception as e:
        print(f"[Prepare Image Bytes Error]: {e}")
        return raw_bytes


def convert_svg_to_png_bytes(svg_data: bytes | str, target_width: int = 1024) -> bytes:
    """Конвертирует SVG-код в валидный бинарный PNG через resvg_py."""
    if not RESVG_AVAILABLE or not svg_data:
        return svg_data if isinstance(svg_data, bytes) else svg_data.encode("utf-8")

    try:
        # resvg_py ожидает str на вход
        if isinstance(svg_data, bytes):
            svg_str = svg_data.decode("utf-8", errors="ignore")
        else:
            svg_str = str(svg_data)

        # Выполняем рендер в PNG
        png_bytes = svg_to_bytes(svg_str, width=target_width)
        if png_bytes and len(png_bytes) > 50:
            return bytes(png_bytes)

    except Exception as e:
        print(f"[resvg_py Error]: {e}")

    # Фолбек, если что-то пошло не так
    return svg_data if isinstance(svg_data, bytes) else svg_data.encode("utf-8")


def normalize_logo_png(raw_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = img.convert("RGBA")
        # Создаем темную подложку чтобы белый логотип стал виден
        background = Image.new("RGB", img.size, (20, 20, 20))
        background.paste(img, mask=img.split()[-1])
        out = io.BytesIO()
        background.save(out, format="PNG")
        return out.getvalue()