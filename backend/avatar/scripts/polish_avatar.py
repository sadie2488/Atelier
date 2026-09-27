"""One-off demo polish for a stored real-body avatar cutout: recover sock/shoe pixels the person
mask cut off (GrabCut on the SOURCE photo around each foot, seeded by the current mask), smooth
the legs/feet silhouette (below the hips only), and optionally upscale 2x.

    python backend/avatar/scripts/polish_avatar.py --avatar avatar_0342be            # preview (default)
    python backend/avatar/scripts/polish_avatar.py --avatar avatar_0342be --apply    # overwrite

--preview writes media/_preview/polish_<short>_before_after.png only.
--apply overwrites the avatar PNG (same key, media.save_png) and, if --scale 2, the wireframe PNG
and the doc's canvas_w/canvas_h/rig (canvas coordinates). Debug aid, not part of the API.

--fix-ankles works on the CURRENT (already polished, any scale) avatar in place: per lower leg
(mid-shin down) it fills concave dents in the left/right silhouette edges (1-D grey closing of
the per-row extents), never removing pixels. Preview: media/_preview/ankle_fix_<short>.png.
--apply-ankles saves the result over the avatar PNG (same key, same size, no doc change).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

from backend.avatar import media

PREVIEW_DIR = ROOT / "media" / "_preview"


def _canvas_offset(doc):
    """canvas (x, y) + offset = source-photo (x, y); build_avatar_visuals only translates."""
    lx, ly = doc["rig"]["landmarks"]["nose"]
    sx, sy = doc["source_landmarks"]["nose"]
    return int(round(sx - lx)), int(round(sy - ly))


def _source_on_canvas(photo, off, size):
    w, h = size
    ox, oy = off
    out = np.zeros((h, w, 3), np.uint8)
    ph, pw = photo.shape[:2]
    x0, y0, x1, y1 = max(0, ox), max(0, oy), min(pw, ox + w), min(ph, oy + h)
    out[y0 - oy:y1 - oy, x0 - ox:x1 - ox] = photo[y0:y1, x0:x1]
    return out


def recover_feet(mask, src, rig, up=4):
    """GrabCut around each lower leg/foot on the source pixels; returns the grown mask."""
    h, w = mask.shape
    lm = rig["landmarks"]
    out = mask.copy()
    for side in ("left", "right"):
        kx, ky = lm[f"{side}_knee"]
        ax, ay = lm[f"{side}_ankle"]
        shin = ay - ky
        y0 = int(max(0, ay - 0.45 * shin))
        y1 = h
        x0 = int(max(0, ax - 0.45 * shin))
        x1 = int(min(w, ax + 0.45 * shin))
        m = mask[y0:y1, x0:x1]
        crop = src[y0:y1, x0:x1]
        big = cv2.resize(crop, (crop.shape[1] * up, crop.shape[0] * up), interpolation=cv2.INTER_CUBIC)
        mb = cv2.resize(m.astype(np.uint8), (big.shape[1], big.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
        gc = np.full(mb.shape, cv2.GC_BGD, np.uint8)
        near = ndimage.binary_dilation(mb, iterations=6 * up)
        gc[near] = cv2.GC_PR_BGD
        gc[mb] = cv2.GC_PR_FGD
        gc[ndimage.binary_erosion(mb, iterations=2 * up)] = cv2.GC_FGD
        bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
        cv2.grabCut(cv2.cvtColor(big, cv2.COLOR_RGB2BGR), gc, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
        fg = (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)
        # back to native: majority vote per native pixel
        fgn = cv2.resize(fg.astype(np.float32), (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_AREA) > 0.5
        # Floor reflection under the shoes is lighter than the shoe/sock: only admit new pixels
        # that are not light floor/wall, and keep what is connected to the existing leg.
        lum = crop.mean(axis=2)
        new = fgn & ~m & (lum < 150)
        grown = m | new
        lab, _ = ndimage.label(grown)
        keep = np.isin(lab, np.unique(lab[m]))
        keep[lab == 0] = False
        grown = (grown & keep) | m
        grown = ndimage.binary_fill_holes(grown)
        # Floor under the shoe sole: per column, drop masked pixels below the lowest dark (shoe)
        # pixel when they are light -- the reflection/floor speck the segmenter kept.
        foot_top = int(ay - y0)
        dark = (lum < 80) & grown
        for cx in range(grown.shape[1]):
            ys = np.nonzero(dark[foot_top:, cx])[0]
            if len(ys):
                below = np.arange(grown.shape[0]) > foot_top + ys[-1]
                grown[below & (lum[:, cx] > 110), cx] = False
        out[y0:y1, x0:x1] = grown
    return out


def smooth_legs(alpha_f, mask, hip_y, scale, sigma=1.8):
    """-> alpha at `scale`x: legs/feet (below hips) from a blurred-and-rethresholded mask;
    above the hips the original alpha upscaled unchanged, with a short ramp between."""
    h, w = mask.shape
    W, H = w * scale, h * scale
    soft = ndimage.gaussian_filter(mask.astype(np.float32), sigma)
    soft_up = cv2.resize(soft, (W, H), interpolation=cv2.INTER_CUBIC)
    # 0.45 (not 0.5): do not shrink the legs; still fills notches narrower than ~sigma.
    hard = (soft_up > 0.45).astype(np.float32)
    legs = ndimage.gaussian_filter(hard, 0.6 * scale)
    orig = cv2.resize(alpha_f, (W, H), interpolation=cv2.INTER_CUBIC).clip(0, 1)
    ys = np.arange(H, dtype=np.float32)[:, None] / scale
    t = np.clip((ys - hip_y) / 12.0, 0, 1)
    return (orig * (1 - t) + legs * t).clip(0, 1)


def decontaminate(rgb, mask, iters=3):
    """Replace edge-pixel colours with the nearest interior colour so background (white wall,
    floor, dark baseboard) doesn't bleed into the feathered edge."""
    inner = ndimage.binary_erosion(mask, iterations=1)
    out = rgb.astype(np.float32).copy()
    known = inner.copy()
    for _ in range(iters + 2):
        k = known.astype(np.float32)
        num = np.stack([ndimage.uniform_filter(out[..., c] * k, 3) for c in range(3)], -1)
        den = ndimage.uniform_filter(k, 3)[..., None]
        fill = (~known) & (den[..., 0] > 1e-3)
        out[fill] = (num / np.maximum(den, 1e-6))[fill]
        known = known | fill
    return out.clip(0, 255).astype(np.uint8)


def polish(doc, avatar, photo, scale):
    a = np.array(avatar.convert("RGBA"))
    h, w = a.shape[:2]
    alpha_f = a[..., 3].astype(np.float32) / 255.0
    mask = alpha_f > 0.5
    src = _source_on_canvas(np.array(photo.convert("RGB")), _canvas_offset(doc), (w, h))
    rig = doc["rig"]
    hip_y = max(rig["landmarks"]["left_hip"][1], rig["landmarks"]["right_hip"][1]) + 8

    grown = recover_feet(mask, src, rig)
    below = np.arange(h)[:, None] > hip_y
    grown = np.where(below, grown, mask)

    rgb = a[..., :3].copy()
    newpx = grown & ~mask
    rgb[newpx] = src[newpx]
    legs_region = below & (grown | ndimage.binary_dilation(grown, iterations=3))
    rgb_dec = decontaminate(rgb, grown)
    rgb = np.where(legs_region[..., None], rgb_dec, rgb)

    alpha = smooth_legs(alpha_f, grown, hip_y, scale)
    W, H = w * scale, h * scale
    rgb_img = Image.fromarray(rgb).resize((W, H), Image.LANCZOS) if scale != 1 else Image.fromarray(rgb)
    out = np.dstack([np.array(rgb_img), (alpha * 255).round().astype(np.uint8)])
    return Image.fromarray(out, "RGBA"), int(newpx.sum())


def _source_at_canvas_scale(doc, photo, size):
    """Source photo aligned to the current canvas. The canvas may be s x the source scale (after
    polish --scale 2); s is recovered from rig vs source landmark spans, then canvas/s + off = source."""
    W, H = size
    rl, sl = doc["rig"]["landmarks"], doc["source_landmarks"]
    span = lambda d: np.hypot(*np.subtract(d["left_ankle"], d["nose"]))
    s = max(1, int(round(span(rl) / span(sl))))
    sx, sy = sl["nose"]
    off = (int(round(sx - rl["nose"][0] / s)), int(round(sy - rl["nose"][1] / s)))
    native = _source_on_canvas(np.array(photo.convert("RGB")), off, (W // s, H // s))
    if s == 1:
        return native, off, s
    return np.array(Image.fromarray(native).resize((W, H), Image.LANCZOS)), off, s


def _fill_edge(ext, win, outer_is_max):
    """1-D closing on the edge profile: raises dips (for a max edge) / lowers bumps (min edge)."""
    v = ext.astype(np.float32)
    if not outer_is_max:
        v = -v
    closed = ndimage.grey_closing(v, size=win, mode="nearest")
    closed = ndimage.gaussian_filter1d(closed, 1.5, mode="nearest")
    closed = np.maximum(closed, v)
    closed = np.floor(closed + 0.3)
    return closed if outer_is_max else -closed


def fix_ankles(doc, avatar, photo):
    a = np.array(avatar.convert("RGBA"))
    H, W = a.shape[:2]
    alpha = a[..., 3].astype(np.float32) / 255.0
    mask = alpha > 0.5
    src, off, s = _source_at_canvas_scale(doc, photo, (W, H))
    lm = doc["rig"]["landmarks"]
    split = int(round((lm["left_knee"][0] + lm["right_knee"][0]) / 2))
    fill = np.zeros_like(mask)
    for side in ("left", "right"):
        ky, ay = lm[f"{side}_knee"][1], lm[f"{side}_ankle"][1]
        y0 = int((ky + ay) / 2)
        x0, x1 = (split, W) if lm[f"{side}_knee"][0] > split else (0, split)
        sub = mask[y0:, x0:x1]
        rows = np.nonzero(sub.any(1))[0]
        if len(rows) < 5:
            continue
        r0, r1 = rows[0], rows[-1] + 1
        L = np.array([np.nonzero(sub[r])[0].min() for r in range(r0, r1)])
        R = np.array([np.nonzero(sub[r])[0].max() for r in range(r0, r1)])
        win = max(9, int(0.2 * (ay - ky)) | 1)
        nL = _fill_edge(L, win, False).astype(int)
        nR = _fill_edge(R, win, True).astype(int)
        # Stop at the shoe's widest row per edge: below it the sole/toe rounds off on purpose.
        a_i = max(0, int(ay) - y0 - r0)
        stopR = a_i + int(np.argmax(R[a_i:])) if a_i < len(R) else len(R) - 1
        stopL = a_i + int(np.argmin(L[a_i:])) if a_i < len(L) else len(L) - 1
        for i, r in enumerate(range(r0, r1)):
            row = fill[y0 + r, x0:x1]
            if i <= stopL:
                row[nL[i]:L[i]] = True
            if i <= stopR:
                row[R[i] + 1:nR[i] + 1] = True
            # interior holes between the edges too
            seg = ~sub[r, L[i]:R[i] + 1]
            row[L[i]:R[i] + 1] |= seg
    fill &= ~mask
    new_mask = mask | fill
    # colours: dark source (shoe/strap) where it is dark; else nearest inside colour (the sock and
    # the wall are the same grey in this photo, so light source pixels are not trusted).
    rgb = a[..., :3].copy()
    # nearest-inside colour along the same row (extends the row's own edge colour outward),
    # 2-D nearest as a fallback for rows with no solid pixel
    idx = ndimage.distance_transform_edt(~mask, return_distances=False, return_indices=True)
    near = rgb[idx[0], idx[1]]
    solid = alpha > 0.9
    for y in np.nonzero(fill.any(1))[0]:
        xs_in = np.nonzero(solid[y])[0]
        if not len(xs_in):
            continue
        for x in np.nonzero(ndimage.binary_dilation(fill, iterations=2)[y])[0]:
            j = xs_in[np.argmin(np.abs(xs_in - x))]
            k = min(max(j + (2 if j < x else -2) * -1, 0), rgb.shape[1] - 1)  # 2 px inside the edge
            near[y, x] = rgb[y, k] if solid[y, k] else rgb[y, j]
    lum = src.astype(np.float32).mean(2)
    near_lum = near.astype(np.float32).mean(2)
    use_src = fill & (lum < 110) & (near_lum < 70)  # dark source only beside dark (shoe) pixels
    grow = ndimage.binary_dilation(fill, iterations=2)
    recol = grow & (alpha < 0.95)  # new + partially transparent old edge pixels near the fill
    rgb[recol] = near[recol]
    rgb[use_src] = src[use_src]
    feather = ndimage.gaussian_filter(new_mask.astype(np.float32), 0.7)
    new_alpha = alpha.copy()
    zone = ndimage.binary_dilation(fill, iterations=3)
    new_alpha[zone] = np.maximum(alpha[zone], feather[zone])
    new_alpha[fill] = np.maximum(new_alpha[fill], 0.6)
    out = np.dstack([rgb, (new_alpha * 255).round().clip(0, 255).astype(np.uint8)])
    return Image.fromarray(out, "RGBA"), int(fill.sum()), int(use_src.sum()), off, s


def preview_ankles(before, after, rig, short, z=6):
    full = [_on_magenta(before), _on_magenta(after)]
    lm = rig["landmarks"]
    y0 = int(min(lm["left_knee"][1], lm["right_knee"][1]) * 0.35 + min(lm["left_ankle"][1], lm["right_ankle"][1]) * 0.65)
    xs = [lm["left_ankle"][0], lm["right_ankle"][0]]
    x0, x1 = int(max(0, min(xs) - 45)), int(min(before.width, max(xs) + 45))
    box = (x0, y0, x1, before.height)
    zs = ((x1 - x0) * z, (before.height - y0) * z)
    zb = full[0].crop(box).resize(zs, Image.NEAREST)
    za = full[1].crop(box).resize(zs, Image.NEAREST)
    gap = 12
    top_w = before.width * 2 + gap
    W = max(top_w, zs[0])
    Ht = before.height + gap + zs[1] * 2 + gap
    sheet = Image.new("RGB", (W, Ht), (40, 40, 40))
    sheet.paste(full[0], (0, 0)); sheet.paste(full[1], (before.width + gap, 0))
    sheet.paste(zb, (0, before.height + gap)); sheet.paste(za, (0, before.height + gap * 2 + zs[1]))
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = PREVIEW_DIR / f"ankle_fix_{short}.png"
    sheet.save(path)
    return path


def scale_rig(rig, s):
    pt = lambda p: [p[0] * s, p[1] * s]
    return {
        "landmarks": {k: pt(v) for k, v in rig["landmarks"].items()},
        "shoulder_mid": pt(rig["shoulder_mid"]), "hip_mid": pt(rig["hip_mid"]),
        "shoulder_width": rig["shoulder_width"] * s, "hip_width": rig["hip_width"] * s,
        "neck": pt(rig["neck"]), "head_center": pt(rig["head_center"]), "head_radius": rig["head_radius"] * s,
    }


def _on_magenta(img):
    bg = Image.new("RGBA", img.size, (255, 0, 255, 255))
    bg.alpha_composite(img.convert("RGBA"))
    return bg.convert("RGB")


def preview(before, after, rig, short):
    s = after.width // before.width
    b2 = before.resize(after.size, Image.LANCZOS)  # same display size for a fair look
    full = [_on_magenta(b2), _on_magenta(after)]
    lm = rig["landmarks"]
    y0 = int(min(lm["left_knee"][1], lm["right_knee"][1]) - 10)
    box = (0, y0 * s, after.width, after.height)
    zb = _on_magenta(before).crop((0, y0, before.width, before.height)).resize(
        ((box[2] - box[0]) * 4 // s, (box[3] - box[1]) * 4 // s), Image.NEAREST)
    za = _on_magenta(after).crop(box).resize(zb.size, Image.NEAREST)
    gap = 12
    W = max(full[0].width * 2, zb.width * 2) + gap
    H = full[0].height + gap + zb.height
    sheet = Image.new("RGB", (W, H), (40, 40, 40))
    sheet.paste(full[0], (0, 0)); sheet.paste(full[1], (full[0].width + gap, 0))
    sheet.paste(zb, (0, full[0].height + gap)); sheet.paste(za, (zb.width + gap, full[0].height + gap))
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = PREVIEW_DIR / f"polish_{short}_before_after.png"
    sheet.save(path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--preview", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--fix-ankles", action="store_true", help="preview the ankle dent fill on the current avatar")
    g.add_argument("--apply-ankles", action="store_true", help="save the ankle dent fill over the avatar PNG")
    ap.add_argument("--scale", type=int, default=2, choices=(1, 2))
    args = ap.parse_args()

    from backend.db import get_db
    col = get_db().avatars
    doc = col.find_one({"avatar_id": args.avatar})
    if doc is None:
        sys.exit(f"no avatar {args.avatar}")
    if args.fix_ankles or args.apply_ankles:
        before = media.load_media(doc["avatar_url"]).convert("RGBA")
        photo = media.load_media(doc["source_photo_url"])
        after, n_fill, n_src, off, s = fix_ankles(doc, before, photo)
        short = args.avatar.split("_", 1)[-1]
        path = preview_ankles(before, after, doc["rig"], short)
        print(f"ankles: filled {n_fill} px ({n_src} from source), offset {off}, scale {s}; preview {path}")
        if args.apply_ankles:
            media.save_png(after, "avatars", Path(doc["avatar_url"]).name)
            print(f"applied: {doc['avatar_url']} (size {after.size}, doc unchanged)")
        return
    if doc["canvas_w"] * args.scale > 600:
        sys.exit("avatar already looks upscaled; refusing to scale again")
    before = media.load_media(doc["avatar_url"]).convert("RGBA")
    photo = media.load_media(doc["source_photo_url"])
    after, n_new = polish(doc, before, photo, args.scale)
    short = args.avatar.split("_", 1)[-1]
    path = preview(before, after, doc["rig"], short)
    print(f"recovered {n_new} native px; {before.size} -> {after.size}; preview {path}")

    if not args.apply:
        return
    fname = Path(doc["avatar_url"]).name
    media.save_png(after, "avatars", fname)
    update = {}
    if args.scale != 1:
        from backend.avatar.draw import draw_wireframe
        from backend.avatar.rig import rig_from_dict
        new_rig = scale_rig(doc["rig"], args.scale)
        update = {"rig": new_rig, "canvas_w": after.width, "canvas_h": after.height}
        media.save_png(draw_wireframe(rig_from_dict(new_rig), after.size), "avatars", Path(doc["wireframe_url"]).name)
    if update:
        col.update_one({"avatar_id": args.avatar}, {"$set": update})
    print(f"applied: {doc['avatar_url']} {update and list(update)}")


if __name__ == "__main__":
    main()
