"""Styling lane: /api/outfits/*.

Reads items via `backend.db.get_db()["items"]` through FastAPI's dependency system so tests
can override it with an in-memory fake (S-I2: the items collection may be empty for this
lane's entire duration, including in production before the vision lane has saved anything).
"""
import random

from fastapi import APIRouter, Depends

from backend.db import get_db
from contract.schemas import Item, Outfit, OutfitsGenerateRequest, OutfitsGenerateResponse

from backend.styling import select as select_mod
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

    chosen = select_mod.select_outfits(
        candidates, min(req.limit, W.OUTFITS_MAX), rng=_rng, previous_ids=_last_outfit_ids
    )
    _last_outfit_ids.clear()
    _last_outfit_ids.update(
        select_mod.make_outfit_id(c["top_id"], c["bottom_id"], c["jacket_id"]) for c in chosen
    )

    # One shared-deadline batch call (S-E4), not one blocking call per outfit: a slow/hanging
    # Gemini must not multiply the response latency by the number of outfits.
    explanations = explain_many(
        [(c["strategy"], c["top"], c["bottom"], c["jacket"]) for c in chosen]
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

    return OutfitsGenerateResponse(outfits=outfits)
