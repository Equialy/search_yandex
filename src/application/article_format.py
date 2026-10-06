import re


def has_styled_article_html(content: str) -> bool:
    """Проверяет, что ответ — HTML-статья с CSS-блоком."""
    text = (content or "").strip().lower()
    return bool(text) and "<style" in text and ("seo-article" in text or "<h1" in text)


def normalize_article_html(html_text: str) -> str:
    """Очищает HTML-ответ от markdown-обёрток, артефактов writing/canvas и мусора."""
    if not html_text:
        return ""

    text = html_text.strip()

    text = re.sub(r":::[a-zA-Z0-9_-]+(?:\{.*?\})?", "", text)
    text = re.sub(r"^:::\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r":::$", "", text).strip()

    text = re.sub(r"^```(?:html|css|xml)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    match = re.search(r"(<style\b|<div\b)", text, re.IGNORECASE)
    if match:
        text = text[match.start():]

    last_div_idx = text.rfind("</div>")
    if last_div_idx != -1:
        text = text[:last_div_idx + len("</div>")]

    return text.strip()


def strip_style_block(html: str) -> str:
    """Убирает <style> из HTML — для отдельного контекста стилизации."""
    without_style = re.sub(
        r"<style[^>]*>.*?</style>",
        "",
        html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    return re.sub(r"\n{3,}", "\n\n", without_style).strip()


def truncate_for_style_context(html: str, max_chars: int = 14000) -> str:
    """Обрезает разметку, если статья слишком длинная для vision-контекста."""
    text = (html or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n<!-- ...статья обрезана для контекста стилизации... -->"


def merge_style_with_markup(response_html: str, article_markup: str) -> str:
    """Склеивает <style> из ответа с markup, если модель вернула только CSS."""
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
    """
    Вставляет баннер/изображение сразу после h1 или первого абзаца статьи.
    Также добавляет CSS-стили для .seo-article__image, если их нет.
    """
    if not html_content or not image_url:
        return html_content

    caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
    image_tag = (
        f'\n  <figure class="seo-article__image-wrapper">\n'
        f'    <img src="{image_url}" alt="{alt_text}" class="seo-article__img" loading="lazy" />\n'
        f'    {caption_html}\n'
        f'  </figure>\n'
    )

    image_css = (
        "\n  .seo-article__image-wrapper { margin: 24px 0; text-align: center; }\n"
        "  .seo-article__img { max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }\n"
        "  .seo-article__image-wrapper figcaption { font-size: 0.85em; color: #666; margin-top: 8px; }\n"
    )

    if "</style>" in html_content:
        html_content = html_content.replace("</style>", f"{image_css}</style>", 1)

    if "</h1>" in html_content:
        return html_content.replace("</h1>", f"</h1>\n{image_tag}", 1)
    elif "</p>" in html_content:
        return html_content.replace("</p>", f"</p>\n{image_tag}", 1)

    return f"{image_tag}\n{html_content}"


# src/application/article_format.py

import re

def inject_multiple_images_to_article(
    html_content: str,
    images: list[dict[str, str]],  # [{"url": "...", "alt": "...", "caption": "..."}]
) -> str:
    """
    Распределяет список изображений по всей статье:
    - 1-е изображение: после заголовка H1 (Hero-баннер)
    - Последующие изображения: равномерно после заголовков H2
    """
    if not html_content or not images:
        return html_content

    # 1. Добавляем стили для адаптивных картинок
    image_css = """
  .seo-article__image-wrapper { margin: 28px 0; text-align: center; }
  .seo-article__img { width: 100%; max-height: 480px; object-fit: cover; border-radius: 12px; box-shadow: 0 6px 18px rgba(0,0,0,0.08); }
  .seo-article__image-wrapper figcaption { font-size: 0.85em; color: #64748b; margin-top: 8px; font-style: italic; }
"""
    if "</style>" in html_content:
        html_content = html_content.replace("</style>", f"{image_css}</style>", 1)

    def make_figure(img_item: dict[str, str]) -> str:
        caption = img_item.get("caption")
        caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
        return (
            f'\n  <figure class="seo-article__image-wrapper">\n'
            f'    <img src="{img_item["url"]}" alt="{img_item.get("alt", "")}" class="seo-article__img" loading="lazy" />\n'
            f'    {caption_html}\n'
            f'  </figure>\n'
        )

    # 2. Вставляем 1-ю картинку после H1
    if images and "</h1>" in html_content:
        hero_figure = make_figure(images[0])
        html_content = html_content.replace("</h1>", f"</h1>\n{hero_figure}", 1)
        remaining_images = images[1:]
    else:
        remaining_images = images

    if not remaining_images:
        return html_content

    # 3. Распределяем оставшиеся картинки после H2 тегов
    h2_matches = list(re.finditer(r"</h2>", html_content, flags=re.IGNORECASE))
    if not h2_matches:
        return html_content

    # Если H2 блоков несколько, вставляем с шагом (например, после 2-го и 4-го H2)
    step = max(1, len(h2_matches) // (len(remaining_images) + 1))
    offset = 0

    for i, img_data in enumerate(remaining_images, start=1):
        target_idx = min(i * step, len(h2_matches) - 1)
        match = h2_matches[target_idx]
        pos = match.end() + offset

        fig_html = make_figure(img_data)
        html_content = html_content[:pos] + fig_html + html_content[pos:]
        offset += len(fig_html)

    return html_content


def strip_existing_images(html: str) -> str:
    """Удаляет ранее вставленные теги <figure> и <img> со статьи перед повторной вставкой."""
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