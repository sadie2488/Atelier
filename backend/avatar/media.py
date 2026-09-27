"""Media file helpers: save/load PNGs under config.MEDIA_DIR and return the contract's relative
URL (A-R17: always `/media/...`, never absolute).

Local disk (config.MEDIA_DIR) is a per-machine cache that a redeploy wipes; durable storage
(backend/media_store.py, PM-owned) is the source of truth. Every save that must outlive the
process is persisted there, and every read falls back to it when the local file is missing --
a fresh deploy, or a read on a different machine than the one that wrote it.
"""
import os
import threading
from pathlib import Path

from PIL import Image

from backend import config, media_store
from contract.enums import ErrorCode

from .errors import AvatarError


def save_png(img: Image.Image, subdir: str, filename: str) -> str:
    directory = config.MEDIA_DIR / subdir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    img.convert("RGBA").save(path, format="PNG")
    # media/_preview/ is debug output only (backend/avatar/scripts/, backend/avatar/verify.py on
    # a failed verification) and must never land in durable storage.
    if "_preview" not in Path(subdir).parts:
        media_store.persist(path)
    return f"/media/{subdir}/{filename}"


def load_media(rel_or_url: str) -> Image.Image:
    """Read a stored image back. `rel_or_url` is a contract-shaped relative media URL (e.g.
    /media/items/top_a3f9c2.png) or a bare path relative to MEDIA_DIR.

    Reads the local cache first; if it's missing (fresh deploy, or another machine than the one
    that wrote it), falls back to durable storage and writes the local cache for next time.
    Raises AvatarError(internal_error) if the file exists in neither place.
    """
    rel = rel_or_url[len("/media/"):] if rel_or_url.startswith("/media/") else rel_or_url
    path = config.MEDIA_DIR / rel
    if not path.is_file():
        data = media_store.get(Path(rel).as_posix())
        if data is None:
            raise AvatarError(ErrorCode.internal_error, f"Missing media file: {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        # temp file + os.replace (atomic): a concurrent reader never sees a half-written PNG.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    return Image.open(path).convert("RGBA")
