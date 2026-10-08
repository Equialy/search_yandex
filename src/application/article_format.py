
import re

DEFAULT_ARTICLE_STYLE = """<style>
  .seo-article { font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.75; color: #1e293b; max-width: 980px; margin: 0 auto; padding: 32px 24px; background: #fff; font-size: 17px; }
  .seo-article h1 { font-size: 2.2em; font-weight: 800; margin: 0 0 24px; color: #0f172a; line-height: 1.25; }
  .seo-article h2 { font-size: 1.6em; font-weight: 700; margin: 44px 0 18px; color: #1e293b; border-bottom: 2px solid #f1f5f9; padding-bottom: 10px; line-height: 1.3; }
  .seo-article h3 { font-size: 1.25em; font-weight: 600; margin: 28px 0 12px; color: #334155; line-height: 1.35; }
  .seo-article p { margin: 0 0 18px; font-size: 1em; color: #334155; }
  .seo-article ul, .seo-article ol { margin: 0 0 24px; padding-left: 28px; }
  .seo-article li { margin-bottom: 8px; color: #334155; }
  .seo-article strong { color: #0f172a; font-weight: 700; }
  .seo-article a { color: #2563eb; text-decoration: underline; }
  .seo-article a:hover { color: #1d4ed8; }
  .seo-article__table { width: 100%; border-collapse: collapse; margin: 28px 0; font-size: 15px; }
  .seo-article__table th, .seo-article__table td { border: 1px solid #e2e8f0; padding: 12px 16px; text-align: left; vertical-align: top; }
  .seo-article__table thead th { background: #f8fafc; font-weight: 700; color: #0f172a; }
  .seo-article__table tbody tr:nth-child(even) { background: #f8fafc; }
  .seo-article__image-wrapper { margin: 32px 0; text-align: center; }
  .seo-article__img { width: 100%; max-height: 480px; object-fit: cover; border-radius: 12px; box-shadow: 0 6px 20px rgba(0,0,0,0.07); }
  .seo-article__image-wrapper figcaption { font-size: 0.88em; color: #64748b; margin-top: 8px; font-style: italic; }
</style>"""


def has_styled_article_html(content: str) -> bool:
    text = (content or "").strip().lower()
    return bool(text) and "<style" in text and ("seo-article" in text or "<h1" in text or "<div" in text)


def normalize_article_html(html_text: str) -> str:
    if not html_text:
        return ""
    text = html_text.strip()
    text = re.sub(r":::writing\{[^}]*\}", "", text, flags=re.IGNORECASE)
    text = re.sub(r":::[a-zA-Z0-9_-]+(?:\{.*?\})?", "", text)
    text = re.sub(r"^:::\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```(?:html|css|xml)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    return text.strip()


def _is_complete_html(text: str) -> bool:
    """Проверяет, прислала ли модель готовую верстку (как Gemini)."""
    lower = text.lower()
    has_style = "<style" in lower
    has_headings = "<h1" in lower and "<h2" in lower
    has_paragraphs = lower.count("<p") >= 5
    has_container = 'class="seo-article"' in lower or "class='seo-article'" in lower
    return has_style and has_headings and has_paragraphs and has_container


def ensure_semantic_html(raw_content: str, topic: str) -> str:
    """
    Если модель (Gemini) УЖЕ прислала готовый валидный HTML со стилями — сохраняет его без искажений.
    Если пришел голый текст — структурирует его.
    """
    if not raw_content:
        return ""

    text = normalize_article_html(raw_content)

    # 1. ЕСЛИ ЭТО УЖЕ ГОТОВЫЙ HTML (КАК У GEMINI) — НЕ ТРОГАЕМ И НЕ ЛОМАЕМ ТАБЛИЦЫ
    if _is_complete_html(text):
        # Удаляем дублирующиеся обертки если есть
        text = re.sub(r"<p>\s*<div", "<div", text, flags=re.IGNORECASE)
        text = re.sub(r"</div>\s*</p>", "</div>", text, flags=re.IGNORECASE)
        return text

    # 2. ФОЛБЭК: восстанавливаем только если модель отдала сырой текст
    style_match = re.search(r"<style[^>]*>.*?</style>", text, flags=re.DOTALL | re.IGNORECASE)
    if style_match:
        style_block = style_match.group(0)
        body = text[style_match.end():].strip()
    else:
        style_block = DEFAULT_ARTICLE_STYLE
        body = text

    body = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', body)

    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
    formatted_blocks = []
    h1_added = False

    for block in blocks:
        if re.match(r"^(title|description):", block, re.I):
            continue

        lines = [l.strip() for l in block.split("\n") if l.strip()]

        # Если блок уже содержит HTML (div, table, ul, ol) — не заворачиваем в <p>!
        if block.startswith(("<div", "<table", "<ul", "<ol", "<figure")):
            formatted_blocks.append(block)
            continue

        first_line = lines[0]
        if first_line.startswith("### "):
            clean_title = re.sub(r"^#+\s*", "", first_line)
            formatted_blocks.append(f"  <h3>{clean_title}</h3>")
            if len(lines) > 1:
                formatted_blocks.append(f"  <p>{' '.join(lines[1:])}</p>")
            continue

        if first_line.startswith("## "):
            clean_title = re.sub(r"^#+\s*", "", first_line)
            formatted_blocks.append(f"  <h2>{clean_title}</h2>")
            if len(lines) > 1:
                formatted_blocks.append(f"  <p>{' '.join(lines[1:])}</p>")
            continue

        if first_line.startswith("# "):
            clean_title = re.sub(r"^#+\s*", "", first_line)
            formatted_blocks.append(f"  <h1>{clean_title}</h1>")
            h1_added = True
            if len(lines) > 1:
                formatted_blocks.append(f"  <p>{' '.join(lines[1:])}</p>")
            continue

        # Одиночные строки
        if len(lines) == 1:
            line = lines[0]
            line = re.sub(r"(<h[1-3][^>]*>)\s*#+\s*", r"\1", line)
            if line.startswith("<"):
                formatted_blocks.append(f"  {line}")
                continue

            if not h1_added and len(line) < 130 and not line.endswith((".", "!", "?")):
                formatted_blocks.append(f"  <h1>{line}</h1>")
                h1_added = True
                continue

            if len(line) < 100 and not line.endswith((".", "!", "?", ";", ":")):
                formatted_blocks.append(f"  <h2>{line}</h2>")
                continue

            formatted_blocks.append(f"  <p>{line}</p>")
            continue

        # Обычный абзац
        merged_p = " ".join(lines)
        if merged_p.strip():
            formatted_blocks.append(f"  <p>{merged_p}</p>")

    if not h1_added:
        formatted_blocks.insert(0, f"  <h1>{topic}</h1>")

    article_html = f'<div class="seo-article">\n' + "\n".join(formatted_blocks) + "\n</div>"
    return f"{style_block}\n\n{article_html}"


def inject_multiple_images_to_article(
    html_content: str,
    images: list[dict[str, str]],
) -> str:
    """Равномерно распределяет список картинок по статье."""
    if not html_content or not images:
        return html_content

    def make_figure(img_item: dict[str, str]) -> str:
        caption = img_item.get("caption")
        caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
        return (
            f'\n  <figure class="seo-article__image-wrapper">\n'
            f'    <img src="{img_item["url"]}" alt="{img_item.get("alt", "")}" class="seo-article__img" loading="lazy" />\n'
            f'    {caption_html}\n'
            f'  </figure>\n'
        )

    # Вставляем Hero-картинку после первого </h1>
    hero_figure = make_figure(images[0])
    remaining_images = images[1:]

    if "</h1>" in html_content:
        html_content = html_content.replace("</h1>", f"</h1>\n{hero_figure}", 1)
    elif "</p>" in html_content:
        html_content = html_content.replace("</p>", f"</p>\n{hero_figure}", 1)
    else:
        html_content = hero_figure + "\n" + html_content

    if not remaining_images:
        return html_content

    # Вставляем остальные картинки после <h2>
    h2_matches = list(re.finditer(r"</h2>", html_content, flags=re.IGNORECASE))
    if h2_matches:
        step = max(1, len(h2_matches) // (len(remaining_images) + 1))
        offset = 0
        for i, img_data in enumerate(remaining_images, start=1):
            target_idx = min(i * step, len(h2_matches) - 1)
            pos = h2_matches[target_idx].end() + offset
            fig_html = make_figure(img_data)
            html_content = html_content[:pos] + fig_html + html_content[pos:]
            offset += len(fig_html)

    return html_content


def strip_existing_images(html: str) -> str:
    if not html:
        return ""
    cleaned = re.sub(
        r'<figure[^>]*class="[^"]*seo-article__image-wrapper[^"]*"[^>]*>.*?</figure>',
        '',
        html,
        flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(
        r'<img[^>]*class="[^"]*seo-article__img[^"]*"[^>]*>',
        '',
        cleaned,
        flags=re.IGNORECASE
    )
    return cleaned


def strip_style_block(html: str) -> str:
    without_style = re.sub(
        r"<style[^>]*>.*?</style>",
        "",
        html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    return re.sub(r"\n{3,}", "\n\n", without_style).strip()


def truncate_for_style_context(html: str, max_chars: int = 14000) -> str:
    text = (html or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n<!-- ...статья обрезана для контекста стилизации... -->"


def merge_style_with_markup(response_html: str, article_markup: str) -> str:
    response = (response_html or "").strip()
    markup = (article_markup or "").strip()
    if not response:
        return markup
    if not markup:
        return response

    lower = response.lower()
    if "<h1" in lower or 'class="seo-article"' in lower or "class='seo-article'" in lower:
        return response

    style_match = re.search(r"<style[^>]*>.*?</style>", response, flags=re.DOTALL | re.IGNORECASE)
    if style_match:
        return f"{style_match.group(0)}\n{markup}"
    return response


def inject_image_to_article(
        html_content: str,
        image_url: str,
        alt_text: str,
        caption: str | None = None
) -> str:
    if not html_content or not image_url:
        return html_content

    caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
    image_tag = (
        f'\n  <figure class="seo-article__image-wrapper">\n'
        f'    <img src="{image_url}" alt="{alt_text}" class="seo-article__img" loading="lazy" />\n'
        f'    {caption_html}\n'
        f'  </figure>\n'
    )

    if "</h1>" in html_content:
        return html_content.replace("</h1>", f"</h1>\n{image_tag}", 1)
    elif "</p>" in html_content:
        return html_content.replace("</p>", f"</p>\n{image_tag}", 1)

    return f"{image_tag}\n{html_content}"