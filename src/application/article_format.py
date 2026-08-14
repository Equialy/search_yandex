import re


def normalize_article_html(content: str) -> str:
    """Убирает markdown-обёртки ```html и лишние пробелы из ответа LLM."""
    text = (content or "").strip()
    if not text.startswith("```"):
        return text

    text = re.sub(r"^```(?:html)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()
