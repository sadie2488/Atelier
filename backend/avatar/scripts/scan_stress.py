"""Scan stress test: runs the real scan pipeline (decode -> landmarks -> pose check -> avatar
visuals) on the two model photos, generated webcam-like variants of them, and every stored scan
source photo. Offline; writes nothing to the avatars collection or media/avatars -- avatar PNGs for
accepted variants go to media/_preview/scan_stress_*.png.

    .venv/Scripts/python.exe -m backend.avatar.scripts.scan_stress [--save]
"""
import io
import logging
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from backend.avatar import service
from backend.avatar.errors import AvatarError
from backend.avatar.landmarks import detect_landmarks
from backend.avatar.pose_validation import validate

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "backend" / "avatar" / "models"
PREVIEW = ROOT / "media" / "_preview"

_last_measure: dict = {}


class _Grab(logging.Handler):
    def emit(self, record):
        _last_measure["m"] = record.getMessage()


logging.getLogger("backend.avatar.pose_validation").addHandler(_Grab())
logging.getLogger("backend.avatar.pose_validation").setLevel(logging.INFO)


def _busy_bg(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """A cluttered-room stand-in with no people in it: random colored boxes (shelves, posters,
    furniture edges), slightly blurred, plus sensor noise."""
    w, h = size
    rng = np.random.default_rng(7)
    arr = np.full((h, w, 3), 150, dtype=np.uint8)
    for _ in range(60):
        x0, y0 = int(rng.integers(0, w)), int(rng.integers(0, h))
        bw, bh = int(rng.integers(w // 30, w // 4)), int(rng.integers(h // 30, h // 3))
        arr[y0:y0 + bh, x0:x0 + bw] = rng.integers(20, 235, 3)
    bg = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(2))
    noise = rng.normal(0, 6, (h, w, 3))
    return Image.fromarray(np.clip(np.asarray(bg) + noise, 0, 255).astype(np.uint8))


def landscape(img, size=(1280, 720), person_scale=1.0, shift=0.0):
    """Paste the portrait photo, scaled to `person_scale` of the frame height, onto a landscape
    busy background; `shift` moves it right by that fraction of the frame width."""
    w, h = size
    ph = round(h * person_scale)
    pw = round(img.width * ph / img.height)
    bg = _busy_bg(img, size)
    x = round((w - pw) / 2 + shift * w)
    y = round((h - ph) * 0.6) if person_scale < 1 else 0
    bg.paste(img.resize((pw, ph), Image.LANCZOS), (x, y))
    return bg


def crop_bottom(img, frac):
    return img.crop((0, 0, img.width, round(img.height * (1 - frac))))


def crop_at_ankle(img, body_frac_above):
    """Crop so the bottom edge sits `body_frac_above` of the body height above the lower ankle."""
    lm = detect_landmarks(np.asarray(img))
    ankle = max(lm["left_ankle"][1], lm["right_ankle"][1])
    body = ankle - lm["nose"][1]
    return img.crop((0, 0, img.width, round(ankle - body * body_frac_above)))


def variants(name, img):
    yield f"{name} original", img
    yield f"{name} landscape 1280x720 full-h", landscape(img)
    yield f"{name} landscape 1600x900 full-h", landscape(img, (1600, 900))
    yield f"{name} 960x540 full-h", landscape(img, (960, 540))
    yield f"{name} landscape person~60%", landscape(img, person_scale=0.75)
    yield f"{name} landscape person~50%", landscape(img, person_scale=0.62)
    yield f"{name} landscape person~40%", landscape(img, person_scale=0.5)
    yield f"{name} 960x540 person~50%", landscape(img, (960, 540), person_scale=0.62)
    yield f"{name} landscape off-center +15%", landscape(img, shift=0.15)
    yield f"{name} landscape off-center -15% ~50%", landscape(img, person_scale=0.62, shift=-0.15)
    yield f"{name} bottom crop 5% img", crop_bottom(img, 0.05)
    yield f"{name} bottom crop 10% img", crop_bottom(img, 0.10)
    yield f"{name} crop at ankle (feet off)", crop_at_ankle(img, 0.0)
    yield f"{name} crop 5% body above ankle", crop_at_ankle(img, 0.05)
    yield f"{name} crop 10% body above ankle", crop_at_ankle(img, 0.10)
    yield f"{name} crop 15% body above ankle", crop_at_ankle(img, 0.15)
    yield f"{name} crop 25% body (mid-shin)", crop_at_ankle(img, 0.25)
    yield f"{name} brightness 0.6", ImageEnhance.Brightness(img).enhance(0.6)
    yield f"{name} brightness 0.4", ImageEnhance.Brightness(img).enhance(0.4)
    yield f"{name} rotate +5", img.rotate(5, resample=Image.BICUBIC, fillcolor=(128, 128, 128))
    yield f"{name} rotate -5", img.rotate(-5, resample=Image.BICUBIC, fillcolor=(128, 128, 128))
    yield f"{name} landscape ~50% dim 0.6 feet-5%", crop_at_ankle(
        ImageEnhance.Brightness(landscape(img, person_scale=0.62, shift=0.1)).enhance(0.6), 0.05)
    yield f"{name} mirrored + rotate 5 + 0.6", ImageEnhance.Brightness(
        ImageOps.mirror(img).rotate(5, resample=Image.BICUBIC, fillcolor=(90, 90, 90))).enhance(0.6)
    yield f"{name} upper body only", img.crop((0, 0, img.width, img.height // 2))
    yield f"{name} face only", img.crop((img.width // 4, 0, img.width * 3 // 4, img.height // 6))


def run(label, img, save):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    _last_measure.clear()
    try:
        rgb = service._decode_image(buf.getvalue())
        lm = detect_landmarks(rgb)
        if lm is None:
            return "REJECT", "no_person_detected", ""
        rej = validate(lm, (rgb.shape[1], rgb.shape[0]))
        meas = re.sub(r".*measurements=(\{.*?\}).*", r"\1", _last_measure.get("m", ""))
        if rej is not None:
            return "REJECT", rej[1].replace("\n", " | "), meas
        vis = service.build_avatar_visuals(rgb, lm)
        if save:
            slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            vis["avatar_img"].save(PREVIEW / f"scan_stress_{slug}.png")
        return "ACCEPT", vis["avatar_kind"], meas
    except AvatarError as e:
        return "ERROR", f"{e}", ""


def main():
    save = "--save" in sys.argv
    verbose = "-v" in sys.argv
    rows = []
    for fname in ("model.sadie.jpeg", "model.lalitha.jpeg"):
        img = ImageOps.exif_transpose(Image.open(MODELS / fname)).convert("RGB")
        img = service._downscale(img)
        for label, v in variants(fname.split(".")[1], img):
            rows.append((label, *run(label, v, save)))
    for p in sorted((ROOT / "media" / "avatars").glob("*_photo.png")):
        img = Image.open(p).convert("RGB")
        rows.append((p.name, *run(p.name, img, False)))
    for label, status, detail, meas in rows:
        print(f"{status:6} | {label:44} | {detail}" + (f" | {meas}" if verbose else ""))


if __name__ == "__main__":
    main()
