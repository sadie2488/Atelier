"""Rank strategy candidates into the final outfit list (S-L1..S-L3).

Best score first, max `OUTFITS_MAX` total, max `OUTFITS_MAX_PER_STRATEGY` per strategy, max
`OUTFITS_MAX_SHARING_GARMENT` outfits sharing any one top or bottom (jackets exempt -- one
good jacket would otherwise starve the list). Returns fewer rather than padding (S-L2).

S4 (human request: "generate outfits should generate different ones each time"): which
*eligible* candidates get chosen is weighted-random-without-replacement rather than a fixed
greedy top-N, so repeat calls on the same closet can surface different (but still
rule-valid, still best-first-sorted) outfits. The scorer itself stays pure and deterministic
(S-C1) -- variety lives entirely here, in selection.
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter

from backend.styling import weights as W


def make_outfit_id(top_id: str, bottom_id: str, jacket_id: str | None) -> str:
    """Deterministic outfit_id from the combination: same combo -> same id, every run."""
    key = f"{top_id}|{bottom_id}|{jacket_id or ''}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]
    return f"outfit_{digest}"


def _fits_rules(c: dict, strategy_counts: Counter, garment_counts: Counter) -> bool:
    if strategy_counts[c["strategy"]] >= W.OUTFITS_MAX_PER_STRATEGY:
        return False
    if garment_counts[c["top_id"]] >= W.OUTFITS_MAX_SHARING_GARMENT:
        return False
    if garment_counts[c["bottom_id"]] >= W.OUTFITS_MAX_SHARING_GARMENT:
        return False
    return True


def _apply(c: dict, strategy_counts: Counter, garment_counts: Counter) -> None:
    strategy_counts[c["strategy"]] += 1
    garment_counts[c["top_id"]] += 1
    garment_counts[c["bottom_id"]] += 1
    # jacket_id intentionally not counted -- jackets are exempt from the sharing cap.


def _weighted_pick(rng: random.Random, weights: list[float]) -> int:
    """Index of one weighted-random pick among `weights` (all >= 0). Falls back to uniform
    if every weight is zero, so a pick is always made rather than raising."""
    total = sum(weights)
    if total <= 0:
        return rng.randrange(len(weights))
    r = rng.random() * total
    upto = 0.0
    for i, w in enumerate(weights):
        upto += w
        if upto >= r:
            return i
    return len(weights) - 1


def select_outfits(
    candidates: list[dict],
    limit: int,
    rng: random.Random | None = None,
    previous_ids: set[str] | None = None,
) -> list[dict]:
    """`candidates`: dicts with strategy, top_id, bottom_id, jacket_id, score (higher better).

    `rng`: injected for deterministic tests (pass a seeded `random.Random`); the route passes
    its own unseeded, process-local instance so real traffic varies run to run.

    `previous_ids` (outfit_id strings from the immediately preceding response, process-local
    memory kept by the caller -- the frontend sends no state): candidates matching one of
    these are excluded outright when there are enough fresh alternatives to fill `limit`
    without them, otherwise down-weighted rather than excluded, so a thin closet never returns
    fewer outfits just to avoid a repeat.

    Every existing selection rule (S-L1: <=2 per strategy, <=2 outfits sharing a top or
    bottom, jackets exempt; S-L2: fewer rather than padding) is enforced during sampling, not
    only during the deterministic top-up pass, and the result is always returned best-score-
    first (contract requirement), regardless of the order candidates were sampled in.
    """
    limit = min(limit, W.OUTFITS_MAX)
    if not candidates or limit <= 0:
        return []

    rng = rng if rng is not None else random.Random()
    previous_ids = previous_ids or set()

    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    best_score = ranked[0]["score"]
    margin_floor = best_score - W.VARIETY_POOL_MARGIN
    pool = [c for c in ranked if c["score"] >= W.VARIETY_MIN_SCORE or c["score"] >= margin_floor]

    def oid(c: dict) -> str:
        return make_outfit_id(c["top_id"], c["bottom_id"], c["jacket_id"])

    fresh = [c for c in pool if oid(c) not in previous_ids]
    exclude_repeats = len(fresh) >= limit
    work_pool = fresh if exclude_repeats else pool

    strategy_counts: Counter = Counter()
    garment_counts: Counter = Counter()
    chosen: list[dict] = []
    chosen_ids: set[str] = set()

    remaining = list(work_pool)
    while remaining and len(chosen) < limit:
        eligible = [i for i, c in enumerate(remaining) if _fits_rules(c, strategy_counts, garment_counts)]
        if not eligible:
            break
        weights = [
            max(remaining[i]["score"], 1e-6) ** W.VARIETY_SCORE_EXPONENT
            * (W.VARIETY_REPEAT_PENALTY if (not exclude_repeats and oid(remaining[i]) in previous_ids) else 1.0)
            for i in eligible
        ]
        pos = _weighted_pick(rng, weights)
        idx = eligible[pos]
        c = remaining.pop(idx)
        chosen.append(c)
        chosen_ids.add(oid(c))
        _apply(c, strategy_counts, garment_counts)

    if len(chosen) < limit:
        # Not enough fresh, rule-valid candidates in the sampled pool -- top up deterministically
        # from the full ranked list (including previously-shown combos and below-floor ones) so
        # we never return fewer outfits than the closet can actually support (S-L2/S-L3 still
        # win over "avoid a repeat" or "stay within the quality floor").
        for c in ranked:
            if len(chosen) >= limit:
                break
            if oid(c) in chosen_ids:
                continue
            if not _fits_rules(c, strategy_counts, garment_counts):
                continue
            chosen.append(c)
            chosen_ids.add(oid(c))
            _apply(c, strategy_counts, garment_counts)

    chosen.sort(key=lambda c: c["score"], reverse=True)
    return chosen
