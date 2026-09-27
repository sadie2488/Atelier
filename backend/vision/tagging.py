"""Post-save automatic details (attributes) from one Gemini vision call on the saved cutout.

Fixed prompt, no user text. Any failure (no key, timeout, bad JSON) -> {} and a warning: the
documented degraded state is an item saved without attributes; tagging never fails a save.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend import config

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 12.0
MAX_LEN = 60

_COMMON = ("pattern", "closure", "formality", "season", "warmth")
KEYS_BY_CATEGORY = {
    "tops": ("subcategory", "sleeve", "neckline", "material", "fit") + _COMMON,
    "bottoms": ("subcategory", "material", "length", "rise") + _COMMON,
    "jackets": ("subcategory", "material", "length") + _COMMON,
}
_HINTS = {
    "tops": "fit is one of tight/regular/loose",
    "bottoms": "length is one of thigh/knee/calf/full; rise is one of high/mid/low",
    "jackets": "length is one of cropped/regular/long",
}

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tagging")


def _prompt(category: str) -> str:
    keys = KEYS_BY_CATEGORY[category]
    return (
        f"This image is a single clothing item (category: {category}). Return ONLY a JSON object "
        f"with exactly these keys: {', '.join(keys)}. Each value is a short lowercase phrase. "
        f"formality is one of casual/smart/dressy; season is one of spring/summer/fall/winter/all-season; "
        f"warmth is one of light/mid/heavy; {_HINTS[category]}. "
        "Use \"none\" for closure if there is none."
    )


def _client():
    from google import genai  # deferred: only needed on the Gemini path
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _call(image_bytes: bytes, category: str) -> str:
    from google.genai import types

    client = _client()  # keep a reference: a dropped Client closes its HTTP session mid-call
    resp = client.models.generate_content(
        model=config.GEMINI_TEXT_MODEL,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/png"), _prompt(category)],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return getattr(resp, "text", None) or ""


def clean(raw: object, category: str) -> dict[str, str]:
    """Keep only known keys for the category with non-empty string values <= MAX_LEN."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key in KEYS_BY_CATEGORY.get(category, ()):
        v = raw.get(key)
        if isinstance(v, str):
            v = v.strip().lower()
            if v and len(v) <= MAX_LEN:
                out[key] = v
    return out


def tag_item(image_path: Path, category: str) -> dict[str, str]:
    if category not in KEYS_BY_CATEGORY:
        return {}
    if not config.GEMINI_API_KEY:
        log.warning("auto-tagging skipped: no GEMINI_API_KEY")
        return {}
    try:
        data = Path(image_path).read_bytes()
        text = _pool.submit(_call, data, category).result(timeout=TIMEOUT_SECONDS)
        return clean(json.loads(text), category)
    except Exception as e:  # noqa: BLE001 -- degraded state: save without attributes
        log.warning("auto-tagging failed for %s: %r", image_path, e)
        return {}
