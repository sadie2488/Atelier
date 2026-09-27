"""Colour-dressing guide ("A Pair & A Spare, Wardrobe Rehab colour dressing guide") as data,
plus the seasonal (12-season chart) palette read used by insights.

Pure: no DB, network or file I/O. Stored Lab colors are mapped to the guide's named colors by
nearest reference swatch (CIEDE2000); denim is special-cased (light wash -> light blue, dark /
indigo -> navy, black jeans fall to black by nearest swatch). Thresholds live in weights.py.
"""
from __future__ import annotations

from functools import lru_cache

from contract.tools.color import delta_e2000, hex_to_lab, lab_to_lch

from backend.styling import weights as W

# Reference swatches, sampled from the chart ("beige" covers the chart's beige and cream).
GUIDE_SWATCHES: dict[str, tuple[str, ...]] = {
    "pink": ("#f4c2c2", "#f8b9b4"),
    "red": ("#d32027", "#d0454a"),
    "orange": ("#f05a28",),
    "beige": ("#f5eedc", "#faf3e1", "#d8c3a0"),
    "yellow": ("#fdd835",),
    "green": ("#00843d",),
    "dark green": ("#145a32",),
    "light blue": ("#c9e0f2",),
    "navy": ("#1b2a5a", "#1f4e79"),
    # Muted mauve from the chart plus violet/plum swatches: with only the mauve, a saturated
    # purple (hue ~313) sat nearer the navy swatch and was described as "navy".
    "purple": ("#7a4a63", "#5b2a86", "#6a3d9a", "#8e44ad", "#4b2a6b"),
    "burgundy": ("#612a44",),
    "brown": ("#5a3a2e", "#6b4a3e"),
    "grey": ("#a9a9a9", "#b0b7bf", "#6e6e6e"),
    "white": ("#ffffff", "#f2f2f2"),
    "black": ("#000000", "#262626"),
}

# MAIN -> (complementary pairings, tonal pairings), transcribed from the chart.
GUIDE_TABLE: dict[str, tuple[frozenset, frozenset]] = {
    "pink": (frozenset({"light blue", "navy", "grey", "white", "black"}), frozenset({"red", "beige"})),
    "red": (frozenset({"light blue", "navy", "grey", "white", "black"}), frozenset({"pink", "beige"})),
    "orange": (frozenset({"dark green", "light blue", "navy", "white", "black"}), frozenset({"beige", "brown"})),
    "beige": (frozenset({"navy", "burgundy", "brown", "white", "black"}), frozenset({"yellow", "orange"})),
    "yellow": (frozenset({"dark green", "navy", "white", "black"}), frozenset({"beige"})),
    "green": (frozenset({"orange", "burgundy", "white", "black"}), frozenset({"yellow", "light blue"})),
    "light blue": (frozenset({"pink", "red", "orange", "white", "black"}), frozenset({"navy", "burgundy"})),
    "navy": (frozenset({"pink", "red", "yellow", "grey", "white", "black"}), frozenset({"light blue", "burgundy"})),
    "purple": (frozenset({"orange", "grey", "green", "white", "black"}), frozenset({"light blue", "navy"})),
    "brown": (frozenset({"beige", "white", "black"}), frozenset({"orange"})),
    "grey": (frozenset({"pink", "red", "navy", "burgundy"}), frozenset({"white", "black"})),
}

# Colors the guide treats as go-with-anything bases: an unlisted pair containing one is
# "neutral" (no bonus, no penalty) rather than a clash.
GUIDE_NEUTRALS = frozenset({"white", "black", "grey", "beige"})

BOTTOM_TYPES = frozenset({"pants", "shorts", "skirt"})


@lru_cache(maxsize=1)
def _reference_labs() -> tuple[tuple[str, tuple[float, float, float]], ...]:
    return tuple((name, hex_to_lab(h)) for name, hexes in GUIDE_SWATCHES.items() for h in hexes)


def _gt(garment_type) -> str | None:
    return getattr(garment_type, "value", garment_type)


def guide_color(lab, garment_type=None) -> str:
    """The guide's named color nearest a stored Lab color (denim special-cased for bottoms)."""
    lab = tuple(float(v) for v in lab)
    L, C, h = lab_to_lch(lab)
    if _gt(garment_type) in BOTTOM_TYPES and C >= W.DENIM_MIN_CHROMA and W.DENIM_HUE_MIN_DEG <= h <= W.DENIM_HUE_MAX_DEG:
        return "light blue" if L > W.DENIM_LIGHT_L_MIN else "navy"
    return min(_reference_labs(), key=lambda nl: delta_e2000(lab, nl[1]))[0]


def item_guide_color(item: dict) -> str:
    return guide_color(item["primary_color"]["lab"], item.get("garment_type"))


def pair_quality(a: str, b: str) -> str:
    """"complementary" | "tonal" | "neutral" | "none" for two guide color names (symmetric:
    the pair counts if either color's row lists the other)."""
    comp_a, tonal_a = GUIDE_TABLE.get(a, (frozenset(), frozenset()))
    comp_b, tonal_b = GUIDE_TABLE.get(b, (frozenset(), frozenset()))
    if b in comp_a or a in comp_b:
        return "complementary"
    if b in tonal_a or a in tonal_b:
        return "tonal"
    if a in GUIDE_NEUTRALS or b in GUIDE_NEUTRALS:
        return "neutral"
    return "none"


def item_pair_quality(item_a: dict, item_b: dict) -> str:
    return pair_quality(item_guide_color(item_a), item_guide_color(item_b))


_ADJUST = {
    "complementary": "GUIDE_COMPLEMENTARY_BONUS",
    "tonal": "GUIDE_TONAL_BONUS",
    "neutral": "GUIDE_NEUTRAL_BONUS",
    "none": "GUIDE_UNLISTED_PENALTY",
}


def pair_adjustment(item_a: dict, item_b: dict) -> float:
    """Score adjustment (weights.py) for what the guide says about two items."""
    return getattr(W, _ADJUST[item_pair_quality(item_a, item_b)])


def _describe(item: dict) -> str:
    name = item_guide_color(item)
    if _gt(item.get("garment_type")) in ("pants", "shorts") and name in ("light blue", "navy"):
        lab = item["primary_color"]["lab"]
        L, C, h = lab_to_lch(tuple(lab))
        if C >= W.DENIM_MIN_CHROMA and W.DENIM_HUE_MIN_DEG <= h <= W.DENIM_HUE_MAX_DEG:
            return "light-wash denim" if name == "light blue" else "dark denim"
    # Speak the garment's own stored color name (e.g. "cream", not the guide's "beige") so the
    # sentence never names a color the outfit doesn't show; _name_agrees already vetted it.
    stored = (item.get("primary_color") or {}).get("name")
    if stored and stored != "unmapped":
        return stored.replace("light_gray", "light grey").replace("gray", "grey").replace("_", " ")
    return name


# Stored color names (contract/colors.json) each guide color may plausibly describe. The
# guide sentence names colors out loud, so it is only emitted when both garments' own color
# names agree with the guide color picked for them.
GUIDE_NAME_AGREES: dict[str, frozenset] = {
    "pink": frozenset({"pink", "red", "purple"}),
    "red": frozenset({"red", "pink", "burgundy", "orange"}),
    "orange": frozenset({"orange", "red", "camel", "tan", "yellow"}),
    "beige": frozenset({"cream", "beige", "tan", "camel", "white", "light_gray"}),
    "yellow": frozenset({"yellow", "orange", "cream"}),
    "green": frozenset({"green", "olive", "teal"}),
    "dark green": frozenset({"green", "olive", "teal"}),
    "light blue": frozenset({"light_blue", "blue", "denim"}),
    "navy": frozenset({"navy", "blue", "denim"}),
    "purple": frozenset({"purple", "burgundy", "pink"}),
    "burgundy": frozenset({"burgundy", "red", "purple", "brown"}),
    "brown": frozenset({"brown", "camel", "tan", "burgundy"}),
    "grey": frozenset({"gray", "light_gray", "charcoal"}),
    "white": frozenset({"white", "cream", "light_gray"}),
    "black": frozenset({"black", "charcoal"}),
}


def _name_agrees(item: dict) -> bool:
    """False when the garment's stored color name contradicts its guide color (items with no
    stored name are trusted)."""
    name = (item.get("primary_color") or {}).get("name")
    if not name:
        return True
    return name in GUIDE_NAME_AGREES.get(item_guide_color(item), frozenset())


def guide_sentence(top: dict, bottom: dict) -> str | None:
    """One plain sentence when the guide lists the top+bottom pair and both named guide colors
    agree with the garments' own color names; None otherwise."""
    quality = item_pair_quality(top, bottom)
    if quality not in ("complementary", "tonal"):
        return None
    if not (_name_agrees(top) and _name_agrees(bottom)):
        return None
    t, b = _describe(top), _describe(bottom)
    if t == b:
        return None
    if "denim" in b:
        verb = "pairs well with" if quality == "complementary" else "makes an easy tonal look with"
        return f"{b[0].upper()}{b[1:]} {verb} {t}."
    first, second = t, b
    if quality == "complementary":
        return f"{first[0].upper()}{first[1:]} and {second} are an easy classic pairing."
    return f"{first[0].upper()}{first[1:]} and {second} make an easy tonal pairing."


# ------------------------------------------------------------------ seasonal palette read

def _is_warm(hue: float) -> bool:
    return not (W.SEASON_COOL_HUE_MIN <= hue < W.SEASON_COOL_HUE_MAX)


def classify_season(labs: list) -> dict | None:
    """12-season read of a set of non-neutral Lab colors: value (light/deep), chroma
    (bright/soft) and temperature (warm/cool). Returns None with too few colors."""
    if len(labs) < W.SEASON_MIN_ITEMS:
        return None
    lchs = [lab_to_lch(tuple(float(v) for v in lab)) for lab in labs]
    mean_l = sum(x[0] for x in lchs) / len(lchs)
    mean_c = sum(x[1] for x in lchs) / len(lchs)
    warm_share = sum(1 for x in lchs if _is_warm(x[2])) / len(lchs)

    value = "light" if mean_l > W.SEASON_LIGHT_L_MIN else "deep" if mean_l < W.SEASON_DEEP_L_MAX else "mid"
    chroma = "bright" if mean_c > W.SEASON_BRIGHT_C_MIN else "soft" if mean_c < W.SEASON_SOFT_C_MAX else "mid"
    warm = warm_share >= 0.5
    temp = "warm" if warm_share >= W.SEASON_WARM_SHARE_MIN else "cool" if warm_share <= W.SEASON_COOL_SHARE_MAX else "neutral"

    mid_l = (W.SEASON_LIGHT_L_MIN + W.SEASON_DEEP_L_MAX) / 2
    mid_c = (W.SEASON_BRIGHT_C_MIN + W.SEASON_SOFT_C_MAX) / 2
    strength = {
        "value": abs(mean_l - mid_l) / W.SEASON_L_SCALE if value != "mid" else 0.0,
        "chroma": abs(mean_c - mid_c) / W.SEASON_C_SCALE if chroma != "mid" else 0.0,
        "temp": abs(warm_share - 0.5) / W.SEASON_TEMP_SCALE if temp != "neutral" else 0.0,
    }
    axis = max(strength, key=lambda k: (strength[k], k == "temp"))
    if strength[axis] == 0.0:
        axis = "temp"

    if axis == "value":
        season = ("light spring" if warm else "light summer") if value == "light" else ("deep autumn" if warm else "deep winter")
    elif axis == "chroma":
        season = ("bright spring" if warm else "bright winter") if chroma == "bright" else ("soft autumn" if warm else "soft summer")
    else:
        lively = mean_l >= mid_l or mean_c >= mid_c
        if warm:
            season = "true spring" if lively and mean_l >= mid_l else "true autumn"
        else:
            season = "true summer" if mean_l >= mid_l and mean_c < mid_c else "true winter"

    words = {
        "chroma": {"bright": "bright", "soft": "muted", "mid": "moderately saturated"}[chroma],
        "temp": {"warm": "warm", "cool": "cool", "neutral": "balanced between warm and cool"}[temp],
        "value": {"light": "light", "deep": "deep", "mid": "mid-depth"}[value],
    }
    return {
        "season": season,
        "mean_l": mean_l,
        "mean_c": mean_c,
        "warm_share": warm_share,
        "sentence": f"Your closet reads as a {season} palette: {words['chroma']}, {words['temp']} and {words['value']}.",
    }
