"""Avatar lane: /api/avatar/* and /api/render/*. Stubs return 501 until the lane replaces them."""
from fastapi import APIRouter

from backend.routes import not_implemented

router = APIRouter(tags=["avatar"])


@router.post("/avatar/scan")
def scan():
    return not_implemented("POST /api/avatar/scan")


@router.get("/avatar/{avatar_id}")
def get_avatar(avatar_id: str):
    return not_implemented("GET /api/avatar/{avatar_id}")


@router.post("/render")
def render():
    return not_implemented("POST /api/render")


@router.get("/render/{render_id}")
def get_render(render_id: str):
    return not_implemented("GET /api/render/{render_id}")
