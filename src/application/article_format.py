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
