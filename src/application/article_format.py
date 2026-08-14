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
