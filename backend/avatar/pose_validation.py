"""A-P3: pose landmarks checked against the outline tolerance. Reject with a specific,
actionable reason, never a generic failure. A-B8: landmarks missing -> reject, no lower rung.
"""
import math
from typing import Optional

from contract.enums import ErrorCode

VISIBILITY_MIN = 0.5
# Human decision 2026-09-26: 25° rejected natural relaxed stances (real scans measured 15-23°);
# 12° still rejects arms pressed flat against the torso.
ARM_ANGLE_MIN_DEG = 12.0

_BODY_REQUIRED = [
    "nose", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]

STEP_BACK_MESSAGE = "Step back so your whole body, shoulders to ankles, is visible in the frame."
ARMS_MESSAGE = "Move your arms slightly away from your body."


def _angle_deg(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """Angle at point b, between rays b->a and b->c, in degrees."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    cos_t = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos_t))


def validate(landmarks: dict[str, tuple[float, float, float]]) -> Optional[tuple[ErrorCode, str]]:
    """-> None if the pose is acceptable, else (ErrorCode.pose_rejected, actionable message)."""
    missing = [n for n in _BODY_REQUIRED if landmarks[n][2] < VISIBILITY_MIN]
    if missing:
        return ErrorCode.pose_rejected, STEP_BACK_MESSAGE

    for side in ("left", "right"):
        shoulder = landmarks[f"{side}_shoulder"][:2]
        hip = landmarks[f"{side}_hip"][:2]
        elbow = landmarks[f"{side}_elbow"][:2]
        if _angle_deg(hip, shoulder, elbow) < ARM_ANGLE_MIN_DEG:
            return ErrorCode.pose_rejected, ARMS_MESSAGE

    return None
