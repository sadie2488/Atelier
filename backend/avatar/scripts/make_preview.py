"""Build a preview avatar + local composite for the human to eyeball, since there is no real
full-body scan fixture yet. Uses a hand-built standing pose (same shape as the unit tests) and
borrows a real face crop from a fixture photo via the actual face detector. Writes to
media/_preview/ -- not part of the API, just a debug aid.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from backend.avatar import compositing, face as face_mod, skin
from backend.avatar.draw import draw_avatar, draw_wireframe
from backend.avatar.placement import PRIMARY_ANCHORS
from backend.avatar.rig import canvas_bbox, compute_rig, translate
from contract.enums import GarmentType

PREVIEW_DIR = ROOT / "media" / "_preview"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def good_landmarks():
    return {
        "nose": (200.0, 80.0, 0.99),
        "left_shoulder": (250.0, 150.0, 0.99), "right_shoulder": (150.0, 150.0, 0.99),
        "left_elbow": (350.0, 160.0, 0.99), "right_elbow": (50.0, 160.0, 0.99),
        "left_wrist": (400.0, 170.0, 0.99), "right_wrist": (10.0, 170.0, 0.99),
        "left_hip": (230.0, 400.0, 0.99), "right_hip": (170.0, 400.0, 0.99),
        "left_knee": (230.0, 560.0, 0.99), "right_knee": (170.0, 560.0, 0.99),
        "left_ankle": (230.0, 700.0, 0.99), "right_ankle": (170.0, 700.0, 0.99),
    }


def main():
    lm = good_landmarks()
    rig = compute_rig(lm)
    x0, y0, x1, y1 = canvas_bbox(rig)
    w, h = max(1, round(x1 - x0)), max(1, round(y1 - y0))
    local = translate(rig, -x0, -y0)

    # Borrow a real face via the real face detector, from a fixture photo (not a full-body one).
    photo = np.asarray(Image.open(
        ROOT / "fixtures" / "images" / "bordeaux short sleeve plaid mini dress #4a1825.png"
    ).convert("RGB"))
    box = face_mod.detect_face_box(photo)
    face_img = face_mod.crop_face(photo, box) if box else None
    face_patch_center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) if box else None
    skin_rgb = skin.sample_skin_tone(photo, lm, face_patch_center)

    wireframe = draw_wireframe(local, (w, h))
    avatar_img = draw_avatar(local, (w, h), skin_rgb, face_img)
    wireframe.save(PREVIEW_DIR / "preview_wireframe.png")
    avatar_img.save(PREVIEW_DIR / "preview_avatar.png")

    # A small local-composite preview: a colored "pants" + "shirt" rectangle placed via the
    # same A4 similarity-transform placement code the render endpoint uses.
    def rect_cutout(color, size=(140, 260)):
        return Image.new("RGBA", size, (*color, 255))

    bottom = (rect_cutout((60, 90, 160)), {
        "left_hip": [0.85, 0.0], "right_hip": [0.15, 0.0],
        "left_knee": [0.85, 0.5], "right_knee": [0.15, 0.5],
        "left_ankle": [0.85, 1.0], "right_ankle": [0.15, 1.0],
    }, GarmentType.pants)
    top = (rect_cutout((190, 60, 60), size=(150, 150)), {
        "left_shoulder": [0.85, 0.0], "right_shoulder": [0.15, 0.0],
        "left_hip": [0.85, 1.0], "right_hip": [0.15, 1.0],
    }, GarmentType.shirt)

    composed = compositing.composite_outfit(avatar_img, (w, h), local, bottom=bottom, top=top)
    composed.save(PREVIEW_DIR / "preview_render_local.png")

    print("wrote:")
    for p in ("preview_wireframe.png", "preview_avatar.png", "preview_render_local.png"):
        print(" ", PREVIEW_DIR / p)


if __name__ == "__main__":
    main()
