"""Bug-fix verification (2026-09-27): live webcam scans are landscape (e.g. 1080x608) with the
person standing far back -- a small fraction of the frame. Before the fix, segmenting the WHOLE
frame made every one of these fall back to the drawn mannequin. This script builds a synthetic
landscape frame from a real fixture photo (model.sadie.jpeg, shrunk and placed off-center on a
plain background) and runs the REAL pipeline end to end (real pose landmarker, real segmenter --
nothing mocked) to confirm `avatar_kind` now comes back `real_body` instead of falling back.

Writes media/_preview/landscape_fix_avatar.png and media/_preview/landscape_fix_wireframe.png.
Debug aid only, not part of the API; never copies the source photo anywhere outside media/_preview/.

    .venv/Scripts/python.exe backend/avatar/scripts/verify_landscape_fix.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageOps

from backend.avatar import person
from backend.avatar.landmarks import detect_landmarks
from backend.avatar.pose_validation import ARMS_MESSAGE_PREFIX, validate as validate_pose
from backend.avatar.rig import compute_rig
from backend.avatar.service import MAX_LONG_SIDE, _downscale, build_avatar_visuals

MODEL_PHOTO = Path(__file__).resolve().parents[1] / "models" / "model.sadie.jpeg"
PREVIEW_DIR = ROOT / "media" / "_preview"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

FRAME_SIZE = (1080, 608)  # landscape, like a laptop webcam
PERSON_HEIGHT_PX = 300    # "standing far back" -- well under half the frame height


def build_landscape_frame() -> np.ndarray:
    img = ImageOps.exif_transpose(Image.open(MODEL_PHOTO)).convert("RGB")
    img = _downscale(img, MAX_LONG_SIDE)

    scale = PERSON_HEIGHT_PX / img.height
    person_img = img.resize((max(1, round(img.width * scale)), PERSON_HEIGHT_PX), Image.LANCZOS)

    canvas = Image.new("RGB", FRAME_SIZE, (60, 60, 65))  # plain "webcam background"
    px = FRAME_SIZE[0] // 2 - person_img.width // 2 - 120  # off-center, not just dead-center
    py = FRAME_SIZE[1] - person_img.height - 40            # standing on a "floor" near the bottom
    canvas.paste(person_img, (px, py))
    return np.asarray(canvas)


def main():
    rgb = build_landscape_frame()
    Image.fromarray(rgb).save(PREVIEW_DIR / "landscape_fix_source.png")

    landmarks = detect_landmarks(rgb)
    if landmarks is None:
        print("no person detected in the synthetic landscape frame -- cannot verify")
        raise SystemExit(1)

    rejection = validate_pose(landmarks, (rgb.shape[1], rgb.shape[0]))
    if rejection is not None:
        lines = rejection[1].split("\n")
        other_lines = [line for line in lines if not line.startswith(ARMS_MESSAGE_PREFIX)]
        if other_lines:
            print(f"pose rejected for a reason other than arm angle: {'; '.join(other_lines)} -- cannot verify")
            raise SystemExit(1)
        print("bypassing arm-angle rejection for this debug verification (fixture photo's pose)")

    rig = compute_rig(landmarks)
    bbox = person.pose_bbox(rig, landmarks, (rgb.shape[1], rgb.shape[0]))
    bx0, by0, bx1, by1 = bbox
    frame_fraction = ((bx1 - bx0) * (by1 - by0)) / (rgb.shape[1] * rgb.shape[0])
    print(f"pose bbox is {frame_fraction * 100:.1f}% of the full frame "
          f"(MIN_PERSON_FRACTION={person.MIN_PERSON_FRACTION * 100:.0f}%)")

    t0 = time.perf_counter()
    visuals = build_avatar_visuals(rgb, landmarks)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"avatar_kind={visuals['avatar_kind']} canvas={visuals['canvas_w']}x{visuals['canvas_h']} "
          f"build_avatar_visuals={elapsed_ms:.0f}ms")

    visuals["avatar_img"].save(PREVIEW_DIR / "landscape_fix_avatar.png")
    visuals["wireframe_img"].save(PREVIEW_DIR / "landscape_fix_wireframe.png")
    print("wrote media/_preview/landscape_fix_{source,avatar,wireframe}.png")

    if visuals["avatar_kind"] != "real_body":
        print("FAIL: expected avatar_kind=real_body -- the landscape/small-person fix did not take effect")
        raise SystemExit(1)
    print("PASS: real-body avatar produced from a small person in a landscape frame")


if __name__ == "__main__":
    main()
