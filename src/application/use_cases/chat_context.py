
import uuid
from datetime import datetime
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import (
    ARTICLE_HTML_FORMAT_TEXT,
    CHAT_HTML_REFINEMENT_HINT,
    CHAT_VISION_HTML_ONLY_HINT,
    CHAT_VISION_STYLE_HINT,
)
from src.application.uow import UnitOfWorkProtocol
from src.application.article_format import has_styled_article_html, normalize_article_html
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.openai_gateway import OpenAiGateway


def _get_latest_article(project) -> Article | None:
    if not project.articles:
        return None
    return max(
        project.articles,
        key=lambda article: article.created_at or datetime.min,
    )


def _build_chat_prompt(
    user_prompt: str,
    *,
    current_article_html: str,
    with_vision: bool,
) -> str:
    parts = [user_prompt.strip()]

    if with_vision:
        parts.extend([CHAT_VISION_STYLE_HINT, CHAT_VISION_HTML_ONLY_HINT, ARTICLE_HTML_FORMAT_TEXT])
        if current_article_html:
            parts.append(
                "ТЕКУЩАЯ СТАТЬЯ (сохрани текст и структуру, измени CSS под скриншот):\n"
                f"{current_article_html}"
            )
    else:
        parts.append(CHAT_HTML_REFINEMENT_HINT)

    return "\n\n".join(part for part in parts if part)


class ContinueContextChatUseCase:
    """Продолжение диалога/доработка статьи с сохранением всего контекста."""

    def __init__(self, uow: UnitOfWorkProtocol, ai_gateway: OpenAiGateway):
        self._uow = uow
        self._openai = ai_gateway

    async def execute(
        self,
        project_id: uuid.UUID,
        user_prompt: str,
        *,
        image_base64: str | None = None,
        image_mime_type: str = "image/png",
    ) -> str:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id)
            if not project:
                raise ValueError("Проект не найден")

            latest_article = _get_latest_article(project)
            current_article_html = (latest_article.content if latest_article else "") or ""
            with_vision = bool(image_base64)

            wrapped_prompt = _build_chat_prompt(
                user_prompt,
                current_article_html=current_article_html,
                with_vision=with_vision,
            )

            response_text, reasoning, updated_history = await self._openai.completion_with_history(
                history=list(project.chat_history),
                user_prompt=wrapped_prompt,
                image_base64=image_base64,
                image_mime_type=image_mime_type,
                temperature=0.35 if with_vision else 0.7,
            )

            response_text = self._normalize_response(response_text)

            if with_vision and not has_styled_article_html(response_text):
                print("[ChatContext]: ответ без <style>, повторяем запрос с усиленным промптом...")
                retry_prompt = _build_chat_prompt(
                    "Предыдущий ответ не содержал CSS. Верни ПОЛНУЮ статью заново — только HTML "
                    "со <style> и div.seo-article. Сохрани весь текст статьи, измени только стили под скриншот.",
                    current_article_html=current_article_html or response_text,
                    with_vision=True,
                )
                response_text, reasoning, updated_history = await self._openai.completion_with_history(
                    history=updated_history,
                    user_prompt=retry_prompt,
                    image_base64=image_base64,
                    image_mime_type=image_mime_type,
                    temperature=0.25,
                )
                response_text = self._normalize_response(response_text)

            project.chat_history = updated_history
            flag_modified(project, "chat_history")

            return response_text

    @staticmethod
    def _normalize_response(response_text: str) -> str:
        stripped = (response_text or "").strip()
        if stripped.startswith("```") or stripped.startswith("<"):
            return normalize_article_html(response_text)
        return response_text
