"""A2/A3: wireframe rig -> line-art avatar. No drawn art assets, no template body (A-B7); every
stroke and fill is computed from the landmarks in `rig`.

Shapes (head, neck, torso, tapered limbs) are built once from the rig and rendered with a single
technique: draw the shape inflated/widened in the outline color, then draw the true shape on top
in the fill color (skin tone for the avatar, fully transparent for the wireframe). That leaves a
uniform-width outline ring wherever the fill doesn't cover the outline layer, with no interior
seams where limb segments or joints meet -- one consistent stroke, everywhere, at any body
proportion. Everything is drawn at SUPERSAMPLE x scale and downsampled with LANCZOS for
anti-aliased edges (still deterministic: no randomness anywhere in this module).
"""
from typing import Optional

from PIL import Image, ImageDraw

from .rig import Rig

STROKE = (30, 30, 30, 255)
TRANSPARENT = (0, 0, 0, 0)
STROKE_WIDTH_FRAC = 0.025  # of shoulder width
SUPERSAMPLE = 2
# Above this native canvas dimension, skip supersampling: an uncapped source photo (a phone
# camera frame, nothing in this pipeline downscales it first) would otherwise make the 2x
# render+LANCZOS-downsample step itself the latency risk this task has to stay under. A canvas
# already this large has plenty of native resolution for the edges to look clean without it.
SUPERSAMPLE_MAX_DIM = 1200

# Limb radii, as a fraction of shoulder width, at each joint along the chain.
ARM_RADII_FRAC = (0.085, 0.070, 0.055, 0.062)   # shoulder, elbow, wrist, hand
LEG_RADII_FRAC = (0.135, 0.105, 0.078, 0.090)   # hip, knee, ankle, foot
HAND_LENGTH_FRAC = 0.12   # beyond the wrist, along the forearm direction
FOOT_LENGTH_FRAC = 0.16   # beyond the ankle, along the shin direction


def _stroke_width(rig: Rig) -> int:
    return max(3, round(rig.shoulder_width * STROKE_WIDTH_FRAC))


def _bbox(center: tuple[float, float], radius: float) -> list[float]:
    return [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius]


def _extend(a: tuple[float, float], b: tuple[float, float], length: float) -> tuple[float, float]:
    """-> the point `length` beyond b, continuing the direction from a to b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    return (b[0] + dx / d * length, b[1] + dy / d * length)


def _tangent_quad(p1, r1, p2, r2) -> list[tuple[float, float]]:
    """-> the quad connecting two circles (p1, r1) and (p2, r2) along their common tangent."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    nx, ny = -dy / length, dx / length
    return [
        (p1[0] + nx * r1, p1[1] + ny * r1),
        (p2[0] + nx * r2, p2[1] + ny * r2),
        (p2[0] - nx * r2, p2[1] - ny * r2),
        (p1[0] - nx * r1, p1[1] - ny * r1),
    ]


def _draw_chain(draw: ImageDraw.ImageDraw, points: list, radii: list[float], fill) -> None:
    """A tapered capsule chain: a tangent quad per segment plus a circle at every joint, so the
    whole chain reads as one continuous rounded shape regardless of how the radius changes."""
    for i in range(len(points) - 1):
        draw.polygon(_tangent_quad(points[i], radii[i], points[i + 1], radii[i + 1]), fill=fill)
    for p, r in zip(points, radii):
        draw.ellipse(_bbox(p, r), fill=fill)


def _inflate_polygon(points: list, amount: float) -> list[tuple[float, float]]:
    """Approximate outward offset: push each vertex away from the polygon's centroid by
    `amount` px. Good enough for the small, roughly-convex torso/neck shapes here."""
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    out = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        d = max((dx * dx + dy * dy) ** 0.5, 1e-6)
        out.append((x + dx / d * amount, y + dy / d * amount))
    return out


def _torso_polygon(rig: Rig) -> list[tuple[float, float]]:
    """Shoulders -> waist -> hips (a soft hourglass hexagon, not a bare trapezoid)."""
    L = rig.landmarks
    sm, hm = rig.shoulder_mid, rig.hip_mid
    t = 0.55
    waist = (sm[0] + (hm[0] - sm[0]) * t, sm[1] + (hm[1] - sm[1]) * t)
    waist_half = min(rig.shoulder_width, rig.hip_width) * 0.40
    # "left"/"right" here are the person's own left/right, which in an unmirrored front-facing
    # photo land on the image's right/left respectively -- match left_hip/right_hip's side so the
    # hexagon traces a simple (non-self-intersecting) perimeter instead of a bowtie.
    left_is_higher_x = L["left_hip"][0] >= L["right_hip"][0]
    left_waist = (waist[0] + waist_half, waist[1]) if left_is_higher_x else (waist[0] - waist_half, waist[1])
    right_waist = (waist[0] - waist_half, waist[1]) if left_is_higher_x else (waist[0] + waist_half, waist[1])
    return [L["left_shoulder"], L["right_shoulder"], right_waist, L["right_hip"], L["left_hip"], left_waist]


def _neck_polygon(rig: Rig) -> list[tuple[float, float]]:
    """A short tapered quad from just inside the head circle down to the shoulder line, so the
    head and torso are continuously connected -- no neck gap."""
    top_half = rig.head_radius * 0.42
    top_y = rig.head_center[1] + rig.head_radius * 0.65  # overlaps into the head fill on purpose
    bottom_half = rig.shoulder_width * 0.15
    bottom_y = rig.shoulder_mid[1] + rig.head_radius * 0.15  # overlaps into the torso fill
    return [
        (rig.head_center[0] - top_half, top_y),
        (rig.head_center[0] + top_half, top_y),
        (rig.shoulder_mid[0] + bottom_half, bottom_y),
        (rig.shoulder_mid[0] - bottom_half, bottom_y),
    ]


def _arm_chain(rig: Rig, side: str) -> tuple[list, list[float]]:
    L = rig.landmarks
    shoulder, elbow, wrist = L[f"{side}_shoulder"], L[f"{side}_elbow"], L[f"{side}_wrist"]
    hand = _extend(elbow, wrist, rig.shoulder_width * HAND_LENGTH_FRAC)
    radii = [rig.shoulder_width * f for f in ARM_RADII_FRAC]
    return [shoulder, elbow, wrist, hand], radii


def _leg_chain(rig: Rig, side: str) -> tuple[list, list[float]]:
    L = rig.landmarks
    hip, knee, ankle = L[f"{side}_hip"], L[f"{side}_knee"], L[f"{side}_ankle"]
    foot = _extend(knee, ankle, rig.shoulder_width * FOOT_LENGTH_FRAC)
    radii = [rig.shoulder_width * f for f in LEG_RADII_FRAC]
    return [hip, knee, ankle, foot], radii


def _draw_body(rig: Rig, size: tuple[int, int], fill: Optional[tuple[int, int, int]]) -> Image.Image:
    """The shared shape pipeline. `fill=None` draws only the outline ring (the wireframe /
    loading state, A-R14); a skin RGB fills the body (the assembled avatar, A-B3/A-B4)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w = _stroke_width(rig)
    inner = TRANSPARENT if fill is None else (*fill, 255)

    for side in ("left", "right"):
        points, radii = _leg_chain(rig, side)
        _draw_chain(draw, points, [r + w for r in radii], STROKE)
        _draw_chain(draw, points, radii, inner)

    torso = _torso_polygon(rig)
    draw.polygon(_inflate_polygon(torso, w), fill=STROKE)
    draw.polygon(torso, fill=inner)

    for side in ("left", "right"):
        points, radii = _arm_chain(rig, side)
        _draw_chain(draw, points, [r + w for r in radii], STROKE)
        _draw_chain(draw, points, radii, inner)

    neck = _neck_polygon(rig)
    draw.polygon(_inflate_polygon(neck, w), fill=STROKE)
    draw.polygon(neck, fill=inner)

    draw.ellipse(_bbox(rig.head_center, rig.head_radius), fill=STROKE)
    draw.ellipse(_bbox(rig.head_center, max(0.0, rig.head_radius - w)), fill=inner)

    return img


def _scale_rig(rig: Rig, k: float) -> Rig:
    def s(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0] * k, p[1] * k)

    return Rig(
        landmarks={key: s(v) for key, v in rig.landmarks.items()},
        shoulder_mid=s(rig.shoulder_mid), hip_mid=s(rig.hip_mid),
        shoulder_width=rig.shoulder_width * k, hip_width=rig.hip_width * k,
        neck=s(rig.neck), head_center=s(rig.head_center), head_radius=rig.head_radius * k,
    )


def _supersample_factor(size: tuple[int, int]) -> int:
    return SUPERSAMPLE if max(size) <= SUPERSAMPLE_MAX_DIM else 1


def draw_wireframe(rig: Rig, size: tuple[int, int]) -> Image.Image:
    """Stroke-only line art: the placement rig made visible, and the render loading state (A-R14)."""
    k = _supersample_factor(size)
    hi_rig = _scale_rig(rig, k)
    hi_size = (size[0] * k, size[1] * k)
    hi_img = _draw_body(hi_rig, hi_size, fill=None)
    return hi_img.resize(size, Image.LANCZOS) if k != 1 else hi_img


def draw_avatar(
    rig: Rig, size: tuple[int, int], skin_rgb: tuple[int, int, int], face_img: Optional[Image.Image],
) -> Image.Image:
    """Line art + light skin fill inside the outline (A-B3/A-B4) + the real face (A-B6)."""
    k = _supersample_factor(size)
    hi_rig = _scale_rig(rig, k)
    hi_size = (size[0] * k, size[1] * k)
    hi_img = _draw_body(hi_rig, hi_size, fill=skin_rgb)
    img = hi_img.resize(size, Image.LANCZOS) if k != 1 else hi_img

    if face_img is not None:
        target_h = max(1, round(rig.head_radius * 2.3))
        scale = target_h / face_img.height
        target_w = max(1, round(face_img.width * scale))
        resized = face_img.resize((target_w, target_h), Image.LANCZOS)
        px = round(rig.head_center[0] - target_w / 2)
        py = round(rig.head_center[1] - target_h / 2)
        img.alpha_composite(resized, (px, py))

        # A thin outline framing the face itself, so it reads as sitting in the head rather than
        # floating over it -- a soft mask alone can otherwise blur into an edgeless smear.
        draw = ImageDraw.Draw(img)
        outline_r = target_h / 2 * 0.92
        draw.ellipse(_bbox(rig.head_center, outline_r), outline=STROKE, width=max(1, round(_stroke_width(rig) * 0.6)))

    return img
