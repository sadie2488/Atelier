"""Styling lane: /api/insights/*.

GET /api/insights/palette (contract 2.2.0): closet-wide color summary for the palette page.
Reads items the same way backend/routes/outfits.py does -- via backend.db.get_db() through
FastAPI's dependency system, so tests can override it with an in-memory fake, and the DB may
be empty (S-I2).
"""
from fastapi import APIRouter, Depends

from backend.db import get_db
from contract.schemas import Item, PaletteInsights

from backend.styling.insights import compute_insights

router = APIRouter(prefix="/insights", tags=["insights"])


def _to_item(doc: dict) -> Item:
    """Strip `_id` and any other DB-only field before validating as Item (same pattern as
    backend/routes/outfits.py)."""
    clean = {k: v for k, v in doc.items() if k in Item.model_fields}
    return Item.model_validate(clean)


def _family_counts_via_mongo(collection) -> dict[str, int] | None:
    """MongoDB aggregation for family counts (the MongoDB-track showcase). Returns None when
    the collection doesn't support aggregate (the shared test fake has no `aggregate`) or the
    call fails, so the route falls back to counting in Python from the items it already
    fetched via find() -- both paths are covered by test_styling.py and must agree.
    """
    aggregate = getattr(collection, "aggregate", None)
    if aggregate is None:
        return None
    try:
        pipeline = [{"$group": {"_id": "$primary_color.family", "count": {"$sum": 1}}}]
        return {doc["_id"]: doc["count"] for doc in aggregate(pipeline)}
    except Exception:
        return None


@router.get("/palette", response_model=PaletteInsights)
def palette(db=Depends(get_db)):
    docs = list(db["items"].find({}))
    items = [_to_item(doc).model_dump() for doc in docs]

    family_counts = _family_counts_via_mongo(db["items"])
    return PaletteInsights(**compute_insights(items, family_counts=family_counts))
