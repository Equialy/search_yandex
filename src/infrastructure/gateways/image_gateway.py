# src/infrastructure/gateways/image_gateway.py

import base64
import uuid
from pathlib import Path
import httpx
from openai import AsyncOpenAI
from src.config.settings import BASE_DIR, settings

IMAGES_DIR = BASE_DIR / "static" / "images" / "articles"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


class ImageGenerationGateway:
    def __init__(self, openai_client: AsyncOpenAI, http_client: httpx.AsyncClient):
        self._openai = openai_client
        self._http = http_client
        self._model = getattr(getattr(settings, "OPENAI", None), "IMAGE_MODEL", "gpt-image-2")

    async def generate_and_save_image(
        self,
        prompt: str,
        filename_prefix: str = "article_img",
        size: str = "1024x1024",
        quality: str = "auto",  # 'low', 'medium', 'high' или 'auto'
    ) -> str:
        """
        Генерирует изображение через gpt-image-2 / gpt-image-1 и сохраняет на диск.
        """
        print(f"[ImageGenerationGateway]: Запуск генерации через {self._model} (quality={quality})...")

        response = await self._openai.images.generate(
            model=self._model,
            prompt=prompt,
            size=size,
            quality=quality,  # Передаем 'auto' или 'high'
            n=1,
        )

        image_data = response.data[0]
        file_name = f"{filename_prefix}_{uuid.uuid4().hex[:8]}.png"
        file_path = IMAGES_DIR / file_name

        # 1. Если API вернул base64
        if getattr(image_data, "b64_json", None):
            raw_bytes = base64.b64decode(image_data.b64_json)
            with open(file_path, "wb") as f:
                f.write(raw_bytes)

        # 2. Если API вернул прямой URL
        elif getattr(image_data, "url", None):
            img_response = await self._http.get(image_data.url, timeout=40.0)
            img_response.raise_for_status()
            with open(file_path, "wb") as f:
                f.write(img_response.content)
        else:
            raise ValueError("API не вернул данные изображения (ни url, ни b64_json)")

        print(f"[Image Saved]: {file_path}")
        return f"/static/images/articles/{file_name}"