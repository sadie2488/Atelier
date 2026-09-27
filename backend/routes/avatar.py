"""Avatar lane: /api/avatar/* and /api/render/*.

A1-A6: capture + pose validation, wireframe rig, avatar assembly, placement, local compositing,
and the two-stage render endpoint. A7: POST /render returns the local composite immediately and,
when generation is possible, status `pending` while a background worker
(backend/avatar/background.py) attempts the Gemini try-on and verification off this thread; when
it is not possible (no key, or an avatar with no stored source photo), status is `failed` right
away -- A7 is fully severable (A-R6).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from backend.db import get_db
from contract.enums import ErrorCode
from contract.schemas import Avatar, AvatarScanResponse, RenderJob, RenderRequest

from backend.avatar import ids, prewarm, service
from backend.avatar.errors import AvatarError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["avatar"])

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.invalid_request: 400,
    ErrorCode.unsupported_image: 415,
    ErrorCode.no_person_detected: 422,
    ErrorCode.pose_rejected: 422,
    ErrorCode.not_found: 404,
    ErrorCode.internal_error: 500,
}


def _error(code: ErrorCode, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=_STATUS_BY_CODE.get(code, 500),
        content={"error": {"code": code.value, "message": message}},
    )


def _clean(doc: dict, model) -> dict:
    """Strip `_id` and any DB-only field (e.g. rig, canvas_w/h) before validating."""
    return {k: v for k, v in doc.items() if k in model.model_fields}


@router.post("/avatar/scan")
async def scan(image: UploadFile = File(...), db=Depends(get_db)):
    data = await image.read()
    try:
        doc = service.scan(data, db["avatars"])
    except AvatarError as e:
        return _error(e.code, e.message)
    except Exception:  # A9: never an unhandled exception / bare 500
        logger.exception("avatar: scan failed unexpectedly")
        return _error(ErrorCode.internal_error, "Could not process the photo.")
    db["avatars"].insert_one(doc)
    prewarm.schedule(doc, db)  # background; never delays or fails the scan
    return AvatarScanResponse.model_validate(_clean(doc, AvatarScanResponse))


@router.get("/avatar/{avatar_id}")
def get_avatar(avatar_id: str, db=Depends(get_db)):
    doc = db["avatars"].find_one({"avatar_id": avatar_id})
    if doc is None:
        return _error(ErrorCode.not_found, f"No avatar with id {avatar_id!r}.")
    return Avatar.model_validate(_clean(doc, Avatar))


@router.post("/render")
def render(body: RenderRequest, db=Depends(get_db)):
    avatar_doc = db["avatars"].find_one({"avatar_id": body.avatar_id})
    if avatar_doc is None:
        return _error(ErrorCode.not_found, f"No avatar with id {body.avatar_id!r}.")

    render_id = ids.render_id_for(body.avatar_id, body.top_id, body.bottom_id, body.jacket_id)
    cached = db["renders"].find_one({"render_id": render_id})
    if cached is not None:
        cached = service.settle_if_stale(cached, db["renders"])
        if cached.get("status") != "failed":
            return RenderJob.model_validate(_clean(cached, RenderJob))
        # A failed try-on is retried when the user asks again, not cached forever.
        db["renders"].delete_one({"render_id": render_id})

    top_doc = db["items"].find_one({"id": body.top_id})
    if top_doc is None:
        return _error(ErrorCode.not_found, f"Item {body.top_id!r} does not exist.")
    bottom_doc = db["items"].find_one({"id": body.bottom_id})
    if bottom_doc is None:
        return _error(ErrorCode.not_found, f"Item {body.bottom_id!r} does not exist.")
    jacket_doc: Optional[dict] = None
    if body.jacket_id is not None:
        jacket_doc = db["items"].find_one({"id": body.jacket_id})
        if jacket_doc is None:
            return _error(ErrorCode.not_found, f"Item {body.jacket_id!r} does not exist.")

    try:
        job = service.render(render_id, avatar_doc, top_doc, bottom_doc, jacket_doc, db["renders"])
    except AvatarError as e:
        return _error(e.code, e.message)
    except Exception:  # A9: never an unhandled exception / bare 500
        logger.exception("avatar: render failed unexpectedly")
        return _error(ErrorCode.internal_error, "Could not build the render.")

    return RenderJob.model_validate(_clean(job, RenderJob))


@router.get("/render/{render_id}")
def get_render(render_id: str, db=Depends(get_db)):
    doc = db["renders"].find_one({"render_id": render_id})
    if doc is None:
        return _error(ErrorCode.not_found, f"No render with id {render_id!r}.")
    doc = service.settle_if_stale(doc, db["renders"])
    return RenderJob.model_validate(_clean(doc, RenderJob))
