"""A3 change (human decision 2026-09-26; FRONTEND_REQUESTS #7, OPEN_QUESTIONS #3; A-B3 superseded
in contract/DECISIONS.md): the visible avatar is the user's real body, cut out of the scan photo
head to feet, on a transparent 1:2 (width:height) canvas -- never the drawn mannequin.

Bug fix (2026-09-27): live webcam scans are landscape (e.g. 1080x608) with the person standing far
back -- a thin strip of the frame. Running the segmenter on the WHOLE frame made the person too
small a fraction of it (< MIN_PERSON_FRACTION), so every live scan fell back. Fixed by segmenting
only the person's own pose bounding box (`pose_bbox`, built from the pose landmarks already
detected for the rig -- head top above the nose, feet below the ankles, padded) instead of the
full frame: the same person is now a large fraction of the region actually analyzed, regardless of
how small they are in the source photo. `MIN_PERSON_FRACTION` is checked against that crop, not
the frame.

The person mask comes from MediaPipe ImageSegmenter's multiclass model (mp_models.image_segmenter
-- the same model A-B5 already uses for skin detection): every non-background category (hair,
body-skin, face-skin, clothes, others). Cleaned with the largest connected component (drops
stray specks the model sometimes classifies elsewhere in the frame), a small bounded morphological
close (fills small holes in the mask -- never the real background between the legs or under an
arm, which stays transparent), and a 1-2px feathered edge (soft alpha, not a hard cutout line).

Fallback (A-B8 spirit, tightened 2026-09-27 -- "no mannequin at all"): if the segmenter itself
fails, or the cleaned mask is implausibly small within the pose bbox, `build_person_cutout`
returns None and the caller (service.build_avatar_visuals) uses `photo_crop_fallback` instead: a
plain crop of the person from the source photo (the same pose bbox), with a soft vignette fading
to transparency at its edges -- a real photo either way, never line art. The drawn wireframe
remains available separately as the render loading state (`wireframe_url`).
"""
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from .mp_models import image_segmenter
from .rig import Rig

# Within the pose-bbox crop (not the whole frame -- see module docstring), below this fraction the
# mask is treated as a failed/implausible segmentation rather than a real person.
MIN_PERSON_FRACTION = 0.05

# Crop padding beyond the mask's own bounding box, as a fraction of that box's width/height --
# mirrors the P0.7 artifact spec's 2% cutout padding; small margin only, no extra art direction.
BBOX_PAD_FRACTION = 0.03

# Bounded hole closing: fills small gaps (a stray unclassified pixel inside the silhouette)
# without ever bridging real background regions (between the legs, under a raised arm), which
# are much larger than this kernel.
HOLE_CLOSE_FRACTION = 0.01

# Target width:height for the avatar canvas (1:2), so the frontend can fit the avatar by height
# without cropping it.
CANVAS_RATIO = 0.5

# The pose landmarks span shoulders/hips/wrists/ankles, not the literal top of the head or the
# tip of the feet -- padded generously (wider than the mask-bbox pad above, since landmarks alone
# undershoot the body's true extent, especially width when arms hang close to the torso).
POSE_BBOX_PAD_W_FRACTION = 0.10
POSE_BBOX_PAD_H_FRACTION = 0.06
FOOT_ALLOWANCE_FRACTION = 0.18  # beyond the ankle landmark, room for the foot/shoe (of shoulder width)

# The segmenter's own model input is 256x256; a pose-bbox crop smaller than this is upscaled
# before segmenting (then the mask is downscaled back), so a distant subject in a landscape frame
# isn't handed to the model at a handful of native pixels.
SEGMENTER_TARGET_DIM = 256


def pose_bbox(
    rig: Rig,
    landmarks_px: dict[str, tuple[float, float, float]],
    frame_size: tuple[int, int],
    pad_w_fraction: float = POSE_BBOX_PAD_W_FRACTION,
    pad_h_fraction: float = POSE_BBOX_PAD_H_FRACTION,
) -> tuple[int, int, int, int]:
    """-> (x0, y0, x1, y1): the person's own head-to-feet region in `landmarks_px`'s pixel
    coordinates, padded and clamped to `frame_size`. This is the region segmentation and the
    photo-crop fallback both operate on -- never the whole frame."""
    pts = {n: (x, y) for n, (x, y, _v) in landmarks_px.items()}
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]

    head_top = rig.head_center[1] - rig.head_radius * 1.3  # matches rig.canvas_bbox's own allowance
    y_top = min(min(ys), head_top)

    foot_bottom = max(ys)
    left_ankle, right_ankle = pts.get("left_ankle"), pts.get("right_ankle")
    for ankle in (left_ankle, right_ankle):
        if ankle is not None:
            foot_bottom = max(foot_bottom, ankle[1])
    foot_bottom += rig.shoulder_width * FOOT_ALLOWANCE_FRACTION

    x0, x1 = min(xs), max(xs)
    y0, y1 = y_top, foot_bottom

    pad_x, pad_y = (x1 - x0) * pad_w_fraction, (y1 - y0) * pad_h_fraction
    fw, fh = frame_size
    x0, y0 = max(0, round(x0 - pad_x)), max(0, round(y0 - pad_y))
    x1, y1 = min(fw, round(x1 + pad_x)), min(fh, round(y1 + pad_y))
    return (x0, y0, max(x1, x0 + 1), max(y1, y0 + 1))  # never degenerate


def _segment_person_mask(rgb: np.ndarray) -> Optional[np.ndarray]:
    """-> bool (h, w) mask of every non-background category, or None if segmentation itself
    fails (model load/download failure, or the task raising on this input)."""
    cats = _segment_categories(rgb)
    return None if cats is None else cats != 0  # 0 == background (mp_models' category list)


def _segment_categories(rgb: np.ndarray) -> Optional[np.ndarray]:
    """-> uint8 (h, w) multiclass category mask, or None if segmentation itself fails."""
    import mediapipe as mp

    try:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = image_segmenter().segment(mp_image)
        category_mask = result.category_mask.numpy_view()
    except Exception:
        return None

    # The real model returns (h, w, 1); a test double may return the bare (h, w) already.
    if category_mask.ndim == 3:
        category_mask = category_mask[..., 0]
    return np.asarray(category_mask).astype(np.uint8)


def _segment_mask_in_crop(crop_rgb: np.ndarray) -> Optional[np.ndarray]:
    """-> bool person mask for the crop (see `_segment_categories_in_crop`)."""
    cats = _segment_categories_in_crop(crop_rgb)
    return None if cats is None else cats != 0


def _segment_categories_in_crop(crop_rgb: np.ndarray) -> Optional[np.ndarray]:
    """`_segment_categories`, but upscaling a small crop first (see SEGMENTER_TARGET_DIM) and
    mapping the resulting category mask back to the crop's own original size."""
    ch, cw = crop_rgb.shape[:2]
    scale = SEGMENTER_TARGET_DIM / max(ch, cw) if max(ch, cw) < SEGMENTER_TARGET_DIM else 1.0

    source = crop_rgb
    if scale > 1.0:
        source = cv2.resize(
            crop_rgb, (round(cw * scale), round(ch * scale)), interpolation=cv2.INTER_LANCZOS4,
        )

    cats = _segment_categories(source)
    if cats is None:
        return None
    if scale > 1.0:
        cats = cv2.resize(cats, (cw, ch), interpolation=cv2.INTER_NEAREST)
    return cats


# Hair-patch fix (2026-09-27, human-flagged): every real-body cutout kept a jagged patch of
# background at the top/side of the head. Real cause (avatar_e6b852/_56501c source photos): the
# scans stand in front of framed photos of OTHER people, and the multiclass segmenter labels those
# people's heads/arms as "hair" connected to the user's own hair, so the largest-component step
# keeps them. Fix, head zone only (rows above the shoulder line): (1) GrabCut seeded from the
# segmenter -- face/body skin and clothes are sure-foreground, the rest of the mask is
# probable-foreground, everything outside is background -- which drops the off-color side
# patches; (2) above the face-skin hairline only, a morphological open with a disc of half the face
# width, which removes narrow protrusions sticking up off the head without rounding a real head
# top (much wider than that disc). Only ever REMOVES mask pixels, never adds; a no-op when the
# segmenter found no face skin.
HEAD_OPEN_FACE_FRACTION = 0.5
GRABCUT_ITERATIONS = 5
GRABCUT_BAND_PX = 31  # probable-background band around the mask for GrabCut to learn from


def _trim_head_background(
    mask: np.ndarray, crop_rgb: np.ndarray, cats: np.ndarray, shoulder_y: Optional[float],
) -> np.ndarray:
    face_ys, face_xs = np.where(cats == 3)
    if shoulder_y is None or face_ys.size == 0:
        return mask
    h_zone = int(min(max(shoulder_y, 0), mask.shape[0]))
    if h_zone < 8:
        return mask
    try:
        m0 = mask[:h_zone]
        gc = np.full(m0.shape, cv2.GC_BGD, np.uint8)
        band = cv2.dilate(m0.astype(np.uint8), np.ones((GRABCUT_BAND_PX, GRABCUT_BAND_PX), np.uint8)) > 0
        gc[band] = cv2.GC_PR_BGD
        gc[m0] = cv2.GC_PR_FGD
        core = cv2.erode(np.isin(cats[:h_zone], [2, 3, 4]).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        gc[core & m0] = cv2.GC_FGD
        bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
        zone_bgr = cv2.cvtColor(np.ascontiguousarray(crop_rgb[:h_zone]), cv2.COLOR_RGB2BGR)
        cv2.grabCut(zone_bgr, gc, None, bgd, fgd, GRABCUT_ITERATIONS, cv2.GC_INIT_WITH_MASK)
        trimmed = mask.copy()
        trimmed[:h_zone] = ((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)) & m0
    except cv2.error:
        trimmed = mask.copy()  # GrabCut can refuse degenerate seeds; skip that step, keep going
    trimmed = _largest_component(trimmed)

    hairline = int(face_ys.min())
    kd = max(3, int((face_xs.max() - face_xs.min()) * HEAD_OPEN_FACE_FRACTION)) | 1
    if hairline > 0:
        region = trimmed[:hairline + kd].astype(np.uint8)
        opened = cv2.morphologyEx(region, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kd, kd))) > 0
        trimmed[:hairline] &= opened[:hairline]
        trimmed = _largest_component(trimmed)
    return trimmed & mask


def _largest_component(mask: np.ndarray) -> np.ndarray:
    mask_u8 = mask.astype(np.uint8) * 255
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if num_labels <= 1:  # nothing but background
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_label = 1 + int(np.argmax(areas))
    return labels == largest_label


def _close_small_holes(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    k = max(3, round(min(h, w) * HOLE_CLOSE_FRACTION))
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask_u8 = mask.astype(np.uint8) * 255
    closed = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)
    return closed > 0


def _feather(mask: np.ndarray) -> np.ndarray:
    """-> uint8 alpha (0-255) with a ~1-2px soft edge instead of mask's hard boundary."""
    alpha = mask.astype(np.float32) * 255.0
    blurred = cv2.GaussianBlur(alpha, (5, 5), sigmaX=0.9)
    return np.clip(blurred, 0, 255).astype(np.uint8)


def _mask_bbox(
    mask: np.ndarray, pad_fraction: float, frame_size: tuple[int, int],
) -> Optional[tuple[int, int, int, int]]:
    ys, xs = np.where(mask)
    if xs.size == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    w, h = frame_size
    pad_x = round((x1 - x0) * pad_fraction)
    pad_y = round((y1 - y0) * pad_fraction)
    return (max(0, x0 - pad_x), max(0, y0 - pad_y), min(w, x1 + pad_x), min(h, y1 + pad_y))


# Feet-blob fix (2026-09-27, human-flagged): the real-body cutout kept a dark floor-shadow blob
# fused into the silhouette right under the feet. Inspecting real failing crops (avatar_858d48,
# avatar_29f549): the shadow is a low-saturation, dark, roughly RECTANGULAR patch bridging the gap
# BETWEEN the two feet -- it does not make the row wider (the overall left-to-right mask span at
# the ankle is already the two-feet width; the shadow just fills the transparent gap in between),
# so a "wider than the shoe" test alone misses it. What distinguishes it: on any row from the ankle
# down, a dark/desaturated run of mask pixels that has ORDINARY (lighter/more saturated) mask
# pixels on BOTH sides -- i.e. an interior bridge connecting two separate regions -- is never part
# of a real shoe, which only touches the row's own left/right edges of the person's mask.
FEET_SHADOW_SAT_MAX = 40    # 0-255 (HSV S) -- a shadow reads as close to gray
FEET_SHADOW_VAL_MAX = 90    # 0-255 (HSV V) -- and dark; real shoes usually have some highlight
MIN_BRIDGE_WIDTH = 5        # px; a fuzzy/textured shoe's dark speckle is thinner than this
# Scan-stress pass: a bridge's CENTER must sit in the middle part of the gap between the ankles
# (a dark trouser hem is centered on its own ankle, the floor shadow on the gap between them).
BRIDGE_CENTER_MARGIN = 0.25


def _trim_feet_shadow(
    mask: np.ndarray, crop_rgb: np.ndarray, ankle_y: Optional[float],
    ankle_xs: Optional[tuple[float, float]] = None,
) -> np.ndarray:
    """-> `mask` with any floor-shadow bridging the feet trimmed out. `ankle_y`: the average ankle
    landmark y, in `crop_rgb`'s own pixel coordinates (already offset by the crop's bbox origin)
    -- None (ankles undetected) leaves the mask untouched. Never touches anything above the ankle
    line, so a real shoe or leg is never cut -- only an interior dark bridge below it.

    `ankle_xs` (local x of both ankles; scan-stress pass 2026-09-27): a bridge must be centered
    between the two ankles (BRIDGE_CENTER_MARGIN). Without this, on a person ~40-60% of a landscape webcam frame, a dark
    trouser hem just below the ankle landmark (flanked by lighter anti-aliased edge pixels) read as
    a "bridge" and was cut out as a full-width stripe above the shoes."""
    if ankle_y is None:
        return mask
    h, w = mask.shape
    zone_top = max(0, int(ankle_y))
    if zone_top >= h:
        return mask

    hsv = np.array(Image.fromarray(crop_rgb).convert("HSV"))
    low_sat_dark = (hsv[:, :, 1] < FEET_SHADOW_SAT_MAX) & (hsv[:, :, 2] < FEET_SHADOW_VAL_MAX)

    trimmed = mask.copy()
    for row in range(zone_top, h):
        row_mask = trimmed[row, :]
        xs = np.where(row_mask)[0]
        if xs.size == 0:
            continue
        row_min, row_max = xs[0], xs[-1]

        dark_idx = np.where(row_mask & low_sat_dark[row, :])[0]
        if dark_idx.size == 0:
            continue
        # Contiguous runs of dark/desaturated mask pixels on this row. A real shadow bridge is a
        # solid patch (several px wide); a fuzzy/textured shoe's dark speckles between highlights
        # are thin -- MIN_BRIDGE_WIDTH keeps those from being misread as a bridge and punching a
        # hole through the shoe itself.
        splits = np.where(np.diff(dark_idx) > 1)[0] + 1
        for run in np.split(dark_idx, splits):
            g0, g1 = run[0], run[-1]
            between_feet = True
            if ankle_xs is not None:
                ax0, ax1 = min(ankle_xs), max(ankle_xs)
                margin = (ax1 - ax0) * BRIDGE_CENTER_MARGIN
                between_feet = ax0 + margin < (g0 + g1) / 2 < ax1 - margin
            if g0 > row_min and g1 < row_max and (g1 - g0 + 1) >= MIN_BRIDGE_WIDTH and between_feet:
                trimmed[row, g0:g1 + 1] = False
    return trimmed


def build_person_cutout(
    rgb: np.ndarray, bbox: tuple[int, int, int, int], ankle_y: Optional[float] = None,
    shoulder_y: Optional[float] = None, ankle_xs: Optional[tuple[float, float]] = None,
) -> Optional[tuple[Image.Image, tuple[int, int, int, int]]]:
    """Segments only within `bbox` (see `pose_bbox`) -- not the whole frame. `ankle_y`: the
    average ankle landmark y in `rgb`'s own full-frame pixel coordinates, used only to trim a
    floor-shadow/mat from under the feet (see `_trim_feet_shadow`); omit to skip that step.
    -> (rgba_crop, full_frame_bbox) where full_frame_bbox = (x0, y0, x1, y1) is the crop's
    location back in `rgb`'s own pixel coordinates, or None when the mask fails or is implausible
    (the caller then uses `photo_crop_fallback` -- never the drawn mannequin).
    """
    bx0, by0, bx1, by1 = bbox
    crop = rgb[by0:by1, bx0:bx1]

    cats = _segment_categories_in_crop(crop)
    if cats is None:
        return None
    mask = cats != 0
    if mask.sum() < MIN_PERSON_FRACTION * mask.size:
        return None

    cleaned = _largest_component(mask)
    cleaned = _close_small_holes(cleaned)
    shoulder_y_local = (shoulder_y - by0) if shoulder_y is not None else None
    cleaned = _trim_head_background(cleaned, crop, cats, shoulder_y_local)
    if cleaned.sum() < MIN_PERSON_FRACTION * cleaned.size:
        return None

    ankle_y_local = (ankle_y - by0) if ankle_y is not None else None
    ankle_xs_local = (ankle_xs[0] - bx0, ankle_xs[1] - bx0) if ankle_xs is not None else None
    cleaned = _trim_feet_shadow(cleaned, crop, ankle_y_local, ankle_xs_local)

    tight = _mask_bbox(cleaned, BBOX_PAD_FRACTION, (crop.shape[1], crop.shape[0]))
    if tight is None:
        return None
    tx0, ty0, tx1, ty1 = tight

    alpha = _feather(cleaned)
    rgba = np.dstack([crop[ty0:ty1, tx0:tx1], alpha[ty0:ty1, tx0:tx1]])
    full_bbox = (bx0 + tx0, by0 + ty0, bx0 + tx1, by0 + ty1)
    return Image.fromarray(rgba, mode="RGBA"), full_bbox


def _vignette_alpha(size: tuple[int, int], inset_fraction: float = 0.04, blur_fraction: float = 0.06) -> np.ndarray:
    """-> uint8 alpha (0-255): opaque in the interior, softly fading to transparent near the
    crop's own edges -- used only for the no-mannequin photo-crop fallback, never a hard
    rectangle."""
    w, h = size
    alpha = np.zeros((h, w), dtype=np.uint8)
    inset_x, inset_y = round(w * inset_fraction), round(h * inset_fraction)
    alpha[inset_y:max(inset_y + 1, h - inset_y), inset_x:max(inset_x + 1, w - inset_x)] = 255
    k = max(3, round(min(w, h) * blur_fraction))
    if k % 2 == 0:
        k += 1
    return cv2.GaussianBlur(alpha, (k, k), 0)


def photo_crop_fallback(rgb: np.ndarray, bbox: tuple[int, int, int, int]) -> Image.Image:
    """Never fails, never line art: a plain crop of the person from the source photo (`bbox` --
    see `pose_bbox`), vignetted to transparency at its edges instead of a hard cutout."""
    x0, y0, x1, y1 = bbox
    crop = rgb[y0:y1, x0:x1]
    alpha = _vignette_alpha((crop.shape[1], crop.shape[0]))
    rgba = np.dstack([crop, alpha])
    return Image.fromarray(rgba, mode="RGBA")


def pad_to_ratio(crop_img: Image.Image, ratio: float = CANVAS_RATIO) -> tuple[Image.Image, tuple[int, int]]:
    """-> (canvas_img, (offset_x, offset_y)): `crop_img` centered on a transparent canvas grown
    (never cropped) in whichever dimension is needed to reach width:height == ratio."""
    cw, ch = crop_img.size
    if cw / ch <= ratio:
        canvas_w, canvas_h = max(cw, round(ch * ratio)), ch
    else:
        canvas_w, canvas_h = cw, max(ch, round(cw / ratio))
    offset = (round((canvas_w - cw) / 2), round((canvas_h - ch) / 2))
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    canvas.alpha_composite(crop_img.convert("RGBA"), offset)
    return canvas, offset


# The segmenter runs at 256x256, so on a ~1200px render its edge is blocky and off by up to ~10px
# (white slivers kept past the silhouette, hair tips cut). Only within a narrow band around that
# edge, the silhouette is snapped to the render's own plain-white background: near-white pixels in
# the band that CONNECT to the outside are background, anything else in the band is person. The
# eroded interior is never touched, so a white garment inside the body always survives; a white
# garment touching the silhouette can lose at most the band width.
GEN_EDGE_BAND_FRACTION = 1 / 128   # of the long side (~10px on a 1216px render)
GEN_WHITE_MIN = 243                # every channel >= this reads as the plain white background


def _snap_edge_to_white_background(mask: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    k = max(3, round(max(h, w) * GEN_EDGE_BAND_FRACTION)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    m8 = mask.astype(np.uint8)
    core = cv2.erode(m8, kernel) > 0
    outer = cv2.dilate(m8, kernel) > 0
    near_white = rgb.min(axis=2) >= GEN_WHITE_MIN
    # Background candidates: everything outside the band, plus near-white pixels in it.
    bg_cand = (~outer | (near_white & ~core)).astype(np.uint8)
    _n, labels = cv2.connectedComponents(bg_cand, connectivity=4)
    outside_labels = np.unique(labels[~outer & (bg_cand > 0)])
    background = np.isin(labels, outside_labels[outside_labels != 0])
    snapped = _largest_component(outer & ~background)
    # The render's own anti-aliased rim (light, just under GEN_WHITE_MIN) shows as a pale outline on
    # dark UI; pull the edge in by 1px so the feather starts on the person, not on that rim.
    return cv2.erode(snapped.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0


# Transparent try-on (human request 2026-09-27): the Gemini try-on render (prompt v5) comes back on
# plain white; it is saved with that background made transparent. Person SEGMENTATION, never a
# white-color threshold -- white/cream garments must survive. Full frame, full canvas size (no
# crop), so framing stays identical to the white-background render. No pose bbox / head / feet
# trims: a generated image has no background people and no floor shadow to remove.
def cut_out_generated(rgb: np.ndarray) -> Optional[Image.Image]:
    """-> RGBA image, same size as `rgb`, with the background transparent and a ~1-2px feathered
    edge; or None if segmentation fails or the mask is implausibly small (caller keeps the
    white-background image -- a documented degraded state, the image is still correct)."""
    cats = _segment_categories(np.ascontiguousarray(rgb[..., :3]))
    if cats is None:
        return None
    mask = cats != 0
    if mask.shape != rgb.shape[:2] or mask.sum() < MIN_PERSON_FRACTION * mask.size:
        return None
    mask = _close_small_holes(_largest_component(mask))
    mask = _snap_edge_to_white_background(mask, rgb[..., :3])
    if mask.sum() < MIN_PERSON_FRACTION * mask.size:
        return None

    alpha = _feather(mask)
    # No color un-blending of the soft edge: tried, it amplified the render's own edge noise into
    # dark specks; the 1px pull-in above already keeps the white rim out.
    return Image.fromarray(np.dstack([np.ascontiguousarray(rgb[..., :3]).astype(np.uint8), alpha]), mode="RGBA")
