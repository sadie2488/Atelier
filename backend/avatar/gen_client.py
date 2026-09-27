"""A7/A-R7: the single Gemini call that takes the person photo plus garment references and
returns the full look. Every failure -- missing key, network, quota, billing, bad model name,
or "no image in the response" -- raises GenerationError so callers can treat them uniformly:
back off, mark the render `failed`, never raise to the user (A-R12, A-R15).
"""
import io
from typing import Optional

from PIL import Image

from backend import config

from .prompt import MODEL, build_prompt


class GenerationError(Exception):
    """Any Gemini call failure. Callers must catch this and keep the local composite."""


def _flatten(img: Image.Image) -> Image.Image:
    """Garment cutouts are RGBA with a transparent background; flatten onto white before
    sending as a reference image so the model sees a plain garment photo, not a checkerboard."""
    if img.mode != "RGBA":
        return img.convert("RGB")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])
    return bg


def generate_tryon(
    person_img: Image.Image,
    top_img: Image.Image,
    bottom_img: Optional[Image.Image],
    jacket_img: Optional[Image.Image],
    is_dress: bool,
) -> Image.Image:
    """-> the generated RGB image. Raises GenerationError on any failure."""
    if not config.GEMINI_API_KEY:
        raise GenerationError("GEMINI_API_KEY is not set.")

    from google import genai
    from google.genai import errors

    prompt = build_prompt(has_jacket=jacket_img is not None, is_dress=is_dress)
    contents = [prompt, person_img.convert("RGB"), _flatten(top_img)]
    if not is_dress and bottom_img is not None:
        contents.append(_flatten(bottom_img))
    if jacket_img is not None:
        contents.append(_flatten(jacket_img))

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config={"http_options": {"timeout": int(config.GEMINI_TIMEOUT_SECONDS * 1000)}},
        )
    except errors.APIError as e:
        raise GenerationError(f"Gemini call failed: {e}") from e
    except Exception as e:  # network errors, SDK errors -- never let this reach the request path
        raise GenerationError(f"Gemini call failed: {type(e).__name__}: {e}") from e

    for candidate in getattr(response, "candidates", None) or []:
        for part in getattr(candidate.content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and inline.data:
                return Image.open(io.BytesIO(inline.data)).convert("RGB")

    raise GenerationError("Gemini response contained no image (likely a safety block or refusal).")
