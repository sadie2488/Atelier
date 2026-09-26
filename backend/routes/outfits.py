"""Styling lane: /api/outfits/*. Stub returns 501 until the lane replaces it."""
from fastapi import APIRouter

from backend.routes import not_implemented

router = APIRouter(prefix="/outfits", tags=["outfits"])


@router.post("/generate")
def generate():
    return not_implemented("POST /api/outfits/generate")
