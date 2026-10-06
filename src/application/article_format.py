# src/application/article_format.py

import re


def has_styled_article_html(content: str) -> bool:
    """Проверяет, что ответ — HTML-статья с CSS-блоком."""
    text = (content or "").strip().lower()
    return bool(text) and "<style" in text and ("seo-article" in text or "<h1" in text or "<div" in text)


def normalize_article_html(html_text: str) -> str:
    """Очищает HTML-ответ от markdown-обёрток, артефактов Canvas (:::writing) и мусора."""
    if not html_text:
        return ""

    text = html_text.strip()

    # Срезаем артефакты Canvas / writing
    text = re.sub(r":::writing\{[^}]*\}", "", text, flags=re.IGNORECASE)
    text = re.sub(r":::[a-zA-Z0-9_-]+(?:\{.*?\})?", "", text)
    text = re.sub(r"^:::\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r":::$", "", text).strip()

    # Срезаем markdown codeblocks
    text = re.sub(r"^```(?:html|css|xml)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

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
    """Вставляет одиночное изображение сразу после h1 или первого абзаца."""
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

    if "</style>" in html_content and ".seo-article__image-wrapper" not in html_content:
        html_content = html_content.replace("</style>", f"{image_css}</style>", 1)

    if "</h1>" in html_content:
        return html_content.replace("</h1>", f"</h1>\n{image_tag}", 1)
    elif "</p>" in html_content:
        return html_content.replace("</p>", f"</p>\n{image_tag}", 1)

    return f"{image_tag}\n{html_content}"


def ensure_semantic_html(raw_content: str, topic: str) -> str:
    """
    Превращает текст Canvas/документа в строгий HTML
    с тегами <div class="seo-article">, <h1>, <h2>, <p> и <ul>.
    """
    if not raw_content:
        return ""

    text = normalize_article_html(raw_content)

    # 1. Извлекаем блок <style>
    style_block = ""
    style_match = re.search(r"<style[^>]*>.*?</style>", text, flags=re.DOTALL | re.IGNORECASE)
    if style_match:
        style_block = style_match.group(0)
        body = text[style_match.end():].strip()
    else:
        body = text

    # Если уже есть теги <p> и заголовки — не ломаем, просто упаковываем в div
    if body.count("<p>") >= 6 and ("<h1" in body or "<h2" in body):
        if not body.strip().startswith("<div"):
            body = f'<div class="seo-article">\n{body}\n</div>'
        return f"{style_block}\n{body}" if style_block else body

    # 2. Форматируем сырые блоки
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
    formatted_html_blocks = []
    h1_added = False

    for block in blocks:
        # Пропускаем сырые метатеги
        if re.match(r"^(title|description):", block, re.I):
            continue

        lines = [l.strip() for l in block.split("\n") if l.strip()]

        # Списки
        is_list = all(re.match(r"^(?:[\u2022\-\—\*\+]|\d+[\.\)])\s+", l) for l in lines) and len(lines) > 1
        if is_list:
            items_html = []
            for l in lines:
                clean_item = re.sub(r"^(?:[\u2022\-\—\*\+]|\d+[\.\)])\s*", "", l)
                items_html.append(f"    <li>{clean_item}</li>")
            formatted_html_blocks.append("  <ul>\n" + "\n".join(items_html) + "\n  </ul>")
            continue

        # Одиночные строки (заголовки или абзацы)
        if len(lines) == 1:
            line = lines[0]
            if line.startswith("<"):
                formatted_html_blocks.append(f"  {line}")
                continue

            if not h1_added and len(line) < 130 and not line.endswith((".", "!", "?")):
                formatted_html_blocks.append(f"  <h1>{line}</h1>")
                h1_added = True
                continue

            if len(line) < 100 and not line.endswith((".", "!", "?", ";", ":")):
                formatted_html_blocks.append(f"  <h2>{line}</h2>")
                continue

            formatted_html_blocks.append(f"  <p>{line}</p>")
            continue

        # Списки вида "термин — определение"
        dash_items = [l for l in lines if " — " in l or " - " in l]
        if len(dash_items) >= 2 and len(dash_items) == len(lines):
            items_html = []
            for l in lines:
                parts = re.split(r"\s+[—\-]\s+", l, maxsplit=1)
                if len(parts) == 2:
                    items_html.append(f"    <li><strong>{parts[0]}</strong> — {parts[1]}</li>")
                else:
                    items_html.append(f"    <li>{l}</li>")
            formatted_html_blocks.append("  <ul>\n" + "\n".join(items_html) + "\n  </ul>")
            continue

        # Обычный абзац текста
        merged_p = " ".join(lines)
        merged_p = re.sub(r"</?(?:td|th|tr|tbody|thead|table)[^>]*>", "", merged_p)
        if merged_p.strip():
            formatted_html_blocks.append(f"  <p>{merged_p}</p>")

    if not h1_added:
        formatted_html_blocks.insert(0, f"  <h1>{topic}</h1>")

    article_html = f'<div class="seo-article">\n' + "\n".join(formatted_html_blocks) + "\n</div>"
    return f"{style_block}\n{article_html}" if style_block else article_html


def inject_multiple_images_to_article(
    html_content: str,
    images: list[dict[str, str]],
) -> str:
    """Равномерно распределяет список картинок по статье."""
    if not html_content or not images:
        return html_content

    image_css = """
  .seo-article__image-wrapper { margin: 28px 0; text-align: center; }
  .seo-article__img { width: 100%; max-height: 480px; object-fit: cover; border-radius: 12px; box-shadow: 0 6px 18px rgba(0,0,0,0.08); }
  .seo-article__image-wrapper figcaption { font-size: 0.85em; color: #64748b; margin-top: 8px; font-style: italic; }
"""
    if "</style>" in html_content and ".seo-article__image-wrapper" not in html_content:
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

    # 1. Hero-баннер после H1 или первого абзаца
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

    # 2. Картинки под заголовками H2
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
    else:
        p_matches = list(re.finditer(r"</p>", html_content, flags=re.IGNORECASE))
        if p_matches:
            step = max(2, len(p_matches) // (len(remaining_images) + 1))
            offset = 0
            for i, img_data in enumerate(remaining_images, start=1):
                idx = min(i * step, len(p_matches) - 1)
                pos = p_matches[idx].end() + offset
                fig_html = make_figure(img_data)
                html_content = html_content[:pos] + fig_html + html_content[pos:]
                offset += len(fig_html)

    return html_content


def strip_existing_images(html: str) -> str:
    """Удаляет теги картинок перед повторной вставкой."""
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