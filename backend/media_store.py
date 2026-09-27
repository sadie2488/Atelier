"""Durable media storage. PM-owned: lanes call it, never edit it.

Local disk (config.MEDIA_DIR) is a cache that disappears on redeploy and differs per machine;
MongoDB GridFS (bucket "media") is the source of truth, so every machine and every deploy sees
the same /media/... files. Keys are paths relative to MEDIA_DIR, e.g. "items/top_a3f9c2.png".

Lanes: after writing a file that must outlive the process (item cutouts, avatars, renders),
call `persist(path)`. Temp candidates under media/tmp/ don't need it.
"""
import mimetypes
from pathlib import Path

import gridfs

from backend import config, db

BUCKET = "media"


def key_for(path: Path) -> str:
    """Absolute path under MEDIA_DIR -> storage key. Raises for paths outside MEDIA_DIR."""
    return Path(path).resolve().relative_to(config.MEDIA_DIR.resolve()).as_posix()


def _bucket() -> gridfs.GridFSBucket:
    return gridfs.GridFSBucket(db.get_db(), bucket_name=BUCKET)


def put(key: str, data: bytes) -> None:
    """Store bytes under key, replacing any earlier version. Raises on failure."""
    bucket = _bucket()
    for old in bucket.find({"filename": key}):
        bucket.delete(old._id)
    bucket.upload_from_stream(key, data, metadata={"content_type": content_type(key)})


def get(key: str) -> bytes | None:
    try:
        return _bucket().open_download_stream_by_name(key).read()
    except gridfs.errors.NoFile:
        return None


def persist(path: Path) -> None:
    """Upload a file already written under MEDIA_DIR."""
    path = Path(path)
    put(key_for(path), path.read_bytes())


def content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"
