import asyncio
import json
import re
import uuid
from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import (
    CHAT_HTML_REFINEMENT_HINT,
    REGENERATE_IMAGES_PROMPT_TEMPLATE,
)
from src.application.uow import UnitOfWorkProtocol
from src.application.article_format import (
    has_styled_article_html,
    inject_multiple_images_to_article,
    merge_style_with_markup,
    normalize_article_html,
    strip_existing_images,
    strip_style_block,
    truncate_for_style_context,
)
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.image_kie_gateway import ImageKieGenerationGateway
from src.infrastructure.gateways.kie_api import KieApiGateway



IMAGE_REGEN_PATTERNS = re.compile(
    r"(перегенерир\w*|сгенерир\w*|обнов\w*|замен\w*|поменя\w*|друг\w*|нов\w*)\s+"
    r"(картинк\w*|изображен\w*|фото\w*|иллюстрац\w*|баннер\w*|обложк\w*)",
    re.IGNORECASE
)


def _get_latest_article(project) -> Article | None:
    if not project.articles:
        return None
    return max(
        project.articles,
        key=lambda article: article.created_at or datetime.min,
    )


class ContinueContextChatUseCase:
    """Продолжение диалога/доработка статьи с поддержкой перегенерации картинок."""

    def __init__(
        self,
        uow: UnitOfWorkProtocol,
        ai_gateway: KieApiGateway,
        image_gateway: ImageKieGenerationGateway,
    ):
        self._uow = uow
        self._openai = ai_gateway
        self._image_gateway = image_gateway

    async def execute(
        self,
        project_id: uuid.UUID,
        user_prompt: str,
        *,
        image_base64: str | None = None,
        image_mime_type: str = "image/png",
        user_id: uuid.UUID | None = None
    ) -> str:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id, user_id=user_id)
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

            elif IMAGE_REGEN_PATTERNS.search(user_prompt) and current_article_html:
                response_text = await self._regenerate_article_images(
                    project=project,
                    latest_article=latest_article,
                    user_prompt=user_prompt,
                )

            else:
                response_text = await self._chat_with_history(
                    project=project,
                    user_prompt=user_prompt,
                )

            if has_styled_article_html(response_text) or "<div class=\"seo-article\">" in response_text:
                new_article = Article(
                    project_id=project.id,
                    title=latest_article.title if latest_article else project.keyword,
                    content=response_text,
                    reasoning="Обновлено через контекстный чат"
                )
                await uow.articles.add(new_article)

            return response_text

    async def _regenerate_article_images(
        self,
        *,
        project,
        latest_article: Article | None,
        user_prompt: str,
    ) -> str:
        """Перегенерация изображений и вставка в существующую статью."""
        print(f"[ChatContext]: Обнаружен запрос на перегенерацию изображений: '{user_prompt}'")
        current_html = latest_article.content if latest_article else ""
        topic = latest_article.title if latest_article else project.keyword

        clean_html = strip_existing_images(current_html)

        prompt_request = REGENERATE_IMAGES_PROMPT_TEMPLATE.format(
            topic=topic,
            user_prompt=user_prompt.strip()
        )
        prompts_json_text = await self._openai.generate_completion(
            [{"role": "user", "content": prompt_request}]
        )

        clean_json_str = (
            prompts_json_text.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )

        try:
            image_configs = json.loads(clean_json_str)[:3]
        except Exception:
            image_configs = [{
                "prompt": f"Photorealistic commercial photography for {topic}, modern style, 4k",
                "alt": topic,
                "caption": "Иллюстрация к услуге",
            }]

        async def generate_one(idx: int, item: dict[str, str]):
            try:
                url = await self._image_gateway.generate_and_save_image(
                    prompt=item["prompt"],
                    filename_prefix=f"proj_{project.id.hex[:6]}_regen_{idx}"
                )
                return {
                    "url": url,
                    "alt": item.get("alt", topic),
                    "caption": item.get("caption", ""),
                }
            except Exception as err:
                print(f"[Chat Image Regen Error]: {err}")
                return None

        print(f"[ChatContext]: Генерация {len(image_configs)} новых картинок...")
        tasks = [generate_one(idx, conf) for idx, conf in enumerate(image_configs, 1)]
        results = await asyncio.gather(*tasks)
        valid_images = [r for r in results if r is not None]

        if valid_images:
            updated_html = inject_multiple_images_to_article(clean_html, valid_images)
        else:
            updated_html = clean_html

        updated_history = list(project.chat_history)
        updated_history.append({"role": "user", "content": user_prompt.strip()})
        updated_history.append({
            "role": "assistant",
            "content": updated_html,
            "reasoning": f"Сгенерировано {len(valid_images)} новых изображений и интегрировано в статью.",
        })
        project.chat_history = updated_history
        flag_modified(project, "chat_history")

        return updated_html

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