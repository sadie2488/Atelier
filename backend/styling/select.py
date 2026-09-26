"""Rank strategy candidates into the final outfit list (S-L1..S-L3).

Best score first, max `OUTFITS_MAX` total, max `OUTFITS_MAX_PER_STRATEGY` per strategy, max
`OUTFITS_MAX_SHARING_GARMENT` outfits sharing any one top or bottom (jackets exempt -- one
good jacket would otherwise starve the list). Returns fewer rather than padding (S-L2).
"""
from __future__ import annotations

import hashlib
from collections import Counter

from backend.styling import weights as W


def make_outfit_id(top_id: str, bottom_id: str, jacket_id: str | None) -> str:
    """Deterministic outfit_id from the combination: same combo -> same id, every run."""
    key = f"{top_id}|{bottom_id}|{jacket_id or ''}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]
    return f"outfit_{digest}"


def select_outfits(candidates: list[dict], limit: int) -> list[dict]:
    """`candidates`: dicts with strategy, top_id, bottom_id, jacket_id, score (higher better).

    Ties keep the candidates' incoming relative order (stable sort), which is itself
    deterministic given a stable items order -- so results are reproducible run to run.
    """
    limit = min(limit, W.OUTFITS_MAX)
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)

    chosen: list[dict] = []
    strategy_counts: Counter = Counter()
    garment_counts: Counter = Counter()

    for c in ranked:
        if len(chosen) >= limit:
            break
        if strategy_counts[c["strategy"]] >= W.OUTFITS_MAX_PER_STRATEGY:
            continue
        if garment_counts[c["top_id"]] >= W.OUTFITS_MAX_SHARING_GARMENT:
            continue
        if garment_counts[c["bottom_id"]] >= W.OUTFITS_MAX_SHARING_GARMENT:
            continue

        chosen.append(c)
        strategy_counts[c["strategy"]] += 1
        garment_counts[c["top_id"]] += 1
        garment_counts[c["bottom_id"]] += 1

    return chosen
