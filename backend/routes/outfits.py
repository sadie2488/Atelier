"""Styling lane: /api/outfits/*.

Reads items via `backend.db.get_db()["items"]` through FastAPI's dependency system so tests
can override it with an in-memory fake (S-I2: the items collection may be empty for this
lane's entire duration, including in production before the vision lane has saved anything).
"""
from fastapi import APIRouter, Depends

from backend.db import get_db
from contract.schemas import Item, Outfit, OutfitsGenerateRequest, OutfitsGenerateResponse

from backend.styling import select as select_mod
from backend.styling import weights as W
from backend.styling.explain import explain
from backend.styling.strategies import generate_candidates

router = APIRouter(prefix="/outfits", tags=["outfits"])


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

    chosen = select_mod.select_outfits(candidates, min(req.limit, W.OUTFITS_MAX))

    outfits = [
        Outfit(
            outfit_id=select_mod.make_outfit_id(c["top_id"], c["bottom_id"], c["jacket_id"]),
            strategy=c["strategy"],
            top_id=c["top_id"],
            bottom_id=c["bottom_id"],
            jacket_id=c["jacket_id"],
            explanation=explain(c["strategy"], c["top"], c["bottom"], c["jacket"]),
            score=round(c["score"], 4),
        )
        for c in chosen
    ]

    return OutfitsGenerateResponse(outfits=outfits)
