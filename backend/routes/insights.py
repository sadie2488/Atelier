"""Styling lane: /api/insights/*. Stub returns 501 until the lane replaces it."""
from fastapi import APIRouter

from backend.routes import not_implemented

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/palette")
def palette():
    return not_implemented("GET /api/insights/palette")
