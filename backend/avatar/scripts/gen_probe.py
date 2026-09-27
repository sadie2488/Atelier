"""One-shot probe of the real Gemini image-generation call (A7). Costs quota -- run it
sparingly, by hand, never from a test. Saves the result to media/_preview/gen_probe_*.png and
prints latency so the PM/human can judge fidelity and speed before the real pipeline trusts it.
"""
import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from PIL import Image

from backend import config
from backend.avatar.prompt import MODEL, PROMPT_VERSION, build_prompt

FIXTURES = ROOT / "fixtures" / "images"
PREVIEW_DIR = ROOT / "media" / "_preview"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

PERSON = "red Whoa So Soft Shrunken Fairisle Cardigan Sweater #661720.png"
TOP = "sharp green Whoa So Soft Fitted Sweater Polo #048c57.png"
BOTTOM = "black Low-Rise Baggy Straight Jean #0f0f11.png"


def main():
    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set; cannot probe.")
        return 1

    from google import genai
    from google.genai import errors

    person = Image.open(FIXTURES / PERSON).convert("RGB")
    top = Image.open(FIXTURES / TOP).convert("RGB")
    bottom = Image.open(FIXTURES / BOTTOM).convert("RGB")

    prompt = build_prompt(has_jacket=False, is_dress=False)
    print(f"model={MODEL} prompt_version={PROMPT_VERSION}")
    print(f"prompt: {prompt}\n")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    t0 = time.perf_counter()
    try:
        response = client.models.generate_content(model=MODEL, contents=[prompt, person, top, bottom])
    except errors.APIError as e:
        print(f"GEMINI CALL FAILED (APIError): {e}")
        return 1
    except Exception as e:
        print(f"GEMINI CALL FAILED ({type(e).__name__}): {e}")
        return 1
    latency = time.perf_counter() - t0
    print(f"latency: {latency:.2f}s")

    saved = 0
    for ci, candidate in enumerate(getattr(response, "candidates", None) or []):
        parts = getattr(candidate.content, "parts", None) or []
        for pi, part in enumerate(parts):
            text = getattr(part, "text", None)
            if text:
                print(f"[candidate {ci} part {pi}] text: {text[:200]}")
            inline = getattr(part, "inline_data", None)
            if inline is not None and inline.data:
                out_path = PREVIEW_DIR / f"gen_probe_{ci}_{pi}.png"
                Image.open(io.BytesIO(inline.data)).convert("RGB").save(out_path)
                print(f"[candidate {ci} part {pi}] saved image -> {out_path}")
                saved += 1

    if saved == 0:
        print("No image part in the response. Full response repr follows:")
        print(response)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
