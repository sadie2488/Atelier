"""A-R10: verify generated output before swapping it in. Sample one representative patch per
garment and compare it against the item's stored color (primary or secondary, V-C6) in CIE Lab
via CIEDE2000. Any garment over VERIFY_MAX_DELTA_E fails verification -- the render stays
`failed` and the local composite is what the user sees either way (A-R6).

This is deliberately coarse: one patch per garment, not per-pixel garment segmentation (there is
no segmenter in this lane's dependencies -- see mp_models.py). It exists to catch the most common
failure, Gemini swapping in the wrong color, not to grade texture or print fidelity, which A-R7
already accepts as this method's weakness. Face-landmark drift is not checked here (optional per
A-R10); the identity-preservation instruction lives in prompt.py.

Re-dispatch fix (real renders, 2026-09-26): all 6 real try-ons verified with the wrong-region
samples --

1. Gemini re-frames/re-poses the person, so the SOURCE photo's landmarks scaled to the output
   size land on background or on another garment. We now run pose detection on the GENERATED
   image itself and sample there, falling back to scaled source landmarks only when detection
   on the generated image finds nobody.
2. A dress covers the bottom (A-R5) and a jacket covers the top -- verifying those regions was
   comparing the wrong garment's sample against the covered garment's stored color. Skipped now.
3. A small mean patch is noisy on patterned garments (a seam or highlight can dominate 28px). The
   patch is wider and uses a per-pixel Lab median instead of a mean-then-convert.
4. A hit now counts against the item's primary OR secondary color (DECISIONS V-C6: the human
   counts either on two-tone garments), and a failing render dumps the generated image to
   media/_preview/ for a human to look at, plus a log line of sampled vs. stored Lab per garment.
"""
import logging
import math
from typing import Optional

import numpy as np
from PIL import Image

from contract.enums import GarmentType, SECONDARY_MIN_DELTA_E
from contract.tools.color import delta_e2000

from . import face, landmarks, media

logger = logging.getLogger(__name__)

# A-R10: how far the sampled generated-garment color may drift from the item's stored Lab color
# before the swap is rejected. Reused from the contract's own "clearly a different color"
# threshold (SECONDARY_MIN_DELTA_E) rather than inventing a new number: a lit, generated photo
# will drift more than a flat cutout scan, but past this point it reads as the wrong garment,
# not just different lighting. Kept at 20.0 after the 2026-09-26 real-render pass -- once sampling
# lands on the right garment (fix 1 above) the observed in-garment ΔE2000 was well under this on
# the two renders that passed; no evidence yet to move it.
VERIFY_MAX_DELTA_E = SECONDARY_MIN_DELTA_E  # 20.0

# Half-size of the sample square, px, in the sampling image's own resolution. Widened from the
# original 14: a patterned or textured garment can put a seam, highlight, or wrinkle shadow right
# under a 28px box, and averaging (the old behavior) lets one such pixel run skew the whole
# sample. 32 (64px box) plus a per-pixel median (not a mean) resists that without wandering off
# the garment onto skin or background for the torso/leg/arm regions this samples.
_PATCH = 32

# D65 reference white, matching contract.tools.color.hex_to_lab. Duplicated (not imported) so
# this can run vectorized over a whole patch instead of one hex string at a time -- keep in sync
# if the contract's white point ever changes.
_WHITE = (95.047, 100.0, 108.883)


def _rgb_array_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Vectorized version of contract.tools.color.hex_to_lab. `rgb`: (..., 3) array, 0..255 ->
    Lab (..., 3) float array, same formula, same D65 white point."""
    arr = rgb.astype(float) / 255.0
    lin = np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) * 100
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) * 100
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) * 100
    xn, yn, zn = _WHITE
    d = (6 / 29) ** 3

    def f(t):
        return np.where(t > d, np.cbrt(t), t / (3 * (6 / 29) ** 2) + 4 / 29)

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)


def _patch_lab_median(img: np.ndarray, cx: float, cy: float, half: int = _PATCH) -> Optional[np.ndarray]:
    h, w = img.shape[:2]
    x0, x1 = max(0, int(cx) - half), min(w, int(cx) + half)
    y0, y1 = max(0, int(cy) - half), min(h, int(cy) + half)
    if x1 <= x0 or y1 <= y0:
        return None
    patch = img[y0:y1, x0:x1].reshape(-1, 3)
    lab = _rgb_array_to_lab(patch)
    return np.median(lab, axis=0)


def _mid(points: dict, a: str, b: str) -> tuple[float, float]:
    return ((points[a][0] + points[b][0]) / 2, (points[a][1] + points[b][1]) / 2)


def _region_points(garment_type: GarmentType, points: dict) -> list[tuple[float, float]]:
    """Candidate points likely inside `garment_type`'s garment, in `points`'s own pixel space.
    Usually one point; a jacket/coat gets several (see below) and the caller takes whichever
    samples closest to the item's stored color -- mirrors the primary/secondary "best of a few"
    match already used for stored colors (V-C6), applied here to sample location instead.

    ISSUES #21 (2026-09-27): a jacket worn open/off-the-shoulder (Gemini draped it like a cape
    rather than arms-in-sleeves, seen on avatar_f709dc's sandwich outfits) leaves the *near*
    shoulder-to-elbow midpoint sitting on bare skin or the top underneath -- the jacket fabric is
    there for the other arm instead, or lower down near the elbow itself. One point isn't
    reliable across poses; four is: both arms' shoulder-elbow midpoints, plus both elbows
    outright. Confirmed by probe_verify.py on the two failing renders: the existing single point
    (left shoulder-elbow midpoint) sampled bare skin (dE 37.6 / 23.6 against stored black), while
    at least one of the other three candidates landed on jacket fabric within a couple of dE of 0
    on the same images -- and all four still agreed (best dE 0.8 / 7.2, close to the prior single
    point's 14.9 / 9.1) on the two renders that already passed, so this doesn't loosen anything
    for a jacket worn closed."""
    try:
        if garment_type in (GarmentType.shirt, GarmentType.dress):
            cx, cy = _mid(points, "left_shoulder", "right_shoulder")
            hx, hy = _mid(points, "left_hip", "right_hip")
            return [((cx + hx) / 2, (cy + hy) / 2)]
        if garment_type in (GarmentType.jacket, GarmentType.coat):
            l_sh, l_el = points["left_shoulder"], points["left_elbow"]
            r_sh, r_el = points["right_shoulder"], points["right_elbow"]
            return [
                ((l_sh[0] + l_el[0]) / 2, (l_sh[1] + l_el[1]) / 2),
                ((r_sh[0] + r_el[0]) / 2, (r_sh[1] + r_el[1]) / 2),
                (l_el[0], l_el[1]),
                (r_el[0], r_el[1]),
            ]
        # pants, shorts, skirt: a point on the upper leg, closer to the hip than the knee
        hx, hy = _mid(points, "left_hip", "right_hip")
        kx, ky = _mid(points, "left_knee", "right_knee")
        return [(hx * 0.65 + kx * 0.35, hy * 0.65 + ky * 0.35)]
    except KeyError:
        return []


def _generated_points(generated_rgb: np.ndarray) -> Optional[dict[str, tuple[float, float]]]:
    """Run pose detection on the GENERATED image itself, so sampling doesn't rely on Gemini
    having kept the source photo's framing/pose. -> {name: (x_px, y_px)} or None if detection
    finds nobody (a failure here falls back to scaled source landmarks, never raises)."""
    try:
        detected = landmarks.detect_landmarks(generated_rgb)
    except Exception:
        logger.exception("avatar: verify: pose detection on the generated image crashed")
        return None
    if detected is None:
        return None
    return {name: (v[0], v[1]) for name, v in detected.items()}


def _scaled_source_points(
    source_landmarks: dict, scale_x: float, scale_y: float,
) -> dict[str, tuple[float, float]]:
    return {name: (x * scale_x, y * scale_y) for name, (x, y) in source_landmarks.items()}


def _save_debug_image(generated_rgb: np.ndarray, render_id: str) -> None:
    """Debug-only dump of a failed render's generated image, for a human to look at. Never
    persisted to durable storage (media.save_png already guards `_preview`); never raises --
    losing the debug artifact must not turn a handled verification failure into a crash."""
    try:
        img = Image.fromarray(generated_rgb.astype("uint8"), "RGB")
        media.save_png(img, "_preview", f"{render_id}_generated_debug.png")
    except Exception:
        logger.exception("avatar: verify: could not save debug image for render %s", render_id)


# ---------------------------------------------------------------- ISSUES #22: identity check
#
# The color check above only asks "is this garment the right color" -- it says nothing about
# whether Gemini kept the same PERSON. Two real failures observed: the face cropped out of frame,
# and a different person's face entirely, both with a garment color that still happened to match.
#
# IDENTITY_FACE_MAX_DELTA_E: the generated face's skin-tone patch may drift from the source
# photo's own face patch by this much (Lab, CIEDE2000) before it reads as a different person.
# Calibrated against real renders (2026-09-27): the two known-bad ISSUES #22 renders measured
# dE2000 15.5 (wrong person) and had no detectable face at all (cropped out); three known-good
# renders of the SAME person measured 2.0-2.7 despite being re-lit/regenerated. 10.0 sits with a
# comfortable margin on both sides of that real gap.
IDENTITY_FACE_MAX_DELTA_E = 10.0

# Simple face-shape proportion: eye-to-eye distance / face box width. Compared between the source
# photo and the generated image; a genuinely different face shape (a different person) shifts this
# ratio more than pose/expression/lighting changes do for the SAME person. Same real renders:
# known-good same-person diffs were 0.002-0.009; the one known-bad render with a detectable (wrong)
# face measured 0.040 -- but its skin-tone dE alone already fails it well past IDENTITY_FACE_MAX_
# DELTA_E, so this is a secondary signal and set conservatively (not the deciding one on that case).
IDENTITY_EYE_RATIO_MAX_ABS_DIFF = 1.0  # eye-spacing check off (human decision): it falsely failed the same person (0.41 vs 0.32); skin tone + face present still enforced

# A face touching the generated image's own edge within this many px counts as "cropped out",
# even if the detector still returns a (partial) box for it.
FACE_EDGE_MARGIN_PX = 2


def _head_geometry(points: Optional[dict]) -> Optional[tuple[tuple[float, float], float]]:
    """Same head-estimate formula as rig.compute_rig (duplicated, not imported: `points` here is
    a plain {name: (x, y)} dict -- generated-image detections or source landmarks -- not a full
    Rig/visibility-tagged landmarks dict). -> (head_center, head_radius) or None if shoulders
    aren't in `points`."""
    if not points:
        return None
    try:
        l_sh, r_sh = points["left_shoulder"], points["right_shoulder"]
        shoulder_width = math.hypot(l_sh[0] - r_sh[0], l_sh[1] - r_sh[1])
        shoulder_mid = ((l_sh[0] + r_sh[0]) / 2, (l_sh[1] + r_sh[1]) / 2)
        head_radius = max(shoulder_width * 0.32, 1.0)
        neck_y = shoulder_mid[1] - head_radius * 0.3
        nose = points.get("nose", (shoulder_mid[0], shoulder_mid[1] - head_radius * 2))
        head_center = (nose[0], min(nose[1], neck_y - head_radius * 0.6))
        return head_center, head_radius
    except (KeyError, TypeError):
        return None


def _detect_face_box(rgb: np.ndarray, points: Optional[dict]) -> Optional[tuple[int, int, int, int]]:
    box = face.detect_face_box(rgb)
    if box is not None:
        return box
    geom = _head_geometry(points)
    return face.detect_face_box_near(rgb, *geom) if geom is not None else None


def _detect_face_keypoints(rgb: np.ndarray, points: Optional[dict]) -> Optional[dict]:
    kps = face.detect_face_keypoints(rgb)
    if kps is not None:
        return kps
    geom = _head_geometry(points)
    return face.detect_face_keypoints_near(rgb, *geom) if geom is not None else None


def verify_identity(
    generated_rgb: np.ndarray,
    generated_points: Optional[dict],
    source_rgb: np.ndarray,
    source_points: dict,
) -> tuple[bool, str]:
    """ISSUES #22. -> (ok, reason). Never raises: a crash here means "could not confirm identity",
    which does not block the render (A9 spirit -- this check is an addition on top of the color
    check, not a replacement for the "never fail the render over a detection hiccup" ladder used
    everywhere else in this lane)."""
    try:
        gh, gw = generated_rgb.shape[:2]
        gen_box = _detect_face_box(generated_rgb, generated_points)
        if gen_box is None:
            return False, "identity: no face detected in the generated image"
        x0, y0, x1, y1 = gen_box
        if (x0 <= FACE_EDGE_MARGIN_PX or y0 <= FACE_EDGE_MARGIN_PX
                or x1 >= gw - FACE_EDGE_MARGIN_PX or y1 >= gh - FACE_EDGE_MARGIN_PX):
            return False, "identity: face is cropped at the edge of the generated image"

        source_box = _detect_face_box(source_rgb, source_points)
        if source_box is None:
            logger.info("avatar: verify identity: no face found on the source photo -- skipping the identity match")
            return True, "ok (no source face to compare against)"
        sx0, sy0, sx1, sy1 = source_box

        gen_lab = _patch_lab_median(generated_rgb, (x0 + x1) / 2, (y0 + y1) / 2, half=max(4, (x1 - x0) // 6))
        src_lab = _patch_lab_median(source_rgb, (sx0 + sx1) / 2, (sy0 + sy1) / 2, half=max(4, (sx1 - sx0) // 6))
        if gen_lab is not None and src_lab is not None:
            de = delta_e2000(tuple(src_lab), tuple(gen_lab))
            if de > IDENTITY_FACE_MAX_DELTA_E:
                return False, f"identity: face skin tone drifted too far from the scan (dE2000={de:.1f} > {IDENTITY_FACE_MAX_DELTA_E})"

        gen_kps = _detect_face_keypoints(generated_rgb, generated_points)
        src_kps = _detect_face_keypoints(source_rgb, source_points)
        if gen_kps is not None and src_kps is not None:
            gen_eye = math.hypot(gen_kps["left_eye"][0] - gen_kps["right_eye"][0], gen_kps["left_eye"][1] - gen_kps["right_eye"][1])
            src_eye = math.hypot(src_kps["left_eye"][0] - src_kps["right_eye"][0], src_kps["left_eye"][1] - src_kps["right_eye"][1])
            gen_ratio = gen_eye / max(1.0, x1 - x0)
            src_ratio = src_eye / max(1.0, sx1 - sx0)
            if abs(gen_ratio - src_ratio) > IDENTITY_EYE_RATIO_MAX_ABS_DIFF:
                return False, (f"identity: face proportions don't match the scan "
                               f"(eye-distance/face-width {gen_ratio:.2f} vs {src_ratio:.2f})")

        return True, "ok"
    except Exception:
        logger.exception("avatar: verify identity crashed")
        return True, "ok (identity check crashed -- not blocking on it)"


def verify_colors(
    generated_rgb: np.ndarray,
    source_landmarks: dict,
    source_size: tuple[int, int],
    top: tuple[GarmentType, dict],       # (garment_type, top item's doc: primary_color[, secondary_color])
    bottom: tuple[GarmentType, dict],    # (garment_type, bottom item's doc)
    jacket: Optional[tuple[GarmentType, dict]] = None,
    render_id: Optional[str] = None,     # for the debug-image dump on failure; omit to skip it
    source_rgb: Optional[np.ndarray] = None,  # ISSUES #22: the scan's own source photo, RGB. When
    # omitted, the identity check is skipped entirely (backward compatible with every existing
    # caller/test that doesn't have it handy) -- background.py passes it.
) -> tuple[bool, str]:
    """-> (ok, reason). `source_landmarks`: {name: [x, y]} in the ORIGINAL scan photo's pixel
    space (the same photo sent to Gemini) -- used only as a fallback, rescaled to the generated
    image's own resolution, when pose detection on the generated image itself finds nobody.

    A-R5: a dress layers over the bottom, so the bottom is not sampled when the top is a dress.
    A-R4: a jacket is drawn over the top, so the top is not sampled when a jacket is present.
    """
    gh, gw = generated_rgb.shape[:2]
    sw, sh = source_size
    scale_x = (gw / sw) if sw else 1.0
    scale_y = (gh / sh) if sh else 1.0

    points = _generated_points(generated_rgb)
    point_source = "generated"
    if points is None:
        points = _scaled_source_points(source_landmarks, scale_x, scale_y)
        point_source = "source(scaled)"

    if source_rgb is not None:
        identity_ok, identity_reason = verify_identity(
            generated_rgb, points if point_source == "generated" else None, source_rgb, source_landmarks,
        )
        if not identity_ok:
            logger.info("avatar: verify identity failed: %s", identity_reason)
            if render_id is not None:
                _save_debug_image(generated_rgb, render_id)
            return False, identity_reason

    top_type, top_doc = top
    bottom_type, bottom_doc = bottom
    is_dress = top_type == GarmentType.dress
    has_jacket = jacket is not None

    checks: list[tuple[str, GarmentType, dict]] = []
    if not has_jacket:
        checks.append(("top", top_type, top_doc))
    if not is_dress:
        checks.append(("bottom", bottom_type, bottom_doc))
    if jacket is not None:
        jacket_type, jacket_doc = jacket
        checks.append(("jacket", jacket_type, jacket_doc))

    failures = []
    for role, garment_type, item_doc in checks:
        candidates = _region_points(garment_type, points)
        if not candidates:
            logger.info("avatar: verify %s (%s): no region point (missing landmark)", role, garment_type.value)
            continue  # can't locate this garment's region; don't fail the render over it

        stored_labs = [tuple(item_doc["primary_color"]["lab"])]
        secondary = item_doc.get("secondary_color")
        if secondary is not None:
            stored_labs.append(tuple(secondary["lab"]))

        # Several candidate points per garment (jacket/coat: both arms), take whichever sample
        # is closest to a stored color -- see _region_points' docstring (ISSUES #21).
        best: Optional[tuple[float, tuple[float, float], np.ndarray]] = None
        for point in candidates:
            sampled_lab = _patch_lab_median(generated_rgb, point[0], point[1])
            if sampled_lab is None:
                continue
            de = min(delta_e2000(lab, tuple(sampled_lab)) for lab in stored_labs)
            if best is None or de < best[0]:
                best = (de, point, sampled_lab)

        if best is None:
            logger.info("avatar: verify %s (%s): all sample patches out of bounds", role, garment_type.value)
            continue
        de, point, sampled_lab = best

        logger.info(
            "avatar: verify %s (%s) via %s point=(%.1f,%.1f) of %d candidate(s) sampled_lab=(%.1f,%.1f,%.1f) "
            "stored_lab(s)=%s dE2000=%.1f",
            role, garment_type.value, point_source, point[0], point[1], len(candidates),
            sampled_lab[0], sampled_lab[1], sampled_lab[2], stored_labs, de,
        )
        if de > VERIFY_MAX_DELTA_E:
            failures.append(f"{garment_type.value} color drifted (dE2000={de:.1f} > {VERIFY_MAX_DELTA_E})")

    if failures:
        if render_id is not None:
            _save_debug_image(generated_rgb, render_id)
        return False, "; ".join(failures)

    return True, "ok"
