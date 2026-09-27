"""Orchestration for POST /avatar/scan and POST/GET /render.

The local composite (A1-A6) is always built synchronously and always succeeds from there on --
it is what POST /render returns immediately (A-R2, A-R6). A7 generation, when possible (a
Gemini key is configured and the scan kept its source photo), is handed to a background worker
(backend/avatar/background.py) that never runs on the request path; this module only decides
whether to start it and returns `pending` in that case, or `failed` if generation is not
possible at all (severability, A-R6).
"""
import io
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from backend import config
from contract.enums import ErrorCode, GarmentType, MAX_UPLOAD_BYTES, RenderStatus

from . import background, compositing, face, ids, media, person, skin
from .draw import draw_wireframe
from .errors import AvatarError
from .landmarks import LM_INDEX, detect_landmarks
from .pose_validation import validate as validate_pose
from .rig import compute_rig, rig_from_dict, rig_to_dict, translate

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


def build_avatar_visuals(rgb: np.ndarray, landmarks: dict) -> dict:
    """rig -> the avatar image, wireframe image, local rig, and canvas size, on ONE shared
    canvas geometry. Shared by scan() and backend/avatar/scripts/reprocess_avatar.py, so a
    reprocessed avatar is built by exactly the same code as a fresh scan.

    A3 change (human decision 2026-09-26; A-B3 superseded in contract/DECISIONS.md), tightened
    2026-09-27 ("no mannequin at all" -- live landscape webcam scans were falling back to it):
    the avatar image is now ALWAYS a real photo of the person, never line art --
      - a real-body cutout (person.build_person_cutout) when the person mask is plausible, or
      - a plain photo crop of the person (person.photo_crop_fallback), vignetted to transparency
        at its edges, when segmentation fails or is implausible.
    Both are built from the person's own pose bounding box (person.pose_bbox -- head to feet, from
    the landmarks already detected for the rig), not the whole frame, so a person who is a small
    fraction of a landscape frame is still a large fraction of the region actually analyzed
    (backend/avatar/person.py's module docstring has the full story).

    The wireframe is always drawn on the SAME canvas geometry as the avatar image (it is no longer
    ever the avatar itself), so the two align pixel-for-pixel; it remains available as the render
    loading state (`wireframe_url`) and as placement's rig either way.
    """
    rig = compute_rig(landmarks)
    frame_size = (rgb.shape[1], rgb.shape[0])
    bbox = person.pose_bbox(rig, landmarks, frame_size)
    ankle_y = (rig.landmarks["left_ankle"][1] + rig.landmarks["right_ankle"][1]) / 2.0

    shoulder_y = min(rig.landmarks["left_shoulder"][1], rig.landmarks["right_shoulder"][1])
    ankle_xs = (rig.landmarks["left_ankle"][0], rig.landmarks["right_ankle"][0])
    cutout = person.build_person_cutout(rgb, bbox, ankle_y=ankle_y, shoulder_y=shoulder_y, ankle_xs=ankle_xs)
    if cutout is not None:
        crop_img, full_bbox = cutout
        avatar_kind = "real_body"
    else:
        crop_img = person.photo_crop_fallback(rgb, bbox)
        full_bbox = bbox
        avatar_kind = "photo_crop"

    # Feet slightly cut off by the bottom of the frame (accepted by pose_validation's
    # FEET_CROP_MAX_FRACTION): the rig's ankles are MediaPipe's estimate below the photo. Extend
    # the crop downward with transparent rows so the canvas still contains the estimated feet and
    # bottoms/dresses anchored to the ankles are not clipped by the canvas edge.
    if max(rig.landmarks["left_ankle"][1], rig.landmarks["right_ankle"][1]) > frame_size[1]:
        feet_bottom = max(rig.landmarks["left_ankle"][1], rig.landmarks["right_ankle"][1]) + (
            rig.shoulder_width * person.FOOT_ALLOWANCE_FRACTION)
        extra = int(round(feet_bottom - full_bbox[3]))
        if extra > 0:
            grown = Image.new("RGBA", (crop_img.width, crop_img.height + extra), (0, 0, 0, 0))
            grown.alpha_composite(crop_img.convert("RGBA"), (0, 0))
            crop_img = grown

    canvas_img, (ox, oy) = person.pad_to_ratio(crop_img)
    canvas_w, canvas_h = canvas_img.size
    fx0, fy0, _fx1, _fy1 = full_bbox
    rig_local = translate(rig, -fx0 + ox, -fy0 + oy)
    wireframe_img = draw_wireframe(rig_local, (canvas_w, canvas_h))

    return {
        "avatar_img": canvas_img,
        "wireframe_img": wireframe_img,
        "rig_local": rig_local,
        "canvas_w": canvas_w,
        "canvas_h": canvas_h,
        "avatar_kind": avatar_kind,
    }


def scan(image_bytes: bytes, avatars_collection) -> dict:
    """-> an avatar doc (contract fields + DB-only rig/canvas) ready to insert. Raises AvatarError."""
    rgb = _decode_image(image_bytes)

    landmarks = detect_landmarks(rgb)
    if landmarks is None:
        raise AvatarError(
            ErrorCode.no_person_detected,
            "No one found in the photo — step back so your whole body is in the frame, in good light.",
        )

    rejection = validate_pose(landmarks, (rgb.shape[1], rgb.shape[0]))
    if rejection is not None:
        code, message = rejection
        raise AvatarError(code, message)

    visuals = build_avatar_visuals(rgb, landmarks)

    avatar_id = ids.new_avatar_id(lambda aid: avatars_collection.find_one({"avatar_id": aid}) is not None)
    wireframe_url = media.save_png(visuals["wireframe_img"], "avatars", f"{avatar_id}_wireframe.png")
    avatar_url = media.save_png(visuals["avatar_img"], "avatars", f"{avatar_id}.png")
    # A7: kept for the generation call, which needs a real photo, not the line-art avatar.
    source_photo_url = media.save_png(Image.fromarray(rgb), "avatars", f"{avatar_id}_photo.png")

    return {
        "avatar_id": avatar_id,
        "wireframe_url": wireframe_url,
        "avatar_url": avatar_url,
        "created_at": datetime.now(timezone.utc),
        "rig": rig_to_dict(visuals["rig_local"]),
        "canvas_w": visuals["canvas_w"],
        "canvas_h": visuals["canvas_h"],
        "avatar_kind": visuals["avatar_kind"],  # DB-only; not part of the contract (see routes_avatar._clean)
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
    # A claimed (running) job is timed from when it started, not from when it was queued: a
    # prewarm job can sit queued behind others and must not be reaped the moment it starts.
    pending_since = job.get("started_at") or job.get("pending_since")
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
    prewarm: bool = False,
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
        job["attempt"] = uuid.uuid4().hex  # DB-only; background._claim/_update match on it
        job["claimed"] = False
    renders_collection.insert_one(job)

    if can_generate:
        background.submit(render_id, avatar_doc, top_doc, bottom_doc, jacket_doc, renders_collection,
                          prewarm=prewarm, attempt=job["attempt"])

    return job
