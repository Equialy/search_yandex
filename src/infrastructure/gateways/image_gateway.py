
import base64
import uuid
from pathlib import Path
import httpx
from openai import AsyncOpenAI
from src.config.settings import BASE_DIR, settings
from src.utils.extract_data import _prepare_image_png_bytes
from src.utils.convert_images import _compress_and_save_webp

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
        Генерирует изображение через OpenAI и сжимает его в WebP (~150-200 KB).
        """
        response = None

        if image_reference_bytes:
            print(
                f"[ImageGenerationGateway]: Генерация через {self._model} с референсом логотипа ({len(image_reference_bytes)} байт)...")
            try:
                png_bytes = _prepare_image_png_bytes(image_reference_bytes, target_size=1024)
                response = await self._openai.images.edit(
                    model=self._model,
                    image=("image.png", png_bytes, "image/png"),
                    prompt=prompt,
                    size=size,
                    quality=quality,
                    n=1,
                )
            except Exception as edit_err:
                print(f"[Image Edit API Warning]: {edit_err}. Пробуем обычную генерацию...")

        if response is None:
            print(f"[ImageGenerationGateway]: Запуск генерации через {self._model}...")
            response = await self._openai.images.generate(
                model=self._model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
            )

        image_data = response.data[0]

        if getattr(image_data, "b64_json", None):
            raw_bytes = base64.b64decode(image_data.b64_json)
        elif getattr(image_data, "url", None):
            img_response = await self._http.get(image_data.url, timeout=40.0)
            img_response.raise_for_status()
            raw_bytes = img_response.content
        else:
            raise ValueError("API не вернул данные изображения")

        file_name = f"{filename_prefix}_{uuid.uuid4().hex[:8]}.webp"
        file_path = IMAGES_DIR / file_name

        _compress_and_save_webp(raw_bytes, file_path, quality=82)

        file_size_kb = file_path.stat().st_size / 1024
        print(f" [Image Saved & Compressed]: {file_path} ({file_size_kb:.1f} KB)")

        return f"/static/images/articles/{file_name}"