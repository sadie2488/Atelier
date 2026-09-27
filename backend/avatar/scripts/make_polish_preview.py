"""A3/A5 visual-polish preview: render the avatar + a local composite for real photos, so a human
can eyeball the new silhouette/limb/face drawing without going through pose validation (the two
model photos currently fail the arm-angle check while new photos are retaken -- see the lane
report). This calls landmark detection, rig, and drawing directly, the same way
`backend/avatar/service.py:scan()` does minus the `validate_pose` step. Debug aid only, not part
of the API; never copies the source photos anywhere outside media/_preview/.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageOps

from backend.avatar import compositing, face as face_mod, media, skin
from backend.avatar.draw import draw_avatar, draw_wireframe
from backend.avatar.landmarks import detect_landmarks
from backend.avatar.rig import canvas_bbox, compute_rig, translate
from contract.enums import GarmentType

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
PREVIEW_DIR = ROOT / "media" / "_preview"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PHOTOS = {
    "sadie": MODELS_DIR / "model.sadie.jpeg",
    "lalitha": MODELS_DIR / "model.lalitha.jpeg",
}

# Two real cutouts already on disk under media/items/ (no bottom_* exists there yet, so this
# pairs a top with a jacket -- still exercises real-asset placement and the jacket-over-top part
# of the A-R4 draw order). Anchors are placed by hand since these fixture PNGs carry none.
TOP_ITEM = {
    "cutout_url": "/media/items/top_26a465.png",
    "garment_type": GarmentType.shirt,
    "anchors": {
        "left_shoulder": [0.82, 0.04], "right_shoulder": [0.18, 0.04],
        "left_hip": [0.85, 0.62], "right_hip": [0.15, 0.62],
    },
}
JACKET_ITEM = {
    "cutout_url": "/media/items/jacket_634a40.png",
    "garment_type": GarmentType.jacket,
    "anchors": {
        "left_shoulder": [0.88, 0.05], "right_shoulder": [0.12, 0.05],
        "left_hip": [0.90, 0.70], "right_hip": [0.10, 0.70],
    },
}


def _load_layer(item: dict):
    cutout = media.load_media(item["cutout_url"])
    return cutout, item["anchors"], item["garment_type"]


def build_one(name: str, photo_path: Path) -> None:
    img = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    rgb = np.asarray(img)

    landmarks = detect_landmarks(rgb)
    if landmarks is None:
        print(f"{name}: no person detected, skipping")
        return

    # Deliberately skip pose_validation.validate() -- these two photos are known to fail the
    # arm-angle check (15-20 degrees vs the 25 degree rule) while new photos are retaken. This is
    # a drawing-only preview, not a scan-acceptance test.
    rig = compute_rig(landmarks)
    x0, y0, x1, y1 = canvas_bbox(rig)
    w, h = max(1, round(x1 - x0)), max(1, round(y1 - y0))
    local = translate(rig, -x0, -y0)

    # These are full-body photos (arms-length-ish framing), so the face is a small fraction of
    # the frame -- too small for blaze_face_short_range to find directly (confirmed: returns
    # None on the raw image). Crop around the rig's own head estimate first, purely to give the
    # same detector a bigger, more face-filling region to work with; face.py itself is untouched.
    hx, hy = rig.head_center
    pad = rig.head_radius * 3.0
    ih, iw = rgb.shape[:2]
    cx0, cy0 = max(0, int(hx - pad)), max(0, int(hy - pad))
    cx1, cy1 = min(iw, int(hx + pad)), min(ih, int(hy + pad))
    head_crop = rgb[cy0:cy1, cx0:cx1]

    face_box = face_mod.detect_face_box(head_crop) if head_crop.size else None
    face_img = face_mod.crop_face(head_crop, face_box) if face_box else None
    face_patch_center = (
        (cx0 + (face_box[0] + face_box[2]) / 2, cy0 + (face_box[1] + face_box[3]) / 2) if face_box else None
    )
    skin_rgb = skin.sample_skin_tone(rgb, landmarks, face_patch_center)

    avatar_img = draw_avatar(local, (w, h), skin_rgb, face_img)
    avatar_img.save(PREVIEW_DIR / f"polish_avatar_{name}.png")

    top = _load_layer(TOP_ITEM)
    jacket = _load_layer(JACKET_ITEM)
    composed = compositing.composite_outfit(avatar_img, (w, h), local, bottom=None, top=top, jacket=jacket)
    composed.save(PREVIEW_DIR / f"polish_render_{name}.png")

    print(f"{name}: wrote polish_avatar_{name}.png and polish_render_{name}.png ({w}x{h})")


def main():
    for name, path in MODEL_PHOTOS.items():
        build_one(name, path)


if __name__ == "__main__":
    main()
