"""Pure pairwise color-harmony scoring (S-C1): no DB, network, or file I/O in this module.
Same inputs always produce the same score.

Operates on numeric color only (S-C2): hue and chroma come from the stored `lch` tuple
(L, chroma, hue-degrees), family/is_neutral/everyday_neutral are read as already stored on
the item -- never recomputed from contract/colors.json here. Every tunable number lives in
`weights.py` (S-T1).

Inputs are plain dicts shaped like `contract.schemas.ExtractedColor` / `Item` (via
`.model_dump()`), not pydantic instances -- keeps this module dependency-free and easy to
unit test with bare fixtures.
"""
from __future__ import annotations

from backend.styling import weights as W


def hue_diff(h1: float, h2: float) -> float:
    """Circular distance between two hue angles in degrees, in [0, 180]."""
    d = abs(h1 - h2) % 360
    return d if d <= 180 else 360 - d


def score_color_pair(a: dict, b: dict) -> float:
    """Harmony score in [0, 1] for two ExtractedColor-shaped dicts (S-C2)."""
    if a["is_neutral"] or b["is_neutral"]:
        return W.NEUTRAL_PAIR_SCORE

    if a["family"] == b["family"]:
        l_spread = abs(a["lch"][0] - b["lch"][0])
        bonus = W.MONOCHROME_L_BONUS * min(l_spread / W.MONOCHROME_L_SPREAD_TARGET, 1.0)
        return min(W.MONOCHROME_BASE + bonus, 1.0)

    diff = hue_diff(a["lch"][2], b["lch"][2])

    if diff <= W.HUE_ANALOGOUS_MAX_DEG:
        penalty = W.ANALOGOUS_HUE_PENALTY * (diff / W.HUE_ANALOGOUS_MAX_DEG)
        return max(W.ANALOGOUS_BASE_SCORE - penalty, 0.0)

    if W.HUE_COMPLEMENTARY_MIN_DEG <= diff <= W.HUE_COMPLEMENTARY_MAX_DEG:
        low_chroma = a["lch"][1] < W.COMPLEMENTARY_LOW_CHROMA_MAX or b["lch"][1] < W.COMPLEMENTARY_LOW_CHROMA_MAX
        return W.COMPLEMENTARY_SCORE if low_chroma else W.COMPLEMENTARY_SCORE * W.COMPLEMENTARY_HIGH_CHROMA_PENALTY

    if a["everyday_neutral"] or b["everyday_neutral"]:
        return W.EVERYDAY_NEUTRAL_PAIR_SCORE

    return W.DEFAULT_PAIR_SCORE


def score_items(item_a: dict, item_b: dict) -> float:
    """Harmony between two items' colors (S-C3, S-C4).

    Primary colors always count at full weight. A secondary color, if present, contributes
    an additional weighted term (S-C3) -- it is never a penalty and never required: an item
    with no secondary_color (or no `attributes`) is scored purely on its primary color and
    must never rank below an otherwise identical item that happens to carry more data (S-C4).
    """
    weighted_sum = score_color_pair(item_a["primary_color"], item_b["primary_color"])
    total_weight = 1.0

    sec_a = item_a.get("secondary_color")
    sec_b = item_b.get("secondary_color")

    if sec_a is not None:
        weighted_sum += W.SECONDARY_COLOR_WEIGHT * score_color_pair(sec_a, item_b["primary_color"])
        total_weight += W.SECONDARY_COLOR_WEIGHT
    if sec_b is not None:
        weighted_sum += W.SECONDARY_COLOR_WEIGHT * score_color_pair(item_a["primary_color"], sec_b)
        total_weight += W.SECONDARY_COLOR_WEIGHT
    if sec_a is not None and sec_b is not None:
        w = W.SECONDARY_COLOR_WEIGHT * W.SECONDARY_COLOR_WEIGHT
        weighted_sum += w * score_color_pair(sec_a, sec_b)
        total_weight += w

    return weighted_sum / total_weight
