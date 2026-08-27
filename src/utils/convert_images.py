import io
from pathlib import Path

from PIL import Image


def _compress_and_save_webp(raw_bytes: bytes, destination_path: Path, quality: int = 82) -> None:
    """
    Конвертирует сырые байты (PNG/JPEG) в оптимизированный WebP
    с целевым весом 120-250 КБ без видимой потери качества.
    """
    with Image.open(io.BytesIO(raw_bytes)) as img:
        if img.mode in ("RGBA", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.save(
            destination_path,
            format="WEBP",
            quality=quality,
            method=6,
            optimize=True
        )