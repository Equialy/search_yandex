
import base64
import uuid
from pathlib import Path
import httpx
from openai import AsyncOpenAI
from src.config.settings import BASE_DIR, settings
from src.utils.extract_data import _prepare_image_png_bytes

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
            quality: str = "auto",
            image_reference_bytes: bytes | None = None,
    ) -> str:
        """
        Генерирует изображение:
        - Если передан image_reference_bytes -> использует client.images.edit (с логотипом как входным файлом)
        - Если нет -> использует client.images.generate
        """
        response = None

        if image_reference_bytes:
            print(
                f"[ImageGenerationGateway]: Генерация через {self._model} с файлом-референсом логотипа ({len(image_reference_bytes)} байт)...")
            try:
                png_bytes = _prepare_image_png_bytes(image_reference_bytes)
                # Передаем файл логотипа в API как tuple (filename, bytes, mime_type)
                response = await self._openai.images.edit(
                    model=self._model,
                    image=("logo.png", png_bytes, "image/png"),
                    prompt=prompt,
                    size=size,
                    quality=quality,
                    n=1,
                )
            except Exception as edit_err:
                print(f"[Image Edit API Warning]: {edit_err}. Пробуем обычную генерацию с промптом...")

        if response is None:
            print(f"[ImageGenerationGateway]: Запуск стандартной генерации через {self._model} (quality={quality})...")
            response = await self._openai.images.generate(
                model=self._model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
            )

        image_data = response.data[0]
        file_name = f"{filename_prefix}_{uuid.uuid4().hex[:8]}.png"
        file_path = IMAGES_DIR / file_name

        if getattr(image_data, "b64_json", None):
            raw_bytes = base64.b64decode(image_data.b64_json)
            with open(file_path, "wb") as f:
                f.write(raw_bytes)
        elif getattr(image_data, "url", None):
            img_response = await self._http.get(image_data.url, timeout=40.0)
            img_response.raise_for_status()
            with open(file_path, "wb") as f:
                f.write(img_response.content)
        else:
            raise ValueError("API не вернул данные изображения")

        print(f"[Image Saved]: {file_path}")
        return f"/static/images/articles/{file_name}"