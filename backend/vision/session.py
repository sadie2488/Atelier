"""Temp-handle session bookkeeping between analyze and save/reject (V-A3, V-A4).

Two directories, deliberately distinct:
  - `tmp_media_dir()` (`config.MEDIA_DIR / "tmp"`) -- the three candidate PNGs, served at
    /media/tmp/... per ARTIFACT_SPEC and MEDIA_PATTERN (the URL's directory segment must be
    lowercase letters only, so it cannot be `config.TEMP_DIR`'s literal name).
  - `config.TEMP_DIR` (media/_tmp) -- one small JSON file per handle holding everything not in
    the API response (per-candidate anchors, full color dicts, automated check results) so
    /save and /reject don't need to re-run segmentation. TTL-swept on startup (V-A4).

Test hygiene (re-dispatch fix): `tmp_media_dir()` is a function, not a module-level constant,
so it re-reads `config.MEDIA_DIR` on every call. A module-level `TMP_MEDIA_DIR =
config.MEDIA_DIR / "tmp"` would bind to whatever `config.MEDIA_DIR` was at import time (process
start, before any test's `isolated_media_dir` fixture monkeypatches it) and every caller that
imported that stale constant -- this module's own `delete_session`, and
`backend/routes/items.py` -- would keep writing real candidate PNGs into `media/tmp` for the
life of the test process regardless of the monkeypatch. Calling `tmp_media_dir()` instead keeps
every caller pointed at the current (per-test, isolated) `config.MEDIA_DIR`.
"""
import json
import secrets
import time
from pathlib import Path

from backend import config


def tmp_media_dir() -> Path:
    return config.MEDIA_DIR / "tmp"


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
    tmp_dir = tmp_media_dir()
    if tmp_dir.exists():
        for f in tmp_dir.glob(f"{handle}_*.png"):
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
