"""Orchestration for POST /avatar/scan and POST/GET /render -- the local composite path
(A1-A6). No Gemini here: A7 (generation) is out of scope for this dispatch, so render always
returns status `failed` with a correct, present local_url (A-R2, A-R6, A-R12), shaped so a
later background job can flip a `pending` row to `done` without changing this shape.
"""
import io
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from PIL import Image, UnidentifiedImageError

from contract.enums import ErrorCode, GarmentType, MAX_UPLOAD_BYTES, RenderStatus

from . import compositing, face, ids, media, skin
from .draw import draw_avatar, draw_wireframe
from .errors import AvatarError
from .landmarks import detect_landmarks
from .pose_validation import validate as validate_pose
from .rig import canvas_bbox, compute_rig, rig_from_dict, rig_to_dict, translate


def _decode_image(data: bytes) -> np.ndarray:
    if len(data) > MAX_UPLOAD_BYTES:
        raise AvatarError(ErrorCode.invalid_request, "Photo is too large.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise AvatarError(ErrorCode.unsupported_image, "Could not read the uploaded photo.") from e
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

    face_box = face.detect_face_box(rgb)
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

    return {
        "avatar_id": avatar_id,
        "wireframe_url": wireframe_url,
        "avatar_url": avatar_url,
        "created_at": datetime.now(timezone.utc),
        "rig": rig_to_dict(rig_local),
        "canvas_w": canvas_w,
        "canvas_h": canvas_h,
    }


def _load_item_layer(item_doc: dict) -> tuple[Image.Image, dict, GarmentType]:
    cutout = media.load_from_url(item_doc["cutout_url"])
    anchors = item_doc.get("anchors") or {}
    garment_type = GarmentType(item_doc["garment_type"])
    return cutout, anchors, garment_type


def render(
    render_id: str,
    avatar_doc: dict,
    top_doc: dict,
    bottom_doc: dict,
    jacket_doc: Optional[dict],
) -> dict:
    """-> a render doc (contract fields) ready to insert. The local composite is built now and
    always succeeds from here on; without A7 there is no generation step to run."""
    rig = rig_from_dict(avatar_doc["rig"])
    canvas_size = (avatar_doc["canvas_w"], avatar_doc["canvas_h"])
    avatar_img = media.load_from_url(avatar_doc["avatar_url"])

    bottom = _load_item_layer(bottom_doc)
    top = _load_item_layer(top_doc)
    jacket = _load_item_layer(jacket_doc) if jacket_doc is not None else None

    composed = compositing.composite_outfit(avatar_img, canvas_size, rig, bottom=bottom, top=top, jacket=jacket)
    local_url = media.save_png(composed, "renders", f"{render_id}_local.png")

    return {
        "render_id": render_id,
        "status": RenderStatus.failed.value,
        "local_url": local_url,
        "generated_url": None,
    }
