import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import urlparse
import httpx

from src.config.settings import BASE_DIR, settings
from src.utils.convert_images import _compress_and_save_webp

IMAGES_DIR = BASE_DIR / "static" / "images" / "articles"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def _is_valid_image_url(url: str | None) -> bool:
    """Проверяет, подходит ли ссылка для KIE.AI (исключает SVG и битые ссылки)."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return False

    parsed_path = urlparse(url).path.lower()
    return any(parsed_path.endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS)


class ImageKieGenerationGateway:
    """
    Шлюз генерации изображений через KIE.AI (Google Nano Banana 2 Lite).
    """

    def __init__(self, http_client: httpx.AsyncClient):
        self._http = http_client
        self._api_key = settings.kie.API_KEY
        self._base_url = settings.kie.KIE_BASE_URL.rstrip('/')
        self._model = settings.kie.IMAGE_MODEL

    async def generate_and_save_image(
            self,
            prompt: str,
            filename_prefix: str = "article_img",
            size: str = "1024x1024",
            quality: str = "auto",
            image_reference_bytes: bytes | None = None,
            image_reference_url: str | None = None,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        clean_ref_url = (image_reference_url or "").split("#")[0].strip()
        image_urls = []

        if _is_valid_image_url(clean_ref_url):
            image_urls.append(clean_ref_url)
        else:
            if clean_ref_url:
                print(
                    f"[ImageKieGateway]: Референс {clean_ref_url} пропущен (SVG или неподдерживаемый формат, модель сгенерирует по тексту)")

        aspect_ratio = "1:1"
        if "1792" in size or "16:9" in size:
            aspect_ratio = "16:9"

        payload = {
            "model": self._model,
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "image_urls": image_urls
            }
        }

        create_task_url = f"{self._base_url}/api/v1/jobs/createTask"

        print(f"[ImageKieGateway]: Создание задачи в KIE.AI ({self._model}) с {len(image_urls)} референс-URL...")
        res = await self._http.post(create_task_url, json=payload, headers=headers, timeout=40.0)

        resp_data = res.json()
        data_block = resp_data.get("data")
        if not data_block or not isinstance(data_block, dict):
            raise ValueError(f"Ошибка KIE.AI при создании задачи: {resp_data}")

        task_id = data_block.get("taskId")
        if not task_id:
            raise ValueError(f"Не удалось получить taskId от KIE.AI: {resp_data}")

        print(f"[ImageKieGateway]: Задача создана (taskId={task_id}), ожидаем результат...")

        # 2. Опрос статуса задачи (polling)
        status_url = f"{self._base_url}/api/v1/jobs/recordInfo"
        result_img_url = None
        max_attempts = 45

        for attempt in range(1, max_attempts + 1):
            await asyncio.sleep(2.0)
            try:
                poll_res = await self._http.get(
                    status_url,
                    params={"taskId": task_id},
                    headers=headers,
                    timeout=20.0
                )
                if poll_res.status_code != 200:
                    continue

                poll_data = poll_res.json()
                task_data = poll_data.get("data") or {}
                state = task_data.get("state")

                if state == "success":
                    result_json_str = task_data.get("resultJson") or "{}"
                    if isinstance(result_json_str, str):
                        result_info = json.loads(result_json_str)
                    else:
                        result_info = result_json_str

                    urls = result_info.get("resultUrls") or []
                    if urls:
                        result_img_url = urls[0]
                        break
                elif state in ("fail", "failed"):
                    fail_msg = task_data.get("failMsg") or task_data.get("msg") or "Unknown error"
                    raise ValueError(f"Генерация KIE.AI завершилась ошибкой: {fail_msg}")

            except Exception as poll_err:
                print(f"[ImageKie Poll Warning #{attempt}]: {poll_err}")

        if not result_img_url:
            raise TimeoutError(f"Превышено время ожидания генерации KIE.AI (taskId={task_id})")

        # 3. Скачиваем готовое изображение
        print(f"[ImageKieGateway]: Скачиваем готовую картинку {result_img_url}...")
        img_res = await self._http.get(result_img_url, timeout=40.0)
        img_res.raise_for_status()

        # 4. Сохраняем в WebP
        file_name = f"{filename_prefix}_{uuid.uuid4().hex[:8]}.webp"
        file_path = IMAGES_DIR / file_name

        _compress_and_save_webp(img_res.content, file_path, quality=82)

        file_size_kb = file_path.stat().st_size / 1024
        print(f" [ImageKie Saved & Compressed]: {file_path} ({file_size_kb:.1f} KB)")

        return f"/static/images/articles/{file_name}"
