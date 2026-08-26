import re


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
