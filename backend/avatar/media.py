"""Media file helpers: save/load PNGs under config.MEDIA_DIR and return the contract's relative
URL (A-R17: always `/media/...`, never absolute).
"""
from PIL import Image

from backend import config


def save_png(img: Image.Image, subdir: str, filename: str) -> str:
    directory = config.MEDIA_DIR / subdir
    directory.mkdir(parents=True, exist_ok=True)
    img.convert("RGBA").save(directory / filename, format="PNG")
    return f"/media/{subdir}/{filename}"


def load_from_url(url: str) -> Image.Image:
    """`url` is a contract-shaped relative media URL, e.g. /media/items/top_a3f9c2.png."""
    rel = url[len("/media/"):] if url.startswith("/media/") else url
    return Image.open(config.MEDIA_DIR / rel).convert("RGBA")
