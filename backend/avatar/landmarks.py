"""A1/A2: pose landmark extraction. MediaPipe Pose -> named pixel landmarks (A-B1)."""
from typing import Optional

import numpy as np

from .mp_models import pose_landmarker

# MediaPipe BlazePose 33-point indices, person's own left/right (matches ARTIFACT_SPEC naming).
LM_INDEX = {
    "nose": 0,
    "left_shoulder": 11, "right_shoulder": 12,
    "left_elbow": 13, "right_elbow": 14,
    "left_wrist": 15, "right_wrist": 16,
    "left_hip": 23, "right_hip": 24,
    "left_knee": 25, "right_knee": 26,
    "left_ankle": 27, "right_ankle": 28,
}


def detect_landmarks(rgb: np.ndarray) -> Optional[dict[str, tuple[float, float, float]]]:
    """-> {name: (x_px, y_px, visibility)} for the detected person, or None if nobody is found."""
    import mediapipe as mp

    h, w = rgb.shape[:2]
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = pose_landmarker().detect(mp_image)
    if not result.pose_landmarks:
        return None
    lm = result.pose_landmarks[0]
    return {name: (lm[idx].x * w, lm[idx].y * h, lm[idx].visibility) for name, idx in LM_INDEX.items()}
