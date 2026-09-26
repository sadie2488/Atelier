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


def fallback_explanation(strategy: Strategy) -> str:
    """Static per-strategy explanation (S-E3). Always non-empty for every ladder strategy."""
    return _FALLBACK[strategy]


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

    if not config.GEMINI_API_KEY:
        return fallback_explanation(strategy)

    key = _cache_key(strategy, top, bottom, jacket)
    with _cache_lock:
        cached = _cache.get(key)
    if cached:
        return cached

    future = _submit(strategy, top, bottom, jacket, key)
    try:
        text = future.result(timeout=config.GEMINI_TIMEOUT_SECONDS)
        return text if text else fallback_explanation(strategy)
    except Exception:
        return fallback_explanation(strategy)


def explain_many(requests: list[tuple[Strategy, dict, dict, dict | None]]) -> list[str]:
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
    pending: dict[Future, tuple[int, Strategy]] = {}

    for i, (strategy, top, bottom, jacket) in enumerate(requests):
        if not config.GEMINI_API_KEY:
            results[i] = fallback_explanation(strategy)
            continue

        key = _cache_key(strategy, top, bottom, jacket)
        with _cache_lock:
            cached = _cache.get(key)
        if cached:
            results[i] = cached
            continue

        future = _submit(strategy, top, bottom, jacket, key)
        pending[future] = (i, strategy)

    if pending:
        done, not_done = wait(pending.keys(), timeout=W.EXPLAIN_BUDGET_SECONDS)

        for future in done:
            i, strategy = pending[future]
            try:
                text = future.result()
            except Exception:
                text = None
            results[i] = text if text else fallback_explanation(strategy)

        for future in not_done:
            # Deliberately not cancelled/joined: it keeps running on the shared executor and,
            # if it eventually succeeds, its `_cache_if_successful` callback still populates
            # the cache for the next request -- but this response does not wait for it.
            i, strategy = pending[future]
            results[i] = fallback_explanation(strategy)

    return results


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
