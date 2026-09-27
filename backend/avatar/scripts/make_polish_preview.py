"""A3/A5 visual-polish preview: render the avatar + a local composite for real photos, so a human
can eyeball the new silhouette/limb/face drawing without going through pose validation (the two
model photos currently fail the arm-angle check while new photos are retaken -- see the lane
report). This calls landmark detection, decode/downscale, rig, face, skin, and drawing the same
way `backend/avatar/service.py:scan()` does, except that it bypasses only the arm-angle rejection
from `pose_validation.validate()` -- every other rejection (missing/low-visibility landmarks)
still aborts the preview for that photo. Debug aid only, not part of the API; never copies the
source photos anywhere outside media/_preview/.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageOps

from backend.avatar import compositing, face as face_mod, media, skin
from backend.avatar.draw import draw_avatar
from backend.avatar.landmarks import detect_landmarks
from backend.avatar.pose_validation import ARMS_MESSAGE, validate as validate_pose
from backend.avatar.rig import canvas_bbox, compute_rig, translate
from backend.avatar.service import MAX_LONG_SIDE, _downscale
from contract.enums import GarmentType

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
PREVIEW_DIR = ROOT / "media" / "_preview"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PHOTOS = {
    "sadie": MODELS_DIR / "model.sadie.jpeg",
    "lalitha": MODELS_DIR / "model.lalitha.jpeg",
}

# Two real cutouts already on disk under media/items/. Anchors are placed by hand since these
# fixture PNGs carry none.
TOP_ITEM = {
    "cutout_url": "/media/items/top_26a465.png",
    "garment_type": GarmentType.shirt,
    "anchors": {
        "left_shoulder": [0.82, 0.04], "right_shoulder": [0.18, 0.04],
        "left_hip": [0.85, 0.62], "right_hip": [0.15, 0.62],
    },
}
BOTTOM_ITEM = {
    "cutout_url": "/media/items/bottom_0aad1c.png",
    "garment_type": GarmentType.pants,
    "anchors": {
        "left_hip": [0.85, 0.05], "right_hip": [0.15, 0.05],
        "left_knee": [0.80, 0.55], "right_knee": [0.20, 0.55],
        "left_ankle": [0.75, 0.97], "right_ankle": [0.25, 0.97],
    },
}


def _load_layer(item: dict):
    cutout = media.load_media(item["cutout_url"])
    return cutout, item["anchors"], item["garment_type"]


def build_one(name: str, photo_path: Path) -> None:
    # Same decode path as service._decode_image: EXIF-correct, then downscale to the same
    # MAX_LONG_SIDE everything else in the pipeline uses.
    img = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    img = _downscale(img)
    rgb = np.asarray(img)

    landmarks = detect_landmarks(rgb)
    if landmarks is None:
        print(f"{name}: no person detected, skipping")
        return

    # Bypass ONLY the arm-angle rejection -- these two photos are known to fail it (15-20 degrees
    # vs the 25 degree rule) while new photos with arms out are retaken. ARM_ANGLE_MIN_DEG stays
    # untouched in pose_validation.py; any other rejection reason (e.g. a landmark out of frame)
    # still aborts this preview, same as a real scan.
    rejection = validate_pose(landmarks)
    if rejection is not None and rejection[1] != ARMS_MESSAGE:
        print(f"{name}: pose rejected ({rejection[1]}), skipping")
        return
    if rejection is not None:
        print(f"{name}: bypassing arm-angle rejection for this debug preview (real photos pending retake)")

    rig = compute_rig(landmarks)
    x0, y0, x1, y1 = canvas_bbox(rig)
    w, h = max(1, round(x1 - x0)), max(1, round(y1 - y0))
    local = translate(rig, -x0, -y0)

    # Production face-detection path (A-B6/A9): crop around the rig's own head estimate first --
    # on a full-body photo the face is too small for the detector to find directly -- then map
    # the box back to full-frame coordinates. Falls back to no composited face (the plain drawn
    # head) if the crop also finds nothing; there is no lower rung (A-B8).
    face_box = face_mod.detect_face_box_near(rgb, rig.head_center, rig.head_radius)
    face_img = face_mod.crop_face(rgb, face_box) if face_box is not None else None
    face_patch_center = ((face_box[0] + face_box[2]) / 2, (face_box[1] + face_box[3]) / 2) if face_box else None

    skin_rgb = skin.sample_skin_tone(rgb, landmarks, face_patch_center)
    print(f"{name}: sampled skin hex #{skin_rgb[0]:02x}{skin_rgb[1]:02x}{skin_rgb[2]:02x}, face_detected={face_box is not None}")

    avatar_img = draw_avatar(local, (w, h), skin_rgb, face_img)
    avatar_img.save(PREVIEW_DIR / f"polish_avatar_{name}.png")

    top = _load_layer(TOP_ITEM)
    bottom = _load_layer(BOTTOM_ITEM)
    composed = compositing.composite_outfit(avatar_img, (w, h), local, bottom=bottom, top=top, jacket=None)
    composed.save(PREVIEW_DIR / f"polish_render_{name}.png")

    print(f"{name}: wrote polish_avatar_{name}.png and polish_render_{name}.png ({w}x{h}, downscaled to <= {MAX_LONG_SIDE}px long side)")


def main():
    for name, path in MODEL_PHOTOS.items():
        build_one(name, path)


if __name__ == "__main__":
    main()
