"""Outfit explanations (S-E1..S-E5).

Gemini writes the explanation from the strategy label and the outfit's colors; it never
re-ranks (S-E1, out of scope per S-X2) and never blocks or delays the response (S-E4) --
calls run under a hard timeout and any failure (no key, network, timeout, empty text) falls
back to a static per-strategy explanation (S-E3), which is what ships first per the lane's
priority order.

`explain_many` is what the route uses: it dispatches every outfit's Gemini call concurrently
against the shared executor and waits on ONE deadline for the whole batch
(`weights.EXPLAIN_BUDGET_SECONDS`), so a slow or hanging Gemini never multiplies latency by
the outfit count. Stragglers past the deadline are left running in the background (the
executor is module-level and never joined on exit) and just fall back for that response; if
one later succeeds anyway, its result is cached for the next request with the same
combination.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait

from contract.enums import Strategy

_FALLBACK: dict[Strategy, str] = {
    Strategy.neutral_anchor: "A neutral piece anchors the look, so the colorful piece can lead.",
    Strategy.everyday_neutral_base: "An easy neutral base pairs cleanly with this color.",
    Strategy.analogous: "These colors sit close together on the color wheel for a soft, unified look.",
    Strategy.complementary: "These colors sit opposite each other on the color wheel for deliberate contrast.",
    Strategy.monochrome_highlight: "One color family, played across light and dark, with a highlight piece.",
    Strategy.sandwich: "The jacket and bottom share a color, sandwiching a contrasting top between them.",
}

# Not a `with` block: we never want to join outstanding work on exit, since a hung Gemini
# call would then block interpreter shutdown/module teardown the same way it must never block
# a response. Sized so a full batch (OUTFITS_MAX outfits) can all run at once rather than
# queueing behind each other inside the shared budget.
_executor = ThreadPoolExecutor(max_workers=8)

# In-process cache of successful Gemini explanations, keyed by (strategy, piece color names).
# A repeated combination is instant and costs no quota.
_cache: dict[tuple, str] = {}
_cache_lock = threading.Lock()


_SANDWICH_SAME_FAMILY = (
    "The jacket and bottom are both {words}, framing a contrasting top between them."
)


def _loose_sandwich(strategy: Strategy, bottom: dict | None, jacket: dict | None) -> bool:
    """True for a sandwich whose jacket and bottom share only a family, not a visibly similar
    color (e.g. black jacket + light-gray jeans): "share a color" would be false there."""
    if strategy != Strategy.sandwich or not bottom or not jacket:
        return False
    from contract.tools.color import delta_e2000
    from backend.styling import weights as W

    de = delta_e2000(tuple(jacket["primary_color"]["lab"]), tuple(bottom["primary_color"]["lab"]))
    return de > W.EXPLAIN_SHARED_COLOR_MAX_DELTA_E


def fallback_explanation(
    strategy: Strategy, top: dict | None = None, bottom: dict | None = None, jacket: dict | None = None
) -> str:
    """Static per-strategy explanation (S-E3). Always non-empty for every ladder strategy.
    With the pieces given, a sandwich only claims a shared color when the jacket and bottom
    colors are actually close (weights.EXPLAIN_SHARED_COLOR_MAX_DELTA_E)."""
    if _loose_sandwich(strategy, bottom, jacket):
        fam = jacket["primary_color"]["family"]
        words = "neutrals" if fam == "achromatic" else f"{fam.replace('_', ' ')} tones"
        return _SANDWICH_SAME_FAMILY.format(words=words)
    return _FALLBACK[strategy]


def guided_fallback(
    strategy: Strategy, top: dict | None = None, bottom: dict | None = None, jacket: dict | None = None
) -> str:
    """Deterministic explanation (no Gemini configured): the strategy fallback plus, only when
    the colour-dressing guide lists the top+bottom pair, one plain sentence saying so."""
    base = fallback_explanation(strategy, top, bottom, jacket)
    if top is None or bottom is None:
        return base
    from backend.styling.pairing_guide import guide_sentence

    try:
        extra = guide_sentence(top, bottom)
    except Exception:
        extra = None
    return f"{base} {extra}" if extra else base


def _cache_key(strategy: Strategy, top: dict, bottom: dict, jacket: dict | None) -> tuple:
    pieces = [top, bottom, *([jacket] if jacket else [])]
    names = tuple(p["primary_color"]["name"] for p in pieces)
    return (strategy, names)


def _submit(strategy: Strategy, top: dict, bottom: dict, jacket: dict | None, key: tuple) -> Future:
    future = _executor.submit(_gemini_explain, strategy, top, bottom, jacket)

    def _cache_if_successful(f: Future) -> None:
        try:
            text = f.result()
        except Exception:
            return
        if text:
            with _cache_lock:
                _cache[key] = text

    future.add_done_callback(_cache_if_successful)
    return future


def explain(strategy: Strategy, top: dict, bottom: dict, jacket: dict | None) -> str:
    """Best-effort Gemini explanation for a single outfit; always returns promptly and
    non-empty (S-E4). Prefer `explain_many` when explaining a batch of outfits."""
    from backend import config

    if not config.GEMINI_API_KEY or _loose_sandwich(strategy, bottom, jacket):
        return fallback_explanation(strategy, top, bottom, jacket)

    key = _cache_key(strategy, top, bottom, jacket)
    with _cache_lock:
        cached = _cache.get(key)
    if cached:
        return cached

    future = _submit(strategy, top, bottom, jacket, key)
    try:
        text = future.result(timeout=config.GEMINI_TIMEOUT_SECONDS)
        return text if text else fallback_explanation(strategy, top, bottom, jacket)
    except Exception:
        return fallback_explanation(strategy, top, bottom, jacket)


def _with_lead(lead: str | None, text: str) -> str:
    """Style preset lead on a deterministic explanation: "A smart business look: an easy ..."."""
    if not lead or not text:
        return text
    return f"{lead}: {text[0].lower()}{text[1:]}"


def explain_many(
    requests: list[tuple[Strategy, dict, dict, dict | None]], lead: str | None = None
) -> list[str]:
    """Best-effort Gemini explanations for a whole batch of outfits (S-E4): every request is
    dispatched concurrently and the batch waits on a single shared deadline
    (`weights.EXPLAIN_BUDGET_SECONDS`), so total latency does not grow with the outfit count.
    Any request not finished by the deadline (or already cached) resolves immediately; any
    exception or empty text falls back to `fallback_explanation`. Returns one explanation per
    input request, in order.
    """
    from backend import config
    from backend.styling import weights as W

    results: list[str | None] = [None] * len(requests)
    pending: dict[Future, int] = {}

    def _fb(i: int) -> str:
        return _with_lead(lead, fallback_explanation(*requests[i]))

    for i, (strategy, top, bottom, jacket) in enumerate(requests):
        # A family-only sandwich stays deterministic: Gemini told "sandwich" tends to claim a
        # shared color that isn't there.
        if not config.GEMINI_API_KEY or _loose_sandwich(strategy, bottom, jacket):
            results[i] = _with_lead(lead, guided_fallback(*requests[i]))
            continue

        key = _cache_key(strategy, top, bottom, jacket)
        with _cache_lock:
            cached = _cache.get(key)
        if cached:
            results[i] = cached
            continue

        future = _submit(strategy, top, bottom, jacket, key)
        pending[future] = i

    if pending:
        done, not_done = wait(pending.keys(), timeout=W.EXPLAIN_BUDGET_SECONDS)

        for future in done:
            i = pending[future]
            try:
                text = future.result()
            except Exception:
                text = None
            results[i] = text if text else _fb(i)

        for future in not_done:
            # Deliberately not cancelled/joined: it keeps running on the shared executor and,
            # if it eventually succeeds, its `_cache_if_successful` callback still populates
            # the cache for the next request -- but this response does not wait for it.
            i = pending[future]
            results[i] = _fb(i)

    return results


def _gemini_explain(strategy: Strategy, top: dict, bottom: dict, jacket: dict | None) -> str:
    from backend import config
    from google import genai  # deferred: only needed on the Gemini path

    pieces = [top, bottom, *([jacket] if jacket else [])]
    colors = ", ".join(p["primary_color"]["name"] for p in pieces)

    from backend.styling.pairing_guide import guide_sentence

    try:
        hint = guide_sentence(top, bottom)
    except Exception:
        hint = None
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = (
        f"In one short sentence, explain why a '{strategy.value}' outfit combining these "
        f"colors works, using color theory: {colors}. No preamble, no chat, exactly one sentence."
    )
    if hint:
        prompt += f" A colour-dressing guide lists this pairing: {hint}"
    resp = client.models.generate_content(model=config.GEMINI_TEXT_MODEL, contents=prompt)
    return (getattr(resp, "text", None) or "").strip()
