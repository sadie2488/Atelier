"""Styling lane: /api/outfits/*.

Reads items via `backend.db.get_db()["items"]` through FastAPI's dependency system so tests
can override it with an in-memory fake (S-I2: the items collection may be empty for this
lane's entire duration, including in production before the vision lane has saved anything).
"""
import random

from fastapi import APIRouter, Depends

from backend.db import get_db
from contract.schemas import Item, Outfit, OutfitsGenerateRequest, OutfitsGenerateResponse

from backend.styling import planned as planned_mod
from backend.styling import select as select_mod
from backend.styling import styles as styles_mod
from backend.styling import weights as W
from backend.styling.explain import explain_many
from backend.styling.strategies import generate_candidates

router = APIRouter(prefix="/outfits", tags=["outfits"])

# S4 (variety): the frontend sends no state across calls, so this process keeps a small
# in-process memory of the previous response's outfit_ids (fine for the demo -- not durable,
# not shared across processes) plus its own unseeded RNG, so repeat calls tend not to just
# replay the same top outfit. Tests inject their own seeded rng/previous_ids into
# select_outfits directly instead of touching this module state.
_rng = random.Random()
_last_outfit_ids: set[str] = set()


def _to_item(doc: dict) -> Item:
    """Strip `_id` and any other DB-only field (e.g. `anchors`) before validating as Item."""
    clean = {k: v for k, v in doc.items() if k in Item.model_fields}
    return Item.model_validate(clean)


def _after_planned(first: dict, candidates: list[dict], limit: int) -> list[dict]:
    """[first] + the scorer's picks that keep the response contract-valid: no duplicate of
    the planned combo, best-first order (only candidates scoring <= the planned outfit), and
    the per-strategy / per-garment caps counted with the planned outfit included."""
    from collections import Counter

    first_key = (first["top_id"], first["bottom_id"], first["jacket_id"])
    first_score = round(first["score"], 4)
    rest = [
        c for c in candidates
        if (c["top_id"], c["bottom_id"], c["jacket_id"]) != first_key
        and round(c["score"], 4) <= first_score
    ]
    picks = select_mod.select_outfits(rest, W.OUTFITS_MAX, rng=_rng, previous_ids=_last_outfit_ids)

    chosen = [first]
    strategy_counts: Counter = Counter({first["strategy"]: 1})
    garment_counts: Counter = Counter({first["top_id"]: 1, first["bottom_id"]: 1})
    for c in picks:
        if len(chosen) >= limit:
            break
        if (
            strategy_counts[c["strategy"]] >= W.OUTFITS_MAX_PER_STRATEGY
            or garment_counts[c["top_id"]] >= W.OUTFITS_MAX_SHARING_GARMENT
            or garment_counts[c["bottom_id"]] >= W.OUTFITS_MAX_SHARING_GARMENT
        ):
            continue
        chosen.append(c)
        strategy_counts[c["strategy"]] += 1
        garment_counts[c["top_id"]] += 1
        garment_counts[c["bottom_id"]] += 1
    return chosen


@router.post("/generate", response_model=OutfitsGenerateResponse)
def generate(body: OutfitsGenerateRequest | None = None, db=Depends(get_db)):
    req = body or OutfitsGenerateRequest()

    docs = list(db["items"].find({}))
    items = [_to_item(doc).model_dump() for doc in docs]

    tops = [i for i in items if i["category"] == "tops"]
    bottoms = [i for i in items if i["category"] == "bottoms"]
    jackets = [i for i in items if i["category"] == "jackets"]

    candidates = [
        {
            "strategy": strategy,
            "top": top,
            "bottom": bottom,
            "jacket": jacket,
            "top_id": top["id"],
            "bottom_id": bottom["id"],
            "jacket_id": jacket["id"] if jacket else None,
            "score": max(0.0, min(1.0, score)),
        }
        for strategy, top, bottom, jacket, score in generate_candidates(tops, bottoms, jackets)
    ]

    limit = min(req.limit, W.OUTFITS_MAX)

    # Demo planned outfits (ATELIER_DEMO_OUTFITS): when set and the next entry in rotation is
    # fully in the closet, it leads the response; the scorer's picks follow. Unset -> the
    # original path below, unchanged.
    first = None
    if req.style is not None:
        # Style preset (2.5.0): no planned rotation; neutral tonal pairs join the pool, then the
        # pool is narrowed by style (relaxing gradually) before the usual variety pick.
        seen = {(c["top_id"], c["bottom_id"], c["jacket_id"]) for c in candidates}
        candidates += [
            c for c in styles_mod.tonal_extras(tops, bottoms, jackets)
            if (c["top_id"], c["bottom_id"], c["jacket_id"]) not in seen
        ]
        chosen = styles_mod.styled_pick(
            req.style, candidates, limit,
            lambda pool, n: select_mod.select_outfits(pool, n, rng=_rng, previous_ids=_last_outfit_ids),
        )
        return _respond(chosen, lead=styles_mod.STYLE_LEAD[req.style])

    try:
        plan = planned_mod.planned_outfits()
        if plan:
            entry = plan[planned_mod.next_planned_index(len(plan))]
            first = planned_mod.plan_outfit(entry, items, candidates)
    except Exception:
        first = None

    if first is None:
        chosen = select_mod.select_outfits(
            candidates, limit, rng=_rng, previous_ids=_last_outfit_ids
        )
    else:
        chosen = _after_planned(first, candidates, limit)
    outfits = _build(chosen)

    if first is None:
        return OutfitsGenerateResponse(outfits=outfits)
    try:
        return OutfitsGenerateResponse(outfits=outfits)
    except Exception:
        # Safety net for the planned path only: never 500 the demo -- the planned outfit alone
        # is always a valid response.
        return OutfitsGenerateResponse(outfits=outfits[:1])


def _respond(chosen: list[dict], lead: str | None = None) -> OutfitsGenerateResponse:
    return OutfitsGenerateResponse(outfits=_build(chosen, lead=lead))


def _build(chosen: list[dict], lead: str | None = None) -> list[Outfit]:
    _last_outfit_ids.clear()
    _last_outfit_ids.update(
        select_mod.make_outfit_id(c["top_id"], c["bottom_id"], c["jacket_id"]) for c in chosen
    )

    # One shared-deadline batch call (S-E4), not one blocking call per outfit: a slow/hanging
    # Gemini must not multiply the response latency by the number of outfits.
    explanations = explain_many(
        [(c["strategy"], c["top"], c["bottom"], c["jacket"]) for c in chosen], lead=lead
    )

    outfits = [
        Outfit(
            outfit_id=select_mod.make_outfit_id(c["top_id"], c["bottom_id"], c["jacket_id"]),
            strategy=c["strategy"],
            top_id=c["top_id"],
            bottom_id=c["bottom_id"],
            jacket_id=c["jacket_id"],
            explanation=explanation,
            score=round(c["score"], 4),
        )
        for c, explanation in zip(chosen, explanations)
    ]
    return outfits
