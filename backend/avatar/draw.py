"""A2/A3: wireframe rig -> line-art avatar. No drawn art assets, no template body (A-B7); every
stroke and fill is computed from the landmarks in `rig`.
"""
from typing import Optional

from PIL import Image, ImageDraw

from .rig import Rig

STROKE = (30, 30, 30, 255)
STROKE_WIDTH_FRAC = 0.02  # of shoulder width


def _stroke_width(rig: Rig) -> int:
    return max(2, round(rig.shoulder_width * STROKE_WIDTH_FRAC))


def _bbox(center: tuple[float, float], radius: float) -> list[float]:
    return [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius]


def draw_wireframe(rig: Rig, size: tuple[int, int]) -> Image.Image:
    """Stroke-only line art: the placement rig made visible, and the render loading state (A-R14)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w = _stroke_width(rig)
    L = rig.landmarks

    draw.ellipse(_bbox(rig.head_center, rig.head_radius), outline=STROKE, width=w)
    draw.line([rig.neck, rig.shoulder_mid], fill=STROKE, width=w)
    draw.line([L["left_shoulder"], L["right_shoulder"]], fill=STROKE, width=w)
    draw.line([L["left_hip"], L["right_hip"]], fill=STROKE, width=w)
    draw.line([L["left_shoulder"], L["left_hip"]], fill=STROKE, width=w)
    draw.line([L["right_shoulder"], L["right_hip"]], fill=STROKE, width=w)
    for side in ("left", "right"):
        draw.line([L[f"{side}_shoulder"], L[f"{side}_elbow"], L[f"{side}_wrist"]],
                   fill=STROKE, width=w, joint="curve")
        draw.line([L[f"{side}_hip"], L[f"{side}_knee"], L[f"{side}_ankle"]],
                   fill=STROKE, width=w, joint="curve")
    return img


def _fill_capsule(draw: ImageDraw.ImageDraw, pts: list[tuple[float, float]], width: int, fill) -> None:
    draw.line(pts, fill=fill, width=width, joint="curve")
    r = width / 2
    for p in pts:
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=fill)


def draw_avatar(
    rig: Rig, size: tuple[int, int], skin_rgb: tuple[int, int, int], face_img: Optional[Image.Image],
) -> Image.Image:
    """Line art + light skin fill inside the outline (A-B3/A-B4) + the real face (A-B6)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill = (*skin_rgb, 255)
    w = _stroke_width(rig)
    L = rig.landmarks

    draw.polygon([L["left_shoulder"], L["right_shoulder"], L["right_hip"], L["left_hip"]], fill=fill)
    for side in ("left", "right"):
        _fill_capsule(draw, [L[f"{side}_shoulder"], L[f"{side}_elbow"], L[f"{side}_wrist"]], w * 3, fill)
        _fill_capsule(draw, [L[f"{side}_hip"], L[f"{side}_knee"], L[f"{side}_ankle"]], w * 4, fill)
    draw.ellipse(_bbox(rig.head_center, rig.head_radius), fill=fill)

    img = Image.alpha_composite(img, draw_wireframe(rig, size))

    if face_img is not None:
        target_h = max(1, round(rig.head_radius * 2.3))
        scale = target_h / face_img.height
        target_w = max(1, round(face_img.width * scale))
        resized = face_img.resize((target_w, target_h), Image.LANCZOS)
        px = round(rig.head_center[0] - target_w / 2)
        py = round(rig.head_center[1] - target_h / 2)
        img.alpha_composite(resized, (px, py))

    return img
