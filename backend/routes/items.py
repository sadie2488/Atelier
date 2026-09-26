"""Vision lane: /api/items/*.

Two-step ingest: POST /analyze persists nothing and returns exactly three candidates; POST
/save persists the chosen one and allocates its slug; POST /reject persists nothing and logs.
Items are stored via `backend.db.get_db()["items"]` (Depends so tests can override it).
"""
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import ValidationError

from backend import config
from backend.db import get_db
from contract.enums import Category, ErrorCode, GarmentType, SLUG_PREFIX
from contract.schemas import (
    AnalyzeForm, AnalyzeResponse, Candidate, ExtractedColor, Item, ItemListResponse,
    RejectRequest, RejectResponse, SaveRequest,
)

from backend.vision import VisionError
from backend.vision.failures import log_failure
from backend.vision.ingest import build_candidates
from backend.vision.session import (
    TMP_MEDIA_DIR, delete_session, load_session, new_temp_handle, save_session, sweep_expired,
)

router = APIRouter(prefix="/items", tags=["items"])

# V-A4: TTL sweep of stale temp handles. Runs once at process start (this module is imported
# by backend/main.py when the app boots) rather than editing main.py directly.
sweep_expired()

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.invalid_request: 400,
    ErrorCode.unsupported_image: 415,
    ErrorCode.no_person_detected: 422,
    ErrorCode.analyze_failed: 500,
    ErrorCode.handle_expired: 410,
    ErrorCode.not_found: 404,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(code: ErrorCode, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=_STATUS_BY_CODE.get(code, 500),
        content={"error": {"code": code.value, "message": message}},
    )


def _to_item(doc: dict) -> Item:
    """Strip `_id` and any DB-only field (e.g. `anchors`) before validating as Item."""
    clean = {k: v for k, v in doc.items() if k in Item.model_fields}
    return Item.model_validate(clean)


def _fresh_slug(prefix: str, items) -> str:
    for _ in range(50):
        slug = f"{prefix}_{secrets.token_hex(3)}"      # SLUG_PATTERN: 6 lowercase hex
        if items.find_one({"id": slug}) is None:
            return slug
    raise VisionError(ErrorCode.analyze_failed, "Could not allocate a unique item slug.")


@router.post("/analyze")
async def analyze(
    image: UploadFile = File(...),
    category: str = Form(...),
    garment_type: str = Form(...),
    color: Optional[str] = Form(None),
    item_name: Optional[str] = Form(None),
):
    try:
        form = AnalyzeForm(category=category, garment_type=garment_type, color=color, item_name=item_name)
    except ValidationError as e:
        return _error(ErrorCode.invalid_request, str(e))

    data = await image.read()

    try:
        candidates, multi_person = build_candidates(data, form.garment_type)
    except VisionError as e:
        return _error(e.code, e.message)
    except Exception as e:  # segmentation/color raised unexpectedly -- never a silent fallback
        log_failure({
            "event": "exception", "temp_handle": None, "category": form.category.value,
            "retailer_color": form.color, "timestamp": _now_iso(), "message": str(e),
        })
        return _error(ErrorCode.analyze_failed, f"Analyze failed: {e}")

    handle = new_temp_handle()
    TMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    api_candidates: list[Candidate] = []
    session_candidates: list[dict] = []
    for i, c in enumerate(candidates):
        filename = f"{handle}_{i}.png"
        Image.fromarray(c["rgba"], mode="RGBA").save(TMP_MEDIA_DIR / filename)
        url = f"/media/tmp/{filename}"

        primary = ExtractedColor(**c["primary_color"])
        secondary = ExtractedColor(**c["secondary_color"]) if c["secondary_color"] else None
        api_candidates.append(Candidate(
            index=i, variant=c["variant"], cutout_url=url,
            primary_color=primary, secondary_color=secondary,
        ))
        session_candidates.append({
            "index": i, "variant": c["variant"].value, "filename": filename,
            "primary_color": c["primary_color"], "secondary_color": c["secondary_color"],
            "anchors": c["anchors"], "checks": c["checks"],
        })

    save_session(handle, {
        "temp_handle": handle,
        "category": form.category.value,
        "garment_type": form.garment_type.value,
        "retailer_color": form.color,
        "retailer_item_name": form.item_name,
        "created_at": time.time(),
        "candidates": session_candidates,
    })

    if multi_person:
        log_failure({
            "event": "multi_person", "temp_handle": handle, "category": form.category.value,
            "retailer_color": form.color, "timestamp": _now_iso(),
        })

    return AnalyzeResponse(temp_handle=handle, candidates=api_candidates)


@router.post("/save")
def save(body: SaveRequest, db=Depends(get_db)):
    session = load_session(body.temp_handle)
    if session is None:
        return _error(ErrorCode.handle_expired, f"Unknown or expired temp_handle {body.temp_handle!r}.")

    cand = next((c for c in session["candidates"] if c["index"] == body.candidate_index), None)
    if cand is None:
        return _error(ErrorCode.invalid_request, f"candidate_index {body.candidate_index} is not in this session.")

    garment_type = GarmentType(session["garment_type"])
    category = Category(session["category"])
    items = db["items"]

    try:
        slug = _fresh_slug(SLUG_PREFIX[garment_type], items)
    except VisionError as e:
        return _error(e.code, e.message)

    src = TMP_MEDIA_DIR / cand["filename"]
    dest_dir = config.MEDIA_DIR / "items"
    dest_dir.mkdir(parents=True, exist_ok=True)
    src.replace(dest_dir / f"{slug}.png")

    doc = {
        "id": slug,
        "category": category.value,
        "garment_type": garment_type.value,
        "cutout_url": f"/media/items/{slug}.png",
        "primary_color": cand["primary_color"],
        "secondary_color": cand["secondary_color"],
        "retailer_color": session.get("retailer_color"),
        "retailer_item_name": session.get("retailer_item_name"),
        "attributes": {},
        "created_at": datetime.now(timezone.utc),
        "anchors": cand["anchors"],   # DB-only, ARTIFACT_SPEC
    }
    item = _to_item(doc)
    items.insert_one(doc)
    delete_session(body.temp_handle)
    return item


@router.post("/reject")
def reject(body: RejectRequest):
    session = load_session(body.temp_handle)
    if session is None:
        return _error(ErrorCode.handle_expired, f"Unknown or expired temp_handle {body.temp_handle!r}.")

    log_failure({
        "event": "reject_all",
        "temp_handle": body.temp_handle,
        "category": session.get("category"),
        "retailer_color": session.get("retailer_color"),
        "timestamp": _now_iso(),
        "candidates": [
            {"index": c["index"], "variant": c["variant"], "checks": c["checks"]}
            for c in session["candidates"]
        ],
    })
    delete_session(body.temp_handle)
    return RejectResponse(ok=True)


@router.get("")
def list_items(category: Optional[Category] = None, db=Depends(get_db)):
    query = {} if category is None else {"category": category.value}
    docs = list(db["items"].find(query))
    items = [_to_item(d) for d in docs]
    items.sort(key=lambda i: i.created_at, reverse=True)
    return ItemListResponse(items=items)


@router.get("/{slug}")
def get_item(slug: str, db=Depends(get_db)):
    doc = db["items"].find_one({"id": slug})
    if doc is None:
        return _error(ErrorCode.not_found, f"No item with id {slug!r}.")
    return _to_item(doc)
