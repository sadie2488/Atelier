"""Outfit explanations (S-E1..S-E5).

Gemini writes the explanation from the strategy label and the outfit's colors; it never
re-ranks (S-E1, out of scope per S-X2) and never blocks or delays the response (S-E4) --
calls run under a hard timeout and any failure (no key, network, timeout, empty text) falls
back to a static per-strategy explanation (S-E3), which is what ships first per the lane's
priority order.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from contract.enums import Strategy

_FALLBACK: dict[Strategy, str] = {
    Strategy.neutral_anchor: "A neutral piece anchors the look, so the colorful piece can lead.",
    Strategy.everyday_neutral_base: "An easy neutral base pairs cleanly with this color.",
    Strategy.analogous: "These colors sit close together on the color wheel for a soft, unified look.",
    Strategy.complementary: "These colors sit opposite each other on the color wheel for deliberate contrast.",
    Strategy.monochrome_highlight: "One color family, played across light and dark, with a highlight piece.",
    Strategy.sandwich: "The jacket and bottom share a color, sandwiching a contrasting top between them.",
}

_executor = ThreadPoolExecutor(max_workers=2)


def fallback_explanation(strategy: Strategy) -> str:
    """Static per-strategy explanation (S-E3). Always non-empty for every ladder strategy."""
    return _FALLBACK[strategy]


def explain(strategy: Strategy, top: dict, bottom: dict, jacket: dict | None) -> str:
    """Best-effort Gemini explanation; always returns promptly and non-empty (S-E4)."""
    from backend import config

    if not config.GEMINI_API_KEY:
        return fallback_explanation(strategy)

    future = _executor.submit(_gemini_explain, strategy, top, bottom, jacket)
    try:
        text = future.result(timeout=config.GEMINI_TIMEOUT_SECONDS)
        return text if text else fallback_explanation(strategy)
    except Exception:
        return fallback_explanation(strategy)


def _gemini_explain(strategy: Strategy, top: dict, bottom: dict, jacket: dict | None) -> str:
    from backend import config
    from google import genai  # deferred: only needed on the Gemini path

    pieces = [top, bottom, *([jacket] if jacket else [])]
    colors = ", ".join(p["primary_color"]["name"] for p in pieces)

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = (
        f"In one short sentence, explain why a '{strategy.value}' outfit combining these "
        f"colors works, using color theory: {colors}. No preamble, no chat, exactly one sentence."
    )
    resp = client.models.generate_content(model=config.GEMINI_TEXT_MODEL, contents=prompt)
    return (getattr(resp, "text", None) or "").strip()
