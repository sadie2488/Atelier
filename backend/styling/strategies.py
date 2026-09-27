"""Named outfit generators, in ship order (S-S1, S-S2):

    1. neutral_anchor          -- always eligible; guarantees non-empty results.
    2. everyday_neutral_base   -- the demo, alongside rung 1.
    3. analogous / complementary
    4. monochrome_highlight    -- same family, L* spread wide enough not to read flat.
    5. sandwich                -- requires a jacket; jacket+bottom share a family, top contrasts.

A strategy whose eligibility is unmet for a given pair stays silent (S-S3): it never
degrades into a different strategy or emits low-confidence filler.

S-O1: every outfit is bottom + (top or dress) + optional jacket. `category == "tops"` covers
shirts and dresses alike; there is no dress special case anywhere in this module (S-O2).
"""
from __future__ import annotations

from contract.enums import Strategy

from backend.styling import weights as W
from backend.styling.scorer import hue_diff, score_items


def _classify_pair(top: dict, bottom: dict):
    """First ladder rung a top+bottom pair satisfies, if any -- (Strategy, score) or None.

    Checked in ladder priority order so a pair eligible for more than one rung is still
    labeled once. This matters beyond tidiness: the contract forbids the same combination
    appearing twice in a response, so a pair must resolve to exactly one strategy.
    """
    t, b = top["primary_color"], bottom["primary_color"]

    # Rung 1: neutral_anchor -- one piece strict neutral (V-C5 chroma rule), the other not.
    if t["is_neutral"] != b["is_neutral"]:
        return Strategy.neutral_anchor, score_items(top, bottom)

    if t["is_neutral"] or b["is_neutral"]:
        # both strict neutral (e.g. black + white) -- not a ladder rung this lane implements.
        return None

    # Rung 2: everyday_neutral_base -- one piece is an everyday-neutral base color
    # (navy/denim/olive/camel/beige/brown), the other a true chromatic partner.
    if t["everyday_neutral"] != b["everyday_neutral"]:
        return Strategy.everyday_neutral_base, score_items(top, bottom)

    # Rung 4: monochrome_highlight -- both pieces share a family (the analogous/complementary
    # branch below only fires when families differ), so this is the family-same counterpart:
    # eligible once the L* spread is wide enough that the pairing reads as deliberately tonal
    # rather than flat (S-S2 rung 4). The optional jacket layer, handled generically below via
    # `_jacket_variants`, is the "plus one optional accent piece".
    if t["family"] == b["family"]:
        l_spread = abs(t["lch"][0] - b["lch"][0])
        if l_spread >= W.MONOCHROME_HIGHLIGHT_MIN_L_SPREAD:
            return Strategy.monochrome_highlight, score_items(top, bottom)
        return None

    # Rung 3: analogous / complementary -- both chromatic-of-the-same-kind (both bases, or
    # both true chromatics), different families, related by hue angle.
    diff = hue_diff(t["lch"][2], b["lch"][2])
    if diff <= W.HUE_ANALOGOUS_MAX_DEG:
        return Strategy.analogous, score_items(top, bottom)
    if W.HUE_COMPLEMENTARY_MIN_DEG <= diff <= W.HUE_COMPLEMENTARY_MAX_DEG:
        low_chroma = (
            t["lch"][1] < W.COMPLEMENTARY_LOW_CHROMA_MAX or b["lch"][1] < W.COMPLEMENTARY_LOW_CHROMA_MAX
        )
        if low_chroma:
            return Strategy.complementary, score_items(top, bottom)

    return None


def _classify_sandwich(top: dict, bottom: dict, jacket: dict) -> Strategy | None:
    """Rung 5 (S-S2): sandwich needs three visible color slots, so it is only reachable when a
    jacket is present -- there is no "no jacket" variant of this strategy. The jacket and
    bottom (the two "bread" pieces) must share a family; the top (the "filling") must be a
    different family, per the frozen family buckets in `contract/colors.json` -- no additional
    hue-angle tunable is introduced here, since family is already the ladder's existing
    same-vs-different-family boundary (mirroring rung 4's own family-based gate above).
    """
    j, b, t = jacket["primary_color"], bottom["primary_color"], top["primary_color"]
    if j["family"] != b["family"]:
        return None
    if t["family"] == j["family"]:
        return None
    return Strategy.sandwich


def _jacket_variants(top: dict, bottom: dict, jackets: list[dict]):
    """Optional jacket layer (S-O3). Yields None (no jacket) then any jacket that doesn't
    visibly clash with the base pairing -- a jacket below the compatibility bar is silently
    skipped for that combination, not scored as a poor outfit.
    """
    yield None
    for jacket in jackets:
        compat = (score_items(jacket, top) + score_items(jacket, bottom)) / 2
        if compat >= W.JACKET_MIN_COMPATIBILITY:
            yield jacket


def _combine_with_jacket(base_score: float, jacket: dict, top: dict, bottom: dict) -> float:
    jacket_score = (score_items(jacket, top) + score_items(jacket, bottom)) / 2
    return (
        (W.PRIMARY_PAIR_WEIGHT * base_score + W.JACKET_PAIR_WEIGHT * jacket_score)
        / (W.PRIMARY_PAIR_WEIGHT + W.JACKET_PAIR_WEIGHT)
    )


def generate_candidates(tops: list[dict], bottoms: list[dict], jackets: list[dict]):
    """Yield (strategy, top, bottom, jacket_or_None, score) for every eligible combination.

    Every outfit shape is bottom + (top or dress) + optional jacket (S-O1); `tops` already
    contains both shirts and dresses, so there is nothing dress-specific here (S-O2).
    """
    for top in tops:
        for bottom in bottoms:
            classified = _classify_pair(top, bottom)
            if classified is not None:
                strategy, base_score = classified
                for jacket in _jacket_variants(top, bottom, jackets):
                    if jacket is None:
                        yield strategy, top, bottom, None, base_score
                        continue
                    combined = _combine_with_jacket(base_score, jacket, top, bottom)
                    yield strategy, top, bottom, jacket, combined
                continue

            # Rung 5: sandwich -- only reached when no higher-priority rung (1-4) claims this
            # top+bottom pair on its own (S-S2 ladder priority keeps a pair labeled once).
            # There is no jacket-less variant: the strategy needs the jacket for its third
            # color slot, so a closet with no suitable jacket leaves it silently dormant (S-S3).
            base_score = score_items(top, bottom)
            for jacket in jackets:
                if _classify_sandwich(top, bottom, jacket) is None:
                    continue
                combined = _combine_with_jacket(base_score, jacket, top, bottom)
                yield Strategy.sandwich, top, bottom, jacket, combined
