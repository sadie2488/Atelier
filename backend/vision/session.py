"""Temp-handle session bookkeeping between analyze and save/reject (V-A3, V-A4).

Two directories, deliberately distinct:
  - `config.MEDIA_DIR / "tmp"` -- the three candidate PNGs, served at /media/tmp/... per
    ARTIFACT_SPEC and MEDIA_PATTERN (the URL's directory segment must be lowercase letters
    only, so it cannot be `config.TEMP_DIR`'s literal name).
  - `config.TEMP_DIR` (media/_tmp) -- one small JSON file per handle holding everything not in
    the API response (per-candidate anchors, full color dicts, automated check results) so
    /save and /reject don't need to re-run segmentation. TTL-swept on startup (V-A4).
"""
import json
import secrets
import time
from pathlib import Path

from backend import config

TMP_MEDIA_DIR = config.MEDIA_DIR / "tmp"


def new_temp_handle() -> str:
    return "tmp_" + secrets.token_hex(6)   # TEMP_HANDLE_PATTERN: tmp_[0-9a-f]{12}


def _meta_path(handle: str) -> Path:
    return config.TEMP_DIR / f"{handle}.json"


def save_session(handle: str, data: dict) -> None:
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    _meta_path(handle).write_text(json.dumps(data), encoding="utf-8")


def load_session(handle: str) -> dict | None:
    p = _meta_path(handle)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def delete_session(handle: str) -> None:
    """Removes the session json and any remaining candidate PNGs for this handle. Safe to call
    even if some files were already moved (save) or never existed."""
    p = _meta_path(handle)
    if p.exists():
        p.unlink()
    if TMP_MEDIA_DIR.exists():
        for f in TMP_MEDIA_DIR.glob(f"{handle}_*.png"):
            f.unlink(missing_ok=True)


def sweep_expired(ttl_seconds: float | None = None) -> None:
    """V-A4: delete any temp handle older than the TTL. Called lazily by the router at import
    time (process startup) rather than from main.py."""
    ttl = config.TEMP_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if not config.TEMP_DIR.exists():
        return
    now = time.time()
    for p in config.TEMP_DIR.glob("*.json"):
        try:
            age = now - p.stat().st_mtime
        except FileNotFoundError:
            continue
        if age > ttl:
            delete_session(p.stem)
