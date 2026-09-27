"""A-P3: pose landmarks checked against the outline tolerance. Evaluate every check and, on
rejection, report every failing one -- specific, actionable, and ordered by importance -- never a
single generic failure (previously this returned only the FIRST failing check, so a person got one
vague reason and had to guess at the rest). A-B8: landmarks missing -> reject, no lower rung.

Human decision 2026-09-27 (priority bug): "the scan usually rejects... more info on why would be
helpful." Real scans come from a laptop/phone browser camera, several feet away, imperfect
lighting -- every threshold below is reviewed against that and loosened to the minimum the
pipeline genuinely needs (a usable rig: shoulders/hips/knees/ankles located with usable
confidence, face visible, roughly front-facing, arms not pressed flat), with the reasoning kept
next to each one. Measured values are logged on every scan (not just rejections) so a rejection
can be debugged from server logs without reproducing it.
"""
import logging
import math
from typing import Optional

from contract.enums import ErrorCode

logger = logging.getLogger(__name__)

# --- thresholds ---------------------------------------------------------------------------------

# Was 0.5. MediaPipe visibility on a real webcam frame (laptop distance, mixed room lighting)
# regularly lands 0.3-0.6 on joints that are perfectly usable for the rig -- 0.5 rejected
# reasonable scans outright (human report 2026-09-27; the real-photo probe below measured
# 0.92-1.0 on well-lit photos, so 0.3 still leaves real margin before this fires).
VISIBILITY_MIN = 0.3

# Unchanged -- 2026-09-26 decision already tuned against real relaxed stances (15-23 degrees
# measured, see model.sadie.jpeg/model.lalitha.jpeg at 14.6-23.8 degrees) vs. arms pressed flat.
# Loosening further would stop catching the latter.
ARM_ANGLE_MIN_DEG = 12.0

# NEW checks below (previously there was no framing or facing check at all -- a too-close/too-far/
# turned scan surfaced only as a confusing missing-landmark or arm-angle rejection, if it was
# caught at all). Bounds are deliberately wide: reject only once the crop is genuinely unusable for
# a rig, not for imperfect distance-from-camera guessing (human report: "the place to stand is
# really small").

# Fraction of the frame height the body spans, head to ankles (see _frame_fraction). The two real
# model photos measured 0.77-0.79 here with plenty of headroom either side.
MAX_BODY_FRAME_FRACTION = 0.97  # near edge-to-edge -- the next small movement clips head or feet
MIN_BODY_FRAME_FRACTION = 0.20  # smaller than this and landmark pixel precision (hence the rig)
                                 # gets genuinely coarse

# Facing-the-camera proxy: MediaPipe Pose's z (depth) is not captured by landmarks.py (it only
# keeps x, y, visibility), so rotation is inferred from how far the nose sits off the shoulder
# midpoint, relative to shoulder width. A front-facing person's nose sits close to centered (the
# two real photos measured 0.02-0.03); a person turned toward profile shifts it well past half the
# shoulder width. Generous on purpose: flags a clear turn, not a tilted head or a slightly angled
# stance.
MAX_FACING_OFFSET_RATIO = 0.6

# 2026-09-27 scan-stress pass (backend/avatar/scripts/scan_stress.py; live judge scan at the demo).
# Feet slightly cut off by the bottom of the frame: MediaPipe still predicts the ankles past the
# edge, and accurately (model.sadie cropped 10% of body height above the ankle: predicted ankle y
# 1375/1381 vs. 1367/1378 true), but with low visibility (0.23-0.27), so the missing-ankles check
# rejected it. Now, when the knees are visible and the predicted ankles sit at/below the bottom
# edge (lower than FEET_EDGE_FRACTION of the frame height) and no more than FEET_CROP_MAX_FRACTION
# of the nose-to-ankle span past it, the ankles count as "cropped, estimated" -- the rig uses
# MediaPipe's prediction -- instead of missing. Ankles hidden INSIDE the frame still reject.
FEET_EDGE_FRACTION = 0.97
FEET_CROP_MAX_FRACTION = 0.18  # model.sadie cropped 15% of the span above the ankle predicts
                               # ~15.3% past the edge; mid-shin (25%) still rejects

# --- missing-landmark groups, ordered most-fundamental-first -------------------------------------
# Grouped (rather than one message per landmark) so a person gets one instruction per body region,
# not a wall of near-duplicate lines.

_MISSING_CHECKS: list[tuple[str, tuple[str, ...], str]] = [
    ("ankles", ("left_ankle", "right_ankle"),
     "Your ankles aren't visible — step back until your feet are in the frame."),
    ("knees", ("left_knee", "right_knee"),
     "Your knees aren't visible — step back so your legs are in the frame."),
    ("hips", ("left_hip", "right_hip"),
     "Your hips aren't visible — step back so your waist is in the frame."),
    ("shoulders", ("left_shoulder", "right_shoulder"),
     "Your shoulders aren't visible — face the camera with your upper body in the frame."),
    ("arms", ("left_elbow", "right_elbow", "left_wrist", "right_wrist"),
     "Your arms aren't visible — let them hang at your sides, a little away from your body."),
    ("face", ("nose",),
     "Your face isn't visible — face the camera and move into better light."),
]

_BODY_REQUIRED = [name for _label, names, _msg in _MISSING_CHECKS for name in names]

# Kept for backend/avatar/scripts/make_polish_preview.py, which bypasses only an arm-angle
# rejection for two known photos -- it matches on this prefix rather than an exact message, since
# the message itself now carries the measured angle.
ARMS_MESSAGE_PREFIX = "Your arms are too close to your body"


def _angle_deg(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """Angle at point b, between rays b->a and b->c, in degrees."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    cos_t = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos_t))


def _arm_message(angle_deg: float) -> str:
    return (
        f"{ARMS_MESSAGE_PREFIX} ({angle_deg:.0f}°, need {ARM_ANGLE_MIN_DEG:.0f}°) "
        "— lift them slightly away."
    )


def feet_cropped_by_frame(
    landmarks: dict[str, tuple[float, float, float]], frame_size: tuple[int, int],
) -> bool:
    """True when the feet are only slightly cut off by the bottom edge: knees visible, and the
    predicted ankles at/past the bottom edge but within FEET_CROP_MAX_FRACTION of the body span."""
    _frame_w, frame_h = frame_size
    if min(landmarks["left_knee"][2], landmarks["right_knee"][2]) < VISIBILITY_MIN:
        return False
    ankle_y = max(landmarks["left_ankle"][1], landmarks["right_ankle"][1])
    span = ankle_y - landmarks["nose"][1]
    if span <= 0:
        return False
    return FEET_EDGE_FRACTION * frame_h <= ankle_y <= frame_h + FEET_CROP_MAX_FRACTION * span


def _feet_cropped_too_much(
    landmarks: dict[str, tuple[float, float, float]], frame_size: tuple[int, int],
) -> bool:
    """True when the predicted ankles lie further past the bottom edge than FEET_CROP_MAX_FRACTION
    allows -- rejected as missing ankles even at a visibility MediaPipe still rates usable (the
    framing check clamps ankles to the frame, so it no longer catches this on its own)."""
    _frame_w, frame_h = frame_size
    ankle_y = max(landmarks["left_ankle"][1], landmarks["right_ankle"][1])
    span = ankle_y - landmarks["nose"][1]
    return span > 0 and ankle_y > frame_h + FEET_CROP_MAX_FRACTION * span


def validate(
    landmarks: dict[str, tuple[float, float, float]],
    frame_size: tuple[int, int],
) -> Optional[tuple[ErrorCode, str]]:
    """-> None if the pose is acceptable, else (ErrorCode.pose_rejected, message).

    Every check is evaluated (not just the first failure); `message` joins every failing one with
    "\\n", most important first, so the frontend can render each line as its own bullet.
    frame_size: (width, height) in pixels of the photo the landmarks were detected on -- needed
    for the framing checks.
    """
    frame_w, frame_h = frame_size
    reasons: list[str] = []
    missing_groups: set[str] = set()
    measurements: dict[str, object] = {}

    feet_cropped = feet_cropped_by_frame(landmarks, frame_size)
    measurements["feet_cropped"] = feet_cropped
    for label, names, message in _MISSING_CHECKS:
        worst_visibility = min(landmarks[n][2] for n in names)
        measurements[f"{label}_visibility"] = round(worst_visibility, 3)
        missing = worst_visibility < VISIBILITY_MIN and not (label == "ankles" and feet_cropped)
        if label == "ankles" and _feet_cropped_too_much(landmarks, frame_size):
            missing = True
        if missing:
            reasons.append(message)
            missing_groups.add(label)

    # Scan-stress pass: "upper body only" produced separate ankles + knees + hips lines that all
    # say "step back". When the ankles are missing, the ankles line already says it -- drop the
    # redundant knees/hips lines (the groups stay marked missing for the checks below).
    if "ankles" in missing_groups:
        redundant = {msg for label, _n, msg in _MISSING_CHECKS if label in {"knees", "hips"}}
        reasons = [r for r in reasons if r not in redundant]

    # Framing (too close / too far): only meaningful once the face and ankles are actually
    # located, otherwise the span below is measuring noise, not the body.
    if not ({"face", "ankles"} & missing_groups):
        nose_y = landmarks["nose"][1]
        # Clamped to the frame: feet slightly cut off (see FEET_CROP_MAX_FRACTION) are allowed, so
        # past the bottom edge this measures only the head room -- "too close" then means the
        # head is about to leave the top of the frame.
        ankle_y = min(max(landmarks["left_ankle"][1], landmarks["right_ankle"][1]), float(frame_h))
        # No head-top landmark exists; approximate the gap from the nose to the top of the head as
        # a fraction of the nose-to-ankle span -- rough human proportions, good enough for a
        # framing threshold, not a precise body-height measurement.
        body_top = nose_y - (ankle_y - nose_y) * 0.12
        body_height = max(1.0, ankle_y - body_top)
        frame_fraction = body_height / frame_h
        measurements["body_frame_fraction"] = round(frame_fraction, 3)
        if frame_fraction > MAX_BODY_FRAME_FRACTION:
            reasons.append(
                "You're too close to the camera — your body fills "
                f"{frame_fraction * 100:.0f}% of the frame height."
            )
        elif frame_fraction < MIN_BODY_FRAME_FRACTION:
            reasons.append(
                "You're too far from the camera — your body only fills "
                f"{frame_fraction * 100:.0f}% of the frame height."
            )

    # Facing the camera: only meaningful once the face and shoulders are actually located.
    if not ({"face", "shoulders"} & missing_groups):
        left_x, right_x = landmarks["left_shoulder"][0], landmarks["right_shoulder"][0]
        shoulder_mid_x = (left_x + right_x) / 2.0
        shoulder_width = abs(left_x - right_x)
        if shoulder_width > 1e-6:
            offset_ratio = abs(landmarks["nose"][0] - shoulder_mid_x) / shoulder_width
            measurements["facing_offset_ratio"] = round(offset_ratio, 3)
            if offset_ratio > MAX_FACING_OFFSET_RATIO:
                reasons.append("Turn to face the camera — your shoulders look rotated.")

    # Arms away from the body: only meaningful once shoulders, hips, and arms are all located.
    if not ({"shoulders", "hips", "arms"} & missing_groups):
        worst_side, worst_angle = None, None
        for side in ("left", "right"):
            shoulder = landmarks[f"{side}_shoulder"][:2]
            hip = landmarks[f"{side}_hip"][:2]
            elbow = landmarks[f"{side}_elbow"][:2]
            angle = _angle_deg(hip, shoulder, elbow)
            measurements[f"{side}_arm_angle_deg"] = round(angle, 1)
            if worst_angle is None or angle < worst_angle:
                worst_angle, worst_side = angle, side
        if worst_angle is not None and worst_angle < ARM_ANGLE_MIN_DEG:
            reasons.append(_arm_message(worst_angle))

    logger.info(
        "avatar scan pose check: frame=%dx%d measurements=%s %s",
        frame_w, frame_h, measurements,
        "accepted" if not reasons else f"rejected ({len(reasons)} check(s) failed): {reasons}",
    )

    if reasons:
        return ErrorCode.pose_rejected, "\n".join(reasons)
    return None
