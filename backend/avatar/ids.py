"""ID allocation. A-R3: render_id is a deterministic hash of the combination, so it doubles as
the cache key -- re-requesting the same (avatar, top, bottom, jacket) always yields the same id.
"""
import hashlib
import secrets
from typing import Callable, Optional


def new_avatar_id(exists: Callable[[str], bool]) -> str:
    for _ in range(50):
        candidate = f"avatar_{secrets.token_hex(3)}"
        if not exists(candidate):
            return candidate
    raise RuntimeError("Could not allocate a unique avatar_id.")


def render_id_for(avatar_id: str, top_id: str, bottom_id: str, jacket_id: Optional[str]) -> str:
    key = f"{avatar_id}|{top_id}|{bottom_id}|{jacket_id or ''}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    return f"render_{digest}"
