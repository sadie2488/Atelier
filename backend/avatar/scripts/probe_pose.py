"""Debug probe: run PoseLandmarker on a few fixture images to see what lands. Not a test."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
POSE_MODEL_PATH = MODELS_DIR / "pose_landmarker_lite.task"

CANDIDATES = [
    "light vintage Lowest-Rise Baggy Wide-Leg Jean #a8bdca.png",
    "leaf green short-sleev midi dress #105243.png",
    "bordeaux short sleeve plaid mini dress #4a1825.png",
    "red Whoa So Soft Shrunken Fairisle Cardigan Sweater #661720.png",
]

LM_NAMES = {
    0: "nose", 11: "left_shoulder", 12: "right_shoulder", 13: "left_elbow", 14: "right_elbow",
    15: "left_wrist", 16: "right_wrist", 23: "left_hip", 24: "right_hip",
    25: "left_knee", 26: "right_knee", 27: "left_ankle", 28: "right_ankle",
}


def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    base = mp_python.BaseOptions(model_asset_path=str(POSE_MODEL_PATH))
    opts = mp_vision.PoseLandmarkerOptions(
        base_options=base, running_mode=mp_vision.RunningMode.IMAGE,
        num_poses=1, output_segmentation_masks=False,
        min_pose_detection_confidence=0.5, min_pose_presence_confidence=0.5,
    )
    landmarker = mp_vision.PoseLandmarker.create_from_options(opts)

    for name in CANDIDATES:
        path = ROOT / "fixtures" / "images" / name
        img = Image.open(path).convert("RGB")
        rgb = np.asarray(img)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)
        print(f"\n=== {name} ({img.width}x{img.height}) ===")
        if not result.pose_landmarks:
            print("  NO PERSON DETECTED")
            continue
        lm = result.pose_landmarks[0]
        for idx, nm in LM_NAMES.items():
            p = lm[idx]
            print(f"  {nm:15s} x={p.x:.3f} y={p.y:.3f} vis={p.visibility:.3f} pres={p.presence:.3f}")


if __name__ == "__main__":
    main()
