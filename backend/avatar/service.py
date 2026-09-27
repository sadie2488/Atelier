"""Orchestration for POST /avatar/scan and POST/GET /render.

The local composite (A1-A6) is always built synchronously and always succeeds from there on --
it is what POST /render returns immediately (A-R2, A-R6). A7 generation, when possible (a
Gemini key is configured and the scan kept its source photo), is handed to a background worker
(backend/avatar/background.py) that never runs on the request path; this module only decides
whether to start it and returns `pending` in that case, or `failed` if generation is not
possible at all (severability, A-R6).
"""
import io
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from backend import config
from contract.enums import ErrorCode, GarmentType, MAX_UPLOAD_BYTES, RenderStatus

from . import background, compositing, face, ids, media, skin
from .draw import draw_avatar, draw_wireframe
from .errors import AvatarError
from .landmarks import LM_INDEX, detect_landmarks
from .pose_validation import validate as validate_pose
from .rig import canvas_bbox, compute_rig, rig_from_dict, rig_to_dict, translate

# A phone camera frame can be 4000-6000px on its long side. Landmarking, drawing (draw.py's own
# SUPERSAMPLE_MAX_DIM=1200 already assumes a canvas well under this), the stored source photo,
# and the Gemini upload only need demo resolution -- downscaling once here, right after decode,
# bounds latency and payload size everywhere downstream instead of every consumer guessing.
MAX_LONG_SIDE = 1600


def _downscale(img: Image.Image, max_long_side: int = MAX_LONG_SIDE) -> Image.Image:
    long_side = max(img.width, img.height)
    if long_side <= max_long_side:
        return img
    scale = max_long_side / long_side
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(new_size, Image.LANCZOS)


def _decode_image(data: bytes) -> np.ndarray:
    if len(data) > MAX_UPLOAD_BYTES:
        raise AvatarError(ErrorCode.invalid_request, "Photo is too large.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        # Phone photos carry EXIF orientation; without correcting it first, landmarks, the rig,
        # and the composited face all land rotated relative to what the person actually sees.
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise AvatarError(ErrorCode.unsupported_image, "Could not read the uploaded photo.") from e
    img = _downscale(img)
    return np.asarray(img)


def scan(image_bytes: bytes, avatars_collection) -> dict:
    """-> an avatar doc (contract fields + DB-only rig/canvas) ready to insert. Raises AvatarError."""
    rgb = _decode_image(image_bytes)

    landmarks = detect_landmarks(rgb)
    if landmarks is None:
        raise AvatarError(
            ErrorCode.no_person_detected,
            "No person found in the photo. Step back so your whole body is in the outline.",
        )

    rejection = validate_pose(landmarks)
    if rejection is not None:
        code, message = rejection
        raise AvatarError(code, message)

    rig = compute_rig(landmarks)
    x0, y0, x1, y1 = canvas_bbox(rig)
    canvas_w, canvas_h = max(1, round(x1 - x0)), max(1, round(y1 - y0))
    rig_local = translate(rig, -x0, -y0)

    face_box = face.detect_face_box_near(rgb, rig.head_center, rig.head_radius)
    face_img = None
    face_patch_center = None
    if face_box is not None:
        face_img = face.crop_face(rgb, face_box)
        fx0, fy0, fx1, fy1 = face_box
        face_patch_center = ((fx0 + fx1) / 2, (fy0 + fy1) / 2)

    skin_rgb = skin.sample_skin_tone(rgb, landmarks, face_patch_center)

    wireframe_img = draw_wireframe(rig_local, (canvas_w, canvas_h))
    avatar_img = draw_avatar(rig_local, (canvas_w, canvas_h), skin_rgb, face_img)

    avatar_id = ids.new_avatar_id(lambda aid: avatars_collection.find_one({"avatar_id": aid}) is not None)
    wireframe_url = media.save_png(wireframe_img, "avatars", f"{avatar_id}_wireframe.png")
    avatar_url = media.save_png(avatar_img, "avatars", f"{avatar_id}.png")
    # A7: kept for the generation call, which needs a real photo, not the line-art avatar.
    source_photo_url = media.save_png(Image.fromarray(rgb), "avatars", f"{avatar_id}_photo.png")

    return {
        "avatar_id": avatar_id,
        "wireframe_url": wireframe_url,
        "avatar_url": avatar_url,
        "created_at": datetime.now(timezone.utc),
        "rig": rig_to_dict(rig_local),
        "canvas_w": canvas_w,
        "canvas_h": canvas_h,
        "source_photo_url": source_photo_url,
        "source_landmarks": {name: [landmarks[name][0], landmarks[name][1]] for name in LM_INDEX},
        "source_w": rgb.shape[1],
        "source_h": rgb.shape[0],
    }


# A process restart mid-generation orphans a job in `pending` forever, since nothing is left to
# flip it. Treated as stale (and settled to `failed` on the next read) once older than this --
# comfortably past the frontend's 45s give-up (BACKEND_API.md), so a genuinely slow-but-alive
# job is never reaped out from under a client still polling it.
PENDING_STALE_SECONDS = 90


def settle_if_stale(job: dict, renders_collection) -> dict:
    """A `pending` render older than PENDING_STALE_SECONDS is orphaned -- settle it to `failed`
    here, on read (GET /render/{id}, or a cache hit in POST /render), instead of leaving it to
    poll forever. Returns the (possibly updated) doc; a no-op for anything not stale-pending.
    """
    if job.get("status") != RenderStatus.pending.value:
        return job
    pending_since = job.get("pending_since")
    if pending_since is None:
        return job
    age = (datetime.now(timezone.utc) - pending_since).total_seconds()
    if age <= PENDING_STALE_SECONDS:
        return job

    renders_collection.update_one(
        {"render_id": job["render_id"]},
        {"$set": {"status": RenderStatus.failed.value, "generated_url": None}},
    )
    return {**job, "status": RenderStatus.failed.value, "generated_url": None}


def _load_item_layer(item_doc: dict) -> tuple[Image.Image, dict, GarmentType]:
    cutout = media.load_media(item_doc["cutout_url"])
    anchors = item_doc.get("anchors") or {}
    garment_type = GarmentType(item_doc["garment_type"])
    return cutout, anchors, garment_type


def render(
    render_id: str,
    avatar_doc: dict,
    top_doc: dict,
    bottom_doc: dict,
    jacket_doc: Optional[dict],
    renders_collection,
) -> dict:
    """-> the render doc as inserted (contract fields). The local composite is built here and
    always succeeds from this point on (A-R2, A-R6). If generation is possible, the doc is
    inserted as `pending` and a background job is started (backend/avatar/background.py, never
    on this thread); otherwise it is inserted as `failed` -- A7 is fully severable.
    """
    rig = rig_from_dict(avatar_doc["rig"])
    canvas_size = (avatar_doc["canvas_w"], avatar_doc["canvas_h"])
    avatar_img = media.load_media(avatar_doc["avatar_url"])

    bottom = _load_item_layer(bottom_doc)
    top = _load_item_layer(top_doc)
    jacket = _load_item_layer(jacket_doc) if jacket_doc is not None else None

    composed = compositing.composite_outfit(avatar_img, canvas_size, rig, bottom=bottom, top=top, jacket=jacket)
    local_url = media.save_png(composed, "renders", f"{render_id}_local.png")

    can_generate = bool(config.GEMINI_API_KEY) and bool(avatar_doc.get("source_photo_url"))
    status = RenderStatus.pending if can_generate else RenderStatus.failed

    job = {
        "render_id": render_id,
        "status": status.value,
        "local_url": local_url,
        "generated_url": None,
    }
    if can_generate:
        job["pending_since"] = datetime.now(timezone.utc)  # DB-only; see settle_if_stale()
    renders_collection.insert_one(job)

    if can_generate:
        background.submit(render_id, avatar_doc, top_doc, bottom_doc, jacket_doc, renders_collection)

    return job
