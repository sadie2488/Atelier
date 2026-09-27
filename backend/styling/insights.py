"""Pure computation for GET /insights/palette (contract 2.2.0): a closet-wide color summary.

Mirrors scorer.py's purity rule (S-C1): no DB, network, or file I/O beyond reading the
frozen `contract/colors.json` family table (via contract.tools.color, already relied on by
the contract itself). Inputs are plain dicts shaped like `contract.schemas.Item`
(`.model_dump()`), not pydantic instances -- same convention as scorer.py/strategies.py.

The route (`backend/routes/insights.py`) is responsible for reading the DB and may supply a
MongoDB-aggregated `family_counts` (the MongoDB-track showcase); when it doesn't (the test
fake has no `aggregate`, or the aggregation isn't supported), this module derives the same
counts from `items` in Python -- both paths must produce identical `families` output.
"""
from __future__ import annotations

from functools import lru_cache

from contract.tools.color import color_table, lab_to_lch

from backend.styling import weights as W
from backend.styling.scorer import hue_diff, score_items
from backend.styling.strategies import generate_candidates

UNMAPPED = "unmapped"


# Friendly wording for insight sentences (display only; families stay colors.json keys).
_FAMILY_WORDS = {
    "achromatic": "black, white and gray",
    "warm_light": "cream and tan",
    "warm_dark": "brown",
    "blue_green": "teal",
}


def _family_words(family: str) -> str:
    return _FAMILY_WORDS.get(family, family.replace("_", " "))


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word

# Families read as "warm" / "cool" for the closet-balance observation. Achromatic is neither.
WARM_FAMILIES = {"red", "orange", "yellow", "warm_light", "warm_dark"}
COOL_FAMILIES = {"blue", "blue_green", "green", "purple"}


@lru_cache(maxsize=1)
def _family_order() -> tuple[str, ...]:
    """colors.json families in file order (first appearance), e.g. for deterministic tie-break."""
    _, table = color_table()
    order: list[str] = []
    for entry in table.values():
        fam = entry["family"]
        if fam not in order:
            order.append(fam)
    return tuple(order)


@lru_cache(maxsize=1)
def _chromatic_centers() -> tuple[tuple[str, float], ...]:
    """(family, center hue) for every colors.json center that isn't achromatic."""
    _, table = color_table()
    return tuple(
        (e["family"], lab_to_lch(tuple(e["lab"]))[2]) for e in table.values() if e["family"] != "achromatic"
    )


def _insights_family(pc: dict) -> str:
    """Family used for the palette summary. Normally the stored family; but a visibly chromatic
    color (not is_neutral) whose nearest colors.json center was achromatic or unmapped (e.g. a
    dark evergreen stored as "charcoal") is grouped with the chromatic family nearest its hue,
    so the page never shows green as missing while a green item sits in the closet."""
    fam = pc["family"]
    if fam not in ("achromatic", UNMAPPED) or pc["is_neutral"]:
        return fam
    hue = lab_to_lch(tuple(pc["lab"]))[2]
    return min(_chromatic_centers(), key=lambda fc: hue_diff(hue, fc[1]))[0]


def _lab_to_hex(lab: tuple[float, float, float]) -> str:
    """CIE Lab (D65) -> sRGB hex. Inverse of contract.tools.color.hex_to_lab; that module has
    no reverse direction, and insights needs one for a family's mean-Lab representative color.
    """
    L, a, b = lab
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200

    def finv(t: float) -> float:
        return t ** 3 if t ** 3 > (6 / 29) ** 3 else 3 * (6 / 29) ** 2 * (t - 4 / 29)

    Xw, Yw, Zw = 95.047, 100.0, 108.883
    x, y, z = finv(fx) * Xw / 100, finv(fy) * Yw / 100, finv(fz) * Zw / 100

    r = x * 3.2404542 + y * -1.5371385 + z * -0.4985314
    g = x * -0.9692660 + y * 1.8760108 + z * 0.0415560
    bb = x * 0.0556434 + y * -0.2040259 + z * 1.0572252

    def gamma(c: float) -> float:
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

    def to255(c: float) -> int:
        return max(0, min(255, round(gamma(c) * 255)))

    return "#{:02x}{:02x}{:02x}".format(to255(r), to255(g), to255(bb))


def _family_hex(items_in_family: list[dict]) -> str:
    if not items_in_family:
        return "#808080"
    labs = [tuple(it["primary_color"]["lab"]) for it in items_in_family]
    mean_lab = tuple(sum(v) / len(v) for v in zip(*labs))
    return _lab_to_hex(mean_lab)


def _missing_family_pair_counts(missing_families: list[str], bottoms: list[dict]) -> list[tuple[str, int]]:
    """For each missing family, how many bottoms a synthetic top in that family would pair
    well with (score_items >= INSIGHTS_PAIR_GOOD_THRESHOLD), using colors.json's own named
    colors in that family as the synthetic top's color (mean Lab of the family's centers --
    there is no closet item to draw from, that's why the family is missing). Sorted best
    first, alphabetical family name on ties.
    """
    if not missing_families or not bottoms:
        return []
    _, table = color_table()
    results: list[tuple[str, int]] = []
    for family in missing_families:
        entries = [e for e in table.values() if e["family"] == family]
        if not entries:
            continue
        labs = [tuple(e["lab"]) for e in entries]
        mean_lab = tuple(sum(v) / len(v) for v in zip(*labs))
        lch = lab_to_lch(mean_lab)
        everyday = sum(1 for e in entries if e["everyday_neutral"]) > len(entries) / 2
        synth_top = {
            "primary_color": {
                "lab": mean_lab,
                "lch": lch,
                "family": family,
                "is_neutral": lch[1] < W.NEUTRAL_CHROMA_MAX,
                "everyday_neutral": everyday,
            }
        }
        count = sum(1 for b in bottoms if score_items(synth_top, b) >= W.INSIGHTS_PAIR_GOOD_THRESHOLD)
        results.append((family, count))
    results.sort(key=lambda kv: (-kv[1], kv[0]))
    return results


def _round_pct(share: float) -> int:
    return round(share * 100)


def _observations(
    item_count: int,
    neutral_share: float,
    families: list[dict],
    tops: list[dict],
    bottoms: list[dict],
    jackets: list[dict],
    pair_counts: list[tuple[str, int]],
) -> list[str]:
    """Up to 6 plain, specific, one-sentence observations (contract PaletteInsights.insights).
    No LLM: every sentence is computed directly from the data above.
    """
    if item_count == 0:
        return []

    obs: list[str] = [f"{_round_pct(neutral_share)}% of your closet is neutral."]

    if families:
        obs.append(f"Your most common colors are {_family_words(families[0]['family'])}.")

    present = {f["family"] for f in families}
    if present and not (present & WARM_FAMILIES):
        obs.append("Your closet has no warm colors.")
    elif present and not (present & COOL_FAMILIES):
        obs.append("Your closet has no cool colors.")

    n_tops, n_bottoms, n_jackets = len(tops), len(bottoms), len(jackets)
    if n_tops and n_bottoms and abs(n_tops - n_bottoms) >= 2:
        if n_tops > n_bottoms:
            obs.append(f"You have {n_tops} tops but only {n_bottoms} bottoms.")
        else:
            obs.append(f"You have {n_bottoms} bottoms but only {n_tops} tops.")

    if n_jackets == 0 and n_tops and n_bottoms:
        obs.append("You have no jackets, so sandwich outfits aren't available yet.")

    if pair_counts:
        best_family, best_count = pair_counts[0]
        if best_count > 0:
            obs.append(f"Adding {_a(_family_words(best_family))} top would pair with {best_count} of your bottoms.")

    return obs[:6]


def _most_versatile(tops: list[dict], bottoms: list[dict], jackets: list[dict], limit: int = 3) -> list[dict]:
    """Up to `limit` items with the most appearances across raw generated outfit candidates
    (not the capped final selection): strategies.generate_candidates over the whole closet,
    counted per item id. Jackets are included.
    """
    order_index = {it["id"]: i for i, it in enumerate([*tops, *bottoms, *jackets])}
    counts: dict[str, int] = {}
    for _strategy, top, bottom, jacket, _score in generate_candidates(tops, bottoms, jackets):
        for entry in (top, bottom, jacket):
            if entry is not None:
                counts[entry["id"]] = counts.get(entry["id"], 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], order_index.get(kv[0], 0)))
    return [{"item_id": item_id, "outfit_count": count} for item_id, count in ranked[:limit]]


def compute_insights(items: list[dict], family_counts: dict[str, int] | None = None) -> dict:
    """Build a dict matching `contract.schemas.PaletteInsights` from a closet's items.

    `items`: dicts shaped like `contract.schemas.Item.model_dump()`.
    `family_counts`: optional pre-computed {family: count} (e.g. from a MongoDB aggregation
    in the route); when omitted, counts are derived from `items` here. Both paths must yield
    the same `families` output for the same closet.
    """
    item_count = len(items)
    order = _family_order()
    order_index = {fam: i for i, fam in enumerate(order)}

    by_family: dict[str, list[dict]] = {}
    neutral_count = 0
    item_family: dict[int, str] = {}
    for item in items:
        pc = item["primary_color"]
        fam = _insights_family(pc)
        item_family[id(item)] = fam
        by_family.setdefault(fam, []).append(item)
        if pc["is_neutral"]:
            neutral_count += 1

    # A regrouped item makes stored-family counts (e.g. the Mongo aggregation) disagree with
    # the summary; count from items instead so bars and missing_families stay consistent.
    if family_counts is None or any(item_family[id(i)] != i["primary_color"]["family"] for i in items):
        family_counts = {fam: len(its) for fam, its in by_family.items()}

    present_families = [
        fam for fam, count in family_counts.items() if fam != UNMAPPED and count > 0
    ]
    present_families.sort(key=lambda f: (-family_counts[f], order_index.get(f, len(order))))

    families = [
        {
            "family": fam,
            "count": family_counts[fam],
            "share": family_counts[fam] / item_count if item_count else 0.0,
            "hex": _family_hex(by_family.get(fam, [])),
        }
        for fam in present_families
    ]

    missing_families = sorted(set(order) - set(present_families))

    sorted_items = sorted(items, key=lambda it: it["created_at"], reverse=True)
    swatches = [
        {
            "item_id": item["id"],
            "category": item["category"],
            "hex": item["primary_color"]["hex"],
            "display_name": item["primary_color"].get("display_name"),
            "family": item_family[id(item)],
        }
        for item in sorted_items
    ]

    tops = [i for i in items if i["category"] == "tops"]
    bottoms = [i for i in items if i["category"] == "bottoms"]
    jackets = [i for i in items if i["category"] == "jackets"]

    neutral_share = neutral_count / item_count if item_count else 0.0

    pair_counts = _missing_family_pair_counts(missing_families, bottoms)
    insights = _observations(item_count, neutral_share, families, tops, bottoms, jackets, pair_counts)

    most_versatile = _most_versatile(tops, bottoms, jackets)

    return {
        "item_count": item_count,
        "neutral_share": neutral_share,
        "families": families,
        "swatches": swatches,
        "missing_families": missing_families,
        "insights": insights,
        "most_versatile": most_versatile,
    }
