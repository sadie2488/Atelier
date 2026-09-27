"""Recolor seven colored closet items to the owner's palette (human request 2026-09-27).

Per garment (alpha > 0 only, alpha untouched), in CIELAB:
  L' = L + (Lt - Lmedian)                    shading/texture kept
  (a', b') = R(theta) * s * (a, b)           same rotation+scale for every pixel, chosen so the
                                             median (a, b) lands on the target (a*, b*)

    .venv/Scripts/python.exe backend/vision/scripts/recolor_items.py            # preview sheet only
    .venv/Scripts/python.exe backend/vision/scripts/recolor_items.py --apply    # write live data
"""
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from scipy import ndimage  # noqa: E402
from skimage.color import lab2rgb, rgb2lab  # noqa: E402

from backend import config  # noqa: E402
from backend.avatar.media import load_media  # noqa: E402

# id -> (target hex, display_name, new retailer_item_name)
TARGETS = {
    "top_3c3a8d": ("#1f2a4d", "navy", "Navy satin shirt"),
    "top_f73474": ("#4a2545", "aubergine", "Aubergine knit cardigan"),
    "top_937754": ("#7a1020", "deep red", "Deep red chunky knit sweater"),
    "bottom_958dc4": ("#6d1a2e", "burgundy", "Burgundy satin slip skirt"),
    "bottom_542088": ("#5b5a2a", "olive", "Olive pleated shorts"),
    "jacket_dec6f5": ("#6b6b3a", "olive", "Olive cropped utility jacket"),
    "jacket_042c40": ("#5e1a1f", "maroon", "Maroon wool coat"),
}


def hex_to_lab(h: str) -> np.ndarray:
    rgb = np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64) / 255.0
    return rgb2lab(rgb.reshape(1, 1, 3)).reshape(3)


def recolor(img: Image.Image, target_hex: str) -> Image.Image:
    rgba = np.asarray(img.convert("RGBA")).copy()
    alpha = rgba[..., 3] > 0
    core = ndimage.binary_erosion(alpha, iterations=2)
    if not core.any():
        core = alpha
    lab = rgb2lab(rgba[..., :3].astype(np.float64) / 255.0)
    med = np.median(lab[core], axis=0)
    t = hex_to_lab(target_hex)

    m_ab, t_ab = complex(med[1], med[2]), complex(t[1], t[2])
    factor = t_ab / m_ab if abs(m_ab) > 1e-6 else 0  # rotation + scale as one complex multiply
    px = lab[alpha]
    ab = (px[:, 1] + 1j * px[:, 2]) * factor
    if abs(m_ab) <= 1e-6:
        ab = ab + t_ab
    out = np.stack([np.clip(px[:, 0] + (t[0] - med[0]), 0, 100), ab.real, ab.imag], axis=1)
    rgb = np.clip(lab2rgb(out.reshape(-1, 1, 3)).reshape(-1, 3), 0, 1)
    rgba[..., :3][alpha] = np.round(rgb * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def preview():
    thumb_h, pad, label_w = 300, 16, 220
    rows = []
    for slug, (hx, name, _) in TARGETS.items():
        before = load_media(f"/media/items/{slug}.png")
        after = recolor(before, hx)
        bbox = before.getbbox()
        before, after = before.crop(bbox), after.crop(bbox)
        scale = thumb_h / before.height
        size = (max(1, int(before.width * scale)), thumb_h)
        rows.append((slug, name, hx, before.resize(size, Image.LANCZOS), after.resize(size, Image.LANCZOS)))
    col_w = max(r[3].width for r in rows)
    W = label_w + 2 * col_w + 4 * pad
    H = len(rows) * (thumb_h + pad) + pad
    sheet = Image.new("RGBA", (W, H), (242, 240, 236, 255))
    d = ImageDraw.Draw(sheet)
    for i, (slug, name, hx, b, a) in enumerate(rows):
        y = pad + i * (thumb_h + pad)
        d.text((pad, y + 10), slug, fill=(30, 30, 30, 255))
        d.text((pad, y + 30), f"-> {name} {hx}", fill=(30, 30, 30, 255))
        d.rectangle([pad, y + 55, pad + 60, y + 95], fill=hx)
        x0 = label_w + pad
        sheet.alpha_composite(b, (x0, y))
        sheet.alpha_composite(a, (x0 + col_w + pad, y))
    out = config.MEDIA_DIR / "_preview" / "recolor_sheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out)
    print(out)


def _delete_media(db, url: str | None) -> None:
    if not url or not url.startswith("/media/"):
        return
    rel = url[len("/media/"):]
    p = config.MEDIA_DIR / rel
    if p.is_file():
        p.unlink()
    from backend import media_store
    bucket = media_store._bucket()
    for f in bucket.find({"filename": rel}):
        bucket.delete(f._id)


def apply():
    from backend import media_store
    from backend.avatar import ids
    from backend.db import get_db
    from backend.vision.color import extract_colors
    from contract.schemas import Item

    db = get_db()
    items = db["items"]
    backup_dir = config.MEDIA_DIR / "_backup" / "recolor"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Find affected renders BEFORE touching anything (render_id is a hash of the id tuple).
    all_items = list(items.find({}))
    tops = [i["id"] for i in all_items if i.get("garment_type") in ("shirt", "dress")]
    bottoms = [i["id"] for i in all_items if i.get("garment_type") in ("pants", "shorts", "skirt")]
    jackets = [None] + [i["id"] for i in all_items if i.get("garment_type") in ("jacket", "coat")]
    touched = set(TARGETS)
    doomed = []
    for av in db["avatars"].find({}, {"avatar_id": 1}):
        for t in tops:
            for b in bottoms:
                for j in jackets:
                    if not ({t, b, j} & touched):
                        continue
                    rid = ids.render_id_for(av["avatar_id"], t, b, j)
                    doc = db["renders"].find_one({"render_id": rid})
                    if doc is not None:
                        doomed.append(doc)

    for slug, (hx, name, new_name) in TARGETS.items():
        doc = items.find_one({"id": slug})
        if doc is None:
            print(f"{slug}: not in DB, skipped")
            continue
        src = load_media(doc["cutout_url"])
        path = config.MEDIA_DIR / "items" / f"{slug}.png"
        bk = backup_dir / f"{slug}.png"
        if not bk.exists():
            shutil.copy2(path, bk)
        out = recolor(Image.open(bk).convert("RGBA") if bk.exists() else src, hx)
        out.save(path, format="PNG")
        media_store.persist(path)
        primary, secondary = extract_colors(np.asarray(out))
        primary["display_name"] = name
        upd = {"primary_color": primary, "secondary_color": secondary, "retailer_item_name": new_name}
        doc.update(upd)
        body = {k: v for k, v in doc.items() if k in Item.model_fields}  # DB-only fields (anchors) aren't in the contract
        if isinstance(body.get("created_at"), datetime) and body["created_at"].tzinfo is None:
            body["created_at"] = body["created_at"].replace(tzinfo=timezone.utc)
        Item.model_validate(body)
        items.update_one({"id": slug}, {"$set": upd})
        print(f"{slug}: {new_name} primary={primary['hex']} {primary['name']}/{primary['family']} "
              f"neutral={primary['is_neutral']} secondary={secondary and secondary['hex']}")

    for r in doomed:
        for k in ("local_url", "generated_url"):
            _delete_media(db, r.get(k))
        db["renders"].delete_one({"_id": r["_id"]})
    print(f"deleted {len(doomed)} render doc(s): {[r['render_id'] for r in doomed]}")


if __name__ == "__main__":
    apply() if "--apply" in sys.argv else preview()
