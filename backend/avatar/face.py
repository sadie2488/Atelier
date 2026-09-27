"""A-B6: the real face is composited at the head. Cropped via MediaPipe face detection,
background removed, scaled to the wireframe's neck anchor (done by draw.draw_avatar).
"""
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .mp_models import face_detector


def detect_face_box(rgb: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    """-> (x0, y0, x1, y1) pixel box of the largest detected face, or None.

    Full-frame detection. On a standing, full-body scan photo the face is a small fraction of
    the frame -- often too small for blaze_face_short_range (a short-range, face-filling
    detector) to find at all. `detect_face_box_near` below is the production path for a
    full-body frame; call this directly only when the image is already face-scale (a crop, or a
    portrait photo).
    """
    import mediapipe as mp

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = face_detector().detect(mp_image)
    if not result.detections:
        return None
    best = max(result.detections, key=lambda d: d.bounding_box.width * d.bounding_box.height)
    bb = best.bounding_box
    return (bb.origin_x, bb.origin_y, bb.origin_x + bb.width, bb.origin_y + bb.height)


def detect_face_box_near(
    rgb: np.ndarray,
    head_center: tuple[float, float],
    head_radius: float,
    pad_factor: float = 3.0,
) -> Optional[tuple[int, int, int, int]]:
    """A-B6/A9: the production face-detection path for a full-body scan photo. Crops a generous,
    face-filling region around the rig's own head estimate (from pose landmarks -- nose plus
    shoulder geometry, see rig.py), runs `detect_face_box` on that crop, and maps the resulting
    box back to full-frame pixel coordinates.

    Returns None if the crop is degenerate or the detector still finds nothing in it -- the
    caller (service.scan) then falls back to the landmark-derived head geometry alone (the
    drawn head circle, no composited photo); there is no further face-detection rung below this
    one (A-B8).
    """
    h, w = rgb.shape[:2]
    hx, hy = head_center
    pad = head_radius * pad_factor
    cx0, cy0 = max(0, int(hx - pad)), max(0, int(hy - pad))
    cx1, cy1 = min(w, int(hx + pad)), min(h, int(hy + pad))
    if cx1 <= cx0 or cy1 <= cy0:
        return None

    crop = rgb[cy0:cy1, cx0:cx1]
    box = detect_face_box(crop)
    if box is None:
        return None
    bx0, by0, bx1, by1 = box
    return (cx0 + bx0, cy0 + by0, cx0 + bx1, cy0 + by1)


def detect_face_keypoints(rgb: np.ndarray) -> Optional[dict[str, tuple[float, float]]]:
    """-> {"right_eye": (x,y), "left_eye": (x,y)} in `rgb`'s own pixel coords for the largest
    detected face, or None. Full-frame detection only -- see detect_face_box's docstring; use
    `detect_face_keypoints_near` for a full-body frame. ISSUES #22: verify.py's identity check
    uses the eye positions for a simple face-proportion match against the source photo.
    """
    import mediapipe as mp

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = face_detector().detect(mp_image)
    if not result.detections:
        return None
    best = max(result.detections, key=lambda d: d.bounding_box.width * d.bounding_box.height)
    try:
        # BlazeFace short-range keypoint order: right_eye, left_eye, nose_tip, mouth_center,
        # right_ear_tragion, left_ear_tragion (person's own left/right).
        kps = best.keypoints
        h, w = rgb.shape[:2]
        return {"right_eye": (kps[0].x * w, kps[0].y * h), "left_eye": (kps[1].x * w, kps[1].y * h)}
    except (IndexError, AttributeError, TypeError):
        return None


def detect_face_keypoints_near(
    rgb: np.ndarray, head_center: tuple[float, float], head_radius: float, pad_factor: float = 3.0,
) -> Optional[dict[str, tuple[float, float]]]:
    """`detect_face_keypoints`, cropped around a head estimate first -- see detect_face_box_near."""
    h, w = rgb.shape[:2]
    hx, hy = head_center
    pad = head_radius * pad_factor
    cx0, cy0 = max(0, int(hx - pad)), max(0, int(hy - pad))
    cx1, cy1 = min(w, int(hx + pad)), min(h, int(hy + pad))
    if cx1 <= cx0 or cy1 <= cy0:
        return None
    kps = detect_face_keypoints(rgb[cy0:cy1, cx0:cx1])
    if kps is None:
        return None
    return {name: (cx0 + x, cy0 + y) for name, (x, y) in kps.items()}


def crop_face(rgb: np.ndarray, box: tuple[int, int, int, int], pad_fraction: float = 0.35) -> Image.Image:
    """Crop the face with padding and remove the background with a soft elliptical alpha mask.

    Not full segmentation -- that model is not a dependency of this lane. A soft ellipse is
    enough for a small circular head cutout to read as intentional rather than a clipped
    rectangle (A-B6, "background removed").
    """
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    px, py = bw * pad_fraction, bh * pad_fraction
    cx0, cy0 = max(0, int(x0 - px)), max(0, int(y0 - py))
    cx1, cy1 = min(w, int(x1 + px)), min(h, int(y1 + py))
    crop = Image.fromarray(rgb[cy0:cy1, cx0:cx1]).convert("RGBA")

    mask = Image.new("L", crop.size, 0)
    draw = ImageDraw.Draw(mask)
    inset_x, inset_y = crop.width * 0.06, crop.height * 0.02
    draw.ellipse([inset_x, inset_y, crop.width - inset_x, crop.height - inset_y], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, crop.width // 40)))
    crop.putalpha(mask)
    return crop
