import asyncio
import json
import uuid
import httpx
from src.config.settings import BASE_DIR, settings
from src.utils.convert_images import _compress_and_save_webp

IMAGES_DIR = BASE_DIR / "static" / "images" / "articles"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


class ImageKieGenerationGateway:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http = http_client
        self._api_key = settings.kie.API_KEY
        self._base_url = settings.kie.KIE_BASE_URL.rstrip('/')
        self._model = settings.kie.IMAGE_MODEL
        self._upload_url = "https://kieai.redpandaai.co/api/file-stream-upload"

    async def upload_image_to_cdn(self, file_bytes: bytes) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        filename = f"logo_{uuid.uuid4().hex[:8]}.png"

        files = {"file": (filename, file_bytes, "image/png")}
        data = {"uploadPath": "images/logos", "fileName": filename}

        res = await self._http.post(self._upload_url, files=files, data=data, headers=headers, timeout=30.0)
        res.raise_for_status()

        resp = res.json()
        download_url = (resp.get("data") or {}).get("downloadUrl") or (resp.get("data") or {}).get("fileUrl")
        if not download_url:
            raise ValueError(f"CDN upload failed: {resp}")

        print(
            f"\n================ [CDN LOGO URL] ================\n{download_url}\n================================================\n"
        )
        return download_url

    async def generate_and_save_image(
        self,
        prompt: str,
        filename_prefix: str = "article_img",
        size: str = "1024x1024",
        image_url: str | None = None,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        aspect_ratio = "16:9" if "16:9" in size or "1792" in size else "1:1"

        if "flux-3" in self._model.lower():
            if image_url:
                api_model = "flux-3/klein-edit-image"
                edit_prompt = f"{prompt} (use the company logo from image 1)"
                input_payload = {
                    "prompt": edit_prompt,
                    "aspect_ratio": aspect_ratio,
                    "image_urls": [image_url],
                    "resolution": "1K",
                    "output_format": "png",
                    "enhance_prompt": False,
                }
            else:
                api_model = "flux-3/klein-text-to-image"
                input_payload = {
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "resolution": "1K",
                    "output_format": "png",
                    "enhance_prompt": True,
                }
        else:
            api_model = self._model
            input_payload = {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "image_input": [image_url] if image_url else [],
                "resolution": "1K",
                "output_format": "png",
            }

        payload = {
            "model": api_model,
            "input": input_payload,
        }

        res = await self._http.post(
            f"{self._base_url}/api/v1/jobs/createTask",
            json=payload,
            headers=headers,
            timeout=250.0,
        )
        res.raise_for_status()

        res_data = res.json()
        if res_data.get("code") != 200:
            raise ValueError(f"KIE error {res_data.get('code')}: {res_data.get('msg')}")

        task_id = (res_data.get("data") or {}).get("taskId")
        if not task_id:
            raise ValueError(f"Task creation failed: {res.text}")

        result_img_url = None

        for _ in range(90):
            await asyncio.sleep(2.0)
            poll_res = await self._http.get(
                f"{self._base_url}/api/v1/jobs/recordInfo",
                params={"taskId": task_id},
                headers=headers,
                timeout=100.0,
            )
            if poll_res.status_code == 200:
                data = poll_res.json().get("data") or {}
                state = data.get("state")
                if state == "success":
                    r_json = data.get("resultJson")
                    urls = (json.loads(r_json) if isinstance(r_json, str) else (r_json or {})).get("resultUrls", [])
                    if urls:
                        result_img_url = urls[0]
                        break
                elif state in ("fail", "failed"):
                    raise ValueError(f"KIE generation failed: {data}")

        if not result_img_url:
            raise TimeoutError(f"Generation timeout for task {task_id}")

        img_res = await self._http.get(result_img_url, timeout=30.0)
        img_res.raise_for_status()

        file_path = IMAGES_DIR / f"{filename_prefix}_{uuid.uuid4().hex[:8]}.webp"
        _compress_and_save_webp(img_res.content, file_path, quality=82)
        return f"/static/images/articles/{file_path.name}"