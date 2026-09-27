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

from backend import config, media_store
from backend.db import get_db
from contract.enums import Category, ErrorCode, GarmentType, SLUG_PREFIX
from contract.schemas import (
    AnalyzeForm, AnalyzeResponse, Candidate, ExtractedColor, Item, ItemListResponse,
    RejectRequest, RejectResponse, RenameRequest, SaveRequest,
)

from backend.vision import VisionError
from backend.vision.failures import log_failure
from backend.vision.flatlay import analyze_flatlay_bytes
from backend.vision.ingest import build_candidates
from backend.vision.tagging import tag_item
from backend.vision.session import (
    delete_session, load_session, new_temp_handle, save_session, sweep_expired, tmp_media_dir,
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


def _has_transparent_background(data: bytes) -> bool:
    """True when the image has an alpha channel and at least 5% of it is fully transparent."""
    try:
        import io
        import numpy as np
        with Image.open(io.BytesIO(data)) as im:
            if "A" not in im.getbands() and "transparency" not in im.info:
                return False
            alpha = np.asarray(im.convert("RGBA"))[..., 3]
        return float((alpha < 16).mean()) >= 0.05
    except Exception:
        return False


def _build_any(data: bytes, category, garment_type):
    """Person pipeline first (unchanged for photos with a person); flat-lay/product-photo
    fallback (alpha cutout, else background flood-fill + GrabCut) when no person is detected.
    Same return shape either way. A photo that already has a transparent background is a garment
    cutout, so it goes straight to the flat-lay path (the pose model can mistake a tee for a torso)."""
    if _has_transparent_background(data):
        return analyze_flatlay_bytes(data, category, garment_type)
    try:
        return build_candidates(data, category, garment_type)
    except VisionError as e:
        if e.code != ErrorCode.no_person_detected:
            raise
        return analyze_flatlay_bytes(data, category, garment_type)


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
        candidates, multi_person, category_mismatch = _build_any(data, form.category, form.garment_type)
    except VisionError as e:
        return _error(e.code, e.message)
    except Exception as e:  # segmentation/color raised unexpectedly -- never a silent fallback
        log_failure({
            "event": "exception", "temp_handle": None, "category": form.category.value,
            "retailer_color": form.color, "timestamp": _now_iso(), "message": str(e),
        })
        return _error(ErrorCode.analyze_failed, f"Analyze failed: {e}")

    handle = new_temp_handle()
    tmp_dir = tmp_media_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    api_candidates: list[Candidate] = []
    session_candidates: list[dict] = []
    for i, c in enumerate(candidates):
        filename = f"{handle}_{i}.png"
        Image.fromarray(c["rgba"], mode="RGBA").save(tmp_dir / filename)
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

    if category_mismatch:
        # V-S7: trust the user's category and proceed regardless -- this is a log-only signal.
        log_failure({
            "event": "category_mismatch", "temp_handle": handle, "category": form.category.value,
            "garment_type": form.garment_type.value, "retailer_color": form.color,
            "timestamp": _now_iso(),
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

    src = tmp_media_dir() / cand["filename"]
    dest_dir = config.MEDIA_DIR / "items"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{slug}.png"
    src.replace(dest_path)

    try:
        media_store.persist(dest_path)
    except Exception as e:  # never insert an item document without its durable image
        return _error(ErrorCode.internal_error, f"Could not persist item image: {e}")

    doc = {
        "id": slug,
        "category": category.value,
        "garment_type": garment_type.value,
        "cutout_url": f"/media/items/{slug}.png",
        "primary_color": cand["primary_color"],
        "secondary_color": cand["secondary_color"],
        "retailer_color": session.get("retailer_color"),
        "retailer_item_name": session.get("retailer_item_name"),
        "attributes": tag_item(dest_path, category.value),   # {} on any failure (degraded)
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


@router.patch("/{slug}")
def rename_item(slug: str, body: RenameRequest, db=Depends(get_db)):
    """2.3.0/2.4.0: edit a saved item's display name and/or its details (attributes). Only those
    fields change; the id and every other piece of data stored under it stay the same."""
    doc = db["items"].find_one({"id": slug})
    if doc is None:
        return _error(ErrorCode.not_found, f"No item with id {slug!r}.")
    update: dict = {}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            return _error(ErrorCode.invalid_request, "The name can't be empty.")
        update["retailer_item_name"] = name
    if body.attributes is not None:
        attrs = dict(doc.get("attributes") or {})
        for key, value in body.attributes.items():
            key, value = key.strip(), value.strip()
            if not key:
                continue
            if value:
                attrs[key] = value          # any value is fine, known or not
            else:
                attrs.pop(key, None)        # "" removes the detail
        update["attributes"] = attrs
    db["items"].update_one({"id": slug}, {"$set": update})
    return _to_item(db["items"].find_one({"id": slug}))


@router.delete("/{slug}")
def archive_item(slug: str, db=Depends(get_db)):
    """2.6.0: remove an item from the closet by moving its document to `items_archive`
    (reversible; the cutout image and everything stored under the id are kept)."""
    doc = db["items"].find_one({"id": slug})
    if doc is None:
        return _error(ErrorCode.not_found, f"No item with id {slug!r}.")
    archived = {k: v for k, v in doc.items() if k != "_id"}
    if db["items_archive"].find_one({"id": slug}) is None:
        db["items_archive"].insert_one(archived)
    db["items"].delete_one({"id": slug})
    return RejectResponse(ok=True)
