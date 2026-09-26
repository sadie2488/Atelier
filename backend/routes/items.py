"""Vision lane: /api/items/*. Stubs return 501 until the lane replaces them."""
from fastapi import APIRouter

from backend.routes import not_implemented

router = APIRouter(prefix="/items", tags=["items"])


@router.post("/analyze")
def analyze():
    return not_implemented("POST /api/items/analyze")


@router.post("/save")
def save():
    return not_implemented("POST /api/items/save")


@router.post("/reject")
def reject():
    return not_implemented("POST /api/items/reject")


@router.get("")
def list_items():
    return not_implemented("GET /api/items")


@router.get("/{slug}")
def get_item(slug: str):
    return not_implemented("GET /api/items/{slug}")
