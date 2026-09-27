"""Style presets for POST /outfits/generate (contract 2.5.0, `OutfitsGenerateRequest.style`).

A preset narrows the candidate pool BEFORE the variety pick; it never changes a score, a
strategy label, or the selection caps. Tiers relax gradually so a valid request never comes
back empty just because the closet lacks the style: every piece matches -> at most one piece
off -> any candidate.

Formality styles (casual / business / going_out) match on the item's free-form
`attributes.formality` (case-insensitive); an item with no formality falls back to keywords
on subcategory/material; an unknown formality word simply doesn't match. Monochrome matches
when every piece shares a color family (all strict neutrals count as one tonal family).
"""
from __future__ import annotations

from contract.enums import OutfitStyle, Strategy

from backend.styling import weights as W
from backend.styling.pairing_guide import pair_adjustment
from backend.styling.scorer import score_items

STYLE_FORMALITY = {
    OutfitStyle.casual: "casual",
    OutfitStyle.business: "smart",
    OutfitStyle.going_out: "dressy",
}

STYLE_LEAD = {
    OutfitStyle.casual: "An easy casual look",
    OutfitStyle.business: "A smart business look",
    OutfitStyle.going_out: "A dressed-up going-out look",
    OutfitStyle.monochrome: "A tonal monochrome look",
}

# Keyword fallback for items with no formality attribute, checked in this order (so "t-shirt"
# reads casual before "shirt" reads smart).
_KEYWORDS = (
    ("dressy", ("satin", "silk", "slip", "cami", "sequin", "velvet", "gown", "lace")),
    ("casual", ("t-shirt", "tee", "jean", "denim", "hoodie", "sweat", "cardigan", "sweater",
                "jogger", "legging", "utility", "fleece", "jersey")),
    ("smart", ("shirt", "blazer", "trouser", "slack", "coat", "turtleneck", "tailored", "chino",
               "suit", "blouse")),
    ("dressy", ("skirt", "dress")),
)

# Business never wants these, even when mislabeled smart.
_BUSINESS_VETO = ("t-shirt", "tee", "slip", "cami")


def _attr(item: dict, key: str) -> str:
    v = (item.get("attributes") or {}).get(key)
    return v.strip().lower() if isinstance(v, str) else ""


def formality(item: dict) -> str | None:
    """The item's formality word (lowercased), inferred from keywords only when missing."""
    f = _attr(item, "formality")
    if f:
        return f
    text = f"{_attr(item, 'subcategory')} {_attr(item, 'material')}"
    if not text.strip():
        return None
    for word, keys in _KEYWORDS:
        if any(k in text for k in keys):
            return word
    return None


def item_matches(style: OutfitStyle, item: dict) -> bool:
    text = f"{_attr(item, 'subcategory')} {_attr(item, 'material')}"
    if style == OutfitStyle.business and any(k in text for k in _BUSINESS_VETO):
        return False
    if style == OutfitStyle.going_out:
        if item.get("category") == "jackets" and "leather" in text:
            return True
        if "jean" in text and (item.get("primary_color") or {}).get("name") == "black":
            return True
    return formality(item) == STYLE_FORMALITY.get(style)


def _family_key(item: dict) -> str:
    c = item["primary_color"]
    return "neutral" if c["is_neutral"] else c["family"]


def mismatches(style: OutfitStyle, c: dict) -> int:
    """How many of the candidate's pieces are off-style."""
    pieces = [c["top"], c["bottom"], *([c["jacket"]] if c["jacket"] else [])]
    if style == OutfitStyle.monochrome:
        keys = [_family_key(p) for p in pieces]
        return len(keys) - max(keys.count(k) for k in set(keys))
    return sum(0 if item_matches(style, p) else 1 for p in pieces)


def tonal_extras(tops: list[dict], bottoms: list[dict], jackets: list[dict]) -> list[dict]:
    """All-neutral tonal pairs (e.g. black cami + white skirt) the color ladder leaves silent,
    offered only to style presets, labeled monochrome_highlight and gated by the same L*
    spread that rung needs. Optional jacket: another strict neutral."""
    out = []
    for top in tops:
        for bottom in bottoms:
            t, b = top["primary_color"], bottom["primary_color"]
            if not (t["is_neutral"] and b["is_neutral"]):
                continue
            if abs(t["lch"][0] - b["lch"][0]) < W.MONOCHROME_HIGHLIGHT_MIN_L_SPREAD:
                continue
            base = score_items(top, bottom) + pair_adjustment(top, bottom)
            for jacket in [None, *[j for j in jackets if j["primary_color"]["is_neutral"]]]:
                score = base
                if jacket is not None:
                    js = (score_items(jacket, top) + score_items(jacket, bottom)) / 2
                    score = (
                        (W.PRIMARY_PAIR_WEIGHT * base + W.JACKET_PAIR_WEIGHT * js)
                        / (W.PRIMARY_PAIR_WEIGHT + W.JACKET_PAIR_WEIGHT)
                    )
                out.append({
                    "strategy": Strategy.monochrome_highlight,
                    "top": top, "bottom": bottom, "jacket": jacket,
                    "top_id": top["id"], "bottom_id": bottom["id"],
                    "jacket_id": jacket["id"] if jacket else None,
                    "score": max(0.0, min(1.0, score)),
                })
    return out


def styled_pick(style: OutfitStyle, candidates: list[dict], limit: int, select) -> list[dict]:
    """Variety pick restricted to the strictest non-empty tier (0, then 1 off-style piece,
    then any). `select(pool, limit)` is the route's select_outfits."""
    for max_off in (0, 1):
        pool = [c for c in candidates if mismatches(style, c) <= max_off]
        chosen = select(pool, limit)
        if chosen:
            return chosen
    return select(candidates, limit)
