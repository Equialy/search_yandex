import re


def has_styled_article_html(content: str) -> bool:
    """Проверяет, что ответ — HTML-статья с CSS-блоком."""
    text = (content or "").strip().lower()
    return bool(text) and "<style" in text and ("seo-article" in text or "<h1" in text)


def normalize_article_html(content: str) -> str:
    """Убирает markdown-обёртки ```html и лишние пробелы из ответа LLM."""
    text = (content or "").strip()
    if not text.startswith("```"):
        return text

    text = re.sub(r"^```(?:html)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
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