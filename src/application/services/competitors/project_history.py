from __future__ import annotations

import re
from typing import Any

# Маркеры системных/служебных блоков — всё после них отрезается из UI.
_PROMPT_CUT_MARKERS = (
    "\n\nЕсли пользователь просит изменить",
    "\n\nК сообщению приложен скриншот",
    "\n\nФОРМАТ ОТВЕТА",
    "\n\nФормат ответа СТРОГО",
    "\n\nDESIGN TOKENS:",
    "\n\nMARKUP СТАТЬИ",
    "\n\nТЕКУЩАЯ СТАТЬЯ",
    "\n\nОБЯЗАТЕЛЬНО:",
    "\n\nЗАДАЧА:",
    "\n\nПРАВИЛА:",
    "\n\nЗАПРОС ПОЛЬЗОВАТЕЛЯ:",
    "\n\nСТРОГИЕ ПРАВИЛА",
    "\n\nОБЯЗАТЕЛЬНАЯ СТРУКТУРА",
    "\n\nДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ",
)

_INTERNAL_USER_PREFIXES = (
    "Предыдущий ответ не содержал CSS",
    "Предыдущий ответ был некорректным",
    "Предыдущий ответ не содержал",
)


def _message_has_image(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        isinstance(item, dict) and item.get("type") == "image_url"
        for item in content
    )


def _content_to_text(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part).strip()
    return str(content or "").strip()


def _is_article_html(text: str) -> bool:
    lower = text.lower()
    return "<style" in lower and ("<h1" in lower or "seo-article" in lower)


def _extract_user_intent(content: str) -> str:
    text = content.replace("[Изображение]", " ").strip()

    for marker in _PROMPT_CUT_MARKERS:
        if marker in text:
            text = text.split(marker)[0].strip()

    text = re.sub(r"\[Скриншот\]\s*", "", text, flags=re.IGNORECASE).strip()
    text = text.replace("[Стилизация по скриншоту]", "").strip()

    if len(text) > 400:
        first_line = text.split("\n")[0].strip()
        if 0 < len(first_line) <= 300:
            return first_line

    if len(text) > 400 and "\n\n" in text:
        first_block = text.split("\n\n")[0].strip()
        if len(first_block) <= 300:
            return first_block

    return text


def _classify_message(role: str, content: str, *, has_image: bool) -> str:
    if role == "system":
        return "system"

    if "[Стилизация по скриншоту]" in content or has_image:
        if "скриншот" in content.lower() or "стил" in content.lower() or has_image:
            return "styling"

    if content.startswith("Напиши коммерческую SEO-статью"):
        return "generation"

    if "Дополнительный глубокий анализ конкурентов" in content:
        return "analysis"

    if role == "assistant" and "успешно изучены" in content.lower():
        return "analysis_ack"

    if any(content.startswith(prefix) for prefix in _INTERNAL_USER_PREFIXES):
        return "internal"

    return "refinement"


def _format_user_message(content: str, message_type: str) -> str:
    if message_type == "analysis":
        return "Добавлен анализ конкурентов в контекст"

    if message_type == "generation":
        topic_match = re.search(r"на тему '([^']+)'", content)
        topic = topic_match.group(1) if topic_match else "статья"
        return f"Генерация статьи: «{topic}»"

    if message_type == "styling":
        intent = _extract_user_intent(content)
        return intent or "Стилизация по скриншоту"

    if message_type == "internal":
        return "Повторный запрос стилизации"

    intent = _extract_user_intent(content)
    return intent or "Доработка статьи"


def _should_skip_message(role: str, message_type: str, display_text: str) -> bool:
    if message_type in {"system", "analysis_ack", "internal"}:
        return True

    if role == "user" and message_type == "analysis":
        return False

    if not display_text.strip():
        return True

    if role == "user" and len(display_text) > 600 and message_type == "refinement":
        lowered = display_text.lower()
        if any(token in lowered for token in ("seo-article", "методичк", "lsa", "title:", "description:")):
            return True

    return False


def _format_assistant_message(content: str) -> tuple[str, bool, str | None]:
    if _is_article_html(content):
        length = len(content)
        return f"Обновлена HTML-версия статьи ({length:,} симв.)".replace(",", " "), True, content

    if len(content) > 400:
        return content[:400] + "…", True, None

    return content, False, None


def get_latest_article_html(
    raw_history: list[dict[str, Any]] | None,
    fallback_content: str | None = None,
) -> str | None:
    """Последняя HTML-версия из чата или из сохранённой статьи."""
    for msg in reversed(raw_history or []):
        if msg.get("role") != "assistant":
            continue
        text = _content_to_text(msg.get("content", ""))
        if _is_article_html(text):
            return text
    return fallback_content


def format_chat_history_for_ui(raw_history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Готовит chat_history проекта для отображения в UI."""
    if not raw_history:
        return []

    formatted: list[dict[str, Any]] = []
    article_version = 0

    for msg in raw_history:
        role = str(msg.get("role", "user"))
        if role == "system":
            continue

        raw_content = msg.get("content", "")
        has_image = _message_has_image(raw_content)
        raw_text = _content_to_text(raw_content)
        message_type = _classify_message(role, raw_text, has_image=has_image)
        html_content: str | None = None
        is_truncated = False

        if role == "user":
            display_text = _format_user_message(raw_text, message_type)
            if has_image and message_type == "styling":
                display_text = display_text or "Стилизация по скриншоту"
        else:
            display_text, is_truncated, html_content = _format_assistant_message(raw_text)
            if html_content:
                article_version += 1

        if _should_skip_message(role, message_type, display_text):
            continue

        formatted.append({
            "role": role,
            "content": display_text,
            "message_type": message_type,
            "is_truncated": is_truncated,
            "has_image": has_image and role == "user",
            "html_content": html_content,
            "article_version": article_version if html_content else None,
        })

    return formatted


def build_article_preview(content: str, max_chars: int = 320) -> str:
    """Короткий текстовый preview статьи без HTML-тегов."""
    if not content:
        return ""

    text = re.sub(r"<style[^>]*>.*?</style>", " ", content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…"
