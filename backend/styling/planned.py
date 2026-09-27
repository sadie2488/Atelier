"""Demo planned outfits (human decision: the demo's "generate outfit" shows two planned
outfits, in order, on the judge's own scan).

`ATELIER_DEMO_OUTFITS` = "top_id,bottom_id[,jacket_id];top_id,bottom_id[,jacket_id]"
(whitespace-tolerant). Unset/empty -> no planned outfits and the route behaves exactly as
before. Malformed entries are skipped with a logged warning; this module never raises.

Also holds `plan_outfit()`, which builds a candidate dict for a planned combination through
the normal scoring path (strategy + score from the scorer when it produced that combination,
else scored with the existing scoring functions and given the best-fitting strategy label).
"""
from __future__ import annotations

import logging
import os
import threading

from contract.enums import Strategy

from backend.styling import weights as W
from backend.styling.pairing_guide import pair_adjustment
from backend.styling.scorer import hue_diff, score_items
from backend.styling.strategies import _classify_pair, _classify_sandwich, _combine_with_jacket

log = logging.getLogger(__name__)

ENV_VAR = "ATELIER_DEMO_OUTFITS"

_counter_lock = threading.Lock()
_counter = 0


def planned_outfits() -> list[tuple[str, str, str | None]]:
    """Parse ATELIER_DEMO_OUTFITS into [(top_id, bottom_id, jacket_id|None), ...]."""
    try:
        raw = os.environ.get(ENV_VAR, "") or ""
    except Exception:  # pragma: no cover - defensive
        return []
    out: list[tuple[str, str, str | None]] = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split(",")]
        if len(parts) not in (2, 3) or not parts[0] or not parts[1] or (len(parts) == 3 and not parts[2]):
            log.warning("%s: skipping malformed entry %r", ENV_VAR, entry)
            continue
        out.append((parts[0], parts[1], parts[2] if len(parts) == 3 else None))
    return out


def next_planned_index(n: int) -> int:
    """Process-local rotation: call 1 -> 0, call 2 -> 1, ... cycling over n entries."""
    global _counter
    with _counter_lock:
        idx = _counter % n
        _counter += 1
    return idx


def reset_rotation() -> None:
    """Tests only."""
    global _counter
    with _counter_lock:
        _counter = 0


def _fallback_strategy(top: dict, bottom: dict, jacket: dict | None) -> Strategy:
    """Best-fitting label for a combination no ladder rung claimed."""
    if jacket is not None and _classify_sandwich(top, bottom, jacket) is not None:
        return Strategy.sandwich
    t, b = top["primary_color"], bottom["primary_color"]
    if t["is_neutral"] or b["is_neutral"]:
        return Strategy.neutral_anchor
    if t["everyday_neutral"] or b["everyday_neutral"]:
        return Strategy.everyday_neutral_base
    if t["family"] == b["family"]:
        return Strategy.monochrome_highlight
    diff = hue_diff(t["lch"][2], b["lch"][2])
    if diff <= W.HUE_ANALOGOUS_MAX_DEG:
        return Strategy.analogous
    if diff >= W.HUE_COMPLEMENTARY_MIN_DEG:
        return Strategy.complementary
    return Strategy.neutral_anchor


def plan_outfit(entry, items: list[dict], candidates: list[dict]) -> dict | None:
    """Candidate dict for a planned entry, or None (warning logged) if any id is missing or
    in the wrong category."""
    top_id, bottom_id, jacket_id = entry
    by_id = {i["id"]: i for i in items}
    top, bottom = by_id.get(top_id), by_id.get(bottom_id)
    jacket = by_id.get(jacket_id) if jacket_id else None
    if (
        top is None or top["category"] != "tops"
        or bottom is None or bottom["category"] != "bottoms"
        or (jacket_id and (jacket is None or jacket["category"] != "jackets"))
    ):
        log.warning("%s: planned outfit %r not in closet; using normal generation", ENV_VAR, entry)
        return None

    for c in candidates:
        if c["top_id"] == top_id and c["bottom_id"] == bottom_id and c["jacket_id"] == jacket_id:
            return c

    try:
        classified = _classify_pair(top, bottom)
        if classified is not None:
            strategy, base = classified
            base += pair_adjustment(top, bottom)
        else:
            base = score_items(top, bottom) + pair_adjustment(top, bottom)
            strategy = _fallback_strategy(top, bottom, jacket)
        if strategy == Strategy.sandwich and jacket is None:
            strategy = _fallback_strategy(top, bottom, None)
        score = _combine_with_jacket(base, jacket, top, bottom) if jacket is not None else base
    except Exception:
        log.warning("%s: could not score planned outfit %r", ENV_VAR, entry, exc_info=True)
        return None

    return {
        "strategy": strategy,
        "top": top,
        "bottom": bottom,
        "jacket": jacket,
        "top_id": top_id,
        "bottom_id": bottom_id,
        "jacket_id": jacket_id,
        "score": max(0.0, min(1.0, score)),
    }
