import uuid
from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import CHAT_HTML_REFINEMENT_HINT
from src.application.uow import UnitOfWorkProtocol
from src.application.article_format import (
    has_styled_article_html,
    merge_style_with_markup,
    normalize_article_html,
    strip_style_block,
    truncate_for_style_context,
)
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.openai_gateway import OpenAiGateway


def _get_latest_article(project) -> Article | None:
    if not project.articles:
        return None
    return max(
        project.articles,
        key=lambda article: article.created_at or datetime.min,
    )


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

            if image_base64:
                response_text = await self._style_from_screenshot(
                    project=project,
                    user_prompt=user_prompt,
                    current_article_html=current_article_html,
                    image_base64=image_base64,
                    image_mime_type=image_mime_type,
                )
            else:
                response_text = await self._chat_with_history(
                    project=project,
                    user_prompt=user_prompt,
                )

            return response_text

    async def _style_from_screenshot(
        self,
        *,
        project,
        user_prompt: str,
        current_article_html: str,
        image_base64: str,
        image_mime_type: str,
    ) -> str:
        """Отдельный контекст для стилизации — без истории генерации/анализа."""
        article_markup = truncate_for_style_context(
            strip_style_block(current_article_html)
        )
        if not article_markup:
            raise ValueError("Нет статьи для стилизации — сначала сгенерируйте статью")

        print("[ChatContext]: изолированная стилизация по скриншоту (без chat_history)...")

        response_text, reasoning = await self._openai.style_article_from_screenshot(
            article_html=article_markup,
            user_prompt=user_prompt,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
        )
        response_text = merge_style_with_markup(
            self._normalize_response(response_text),
            article_markup,
        )

        if not has_styled_article_html(response_text):
            print("[ChatContext]: повторное применение CSS...")
            response_text, reasoning = await self._openai.style_article_from_screenshot(
                article_html=article_markup,
                user_prompt=(
                    "Предыдущий ответ был некорректным. Верни полный HTML: "
                    "<style> с яркими цветами из скриншота + весь markup статьи."
                ),
                image_base64=image_base64,
                image_mime_type=image_mime_type,
            )
            response_text = merge_style_with_markup(
                self._normalize_response(response_text),
                article_markup,
            )

        updated_history = list(project.chat_history)
        updated_history.append({
            "role": "user",
            "content": f"[Стилизация по скриншоту] {user_prompt.strip()}",
        })
        updated_history.append({
            "role": "assistant",
            "content": response_text,
            "reasoning": reasoning,
        })
        project.chat_history = updated_history
        flag_modified(project, "chat_history")

        return response_text

    async def _chat_with_history(self, *, project, user_prompt: str) -> str:
        wrapped_prompt = f"{user_prompt.strip()}\n\n{CHAT_HTML_REFINEMENT_HINT}"

        response_text, reasoning, updated_history = await self._openai.completion_with_history(
            history=list(project.chat_history),
            user_prompt=wrapped_prompt,
            history_user_content=user_prompt.strip(),
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
