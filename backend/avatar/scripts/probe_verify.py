"""A7 investigation (ISSUES #21): reproduce verify.verify_colors's sampling on an already-generated
image, without spending a Gemini call, and draw the sample boxes so a human can look.

Usage (from repo root, with the project venv):
    .venv/Scripts/python.exe -m backend.avatar.scripts.probe_verify <render_id> <image_path>

Loads the item/avatar docs for the render_id from Mongo (via backend.db.get_db()), runs the same
pose-detection-on-the-generated-image + region-point + patch-median-Lab logic verify.py uses, then
saves a copy of the image with each sampled region boxed and labeled to
media/_preview/<render_id>_sampled.png. Prints sampled vs stored Lab and dE2000 per garment, same
as verify.py's log line, plus which region each point falls in relative to the pose landmarks so a
human can judge whether the box actually landed on the garment it claims to.
"""
import sys

import numpy as np
from PIL import Image, ImageDraw

from backend.avatar import landmarks, verify
from backend.avatar.ids import render_id_for
from backend.db import get_db
from contract.enums import GarmentType
from contract.tools.color import delta_e2000


def _lookup_render(render_id: str) -> dict:
    db = get_db()
    doc = db["renders"].find_one({"render_id": render_id})
    if doc is None:
        raise SystemExit(f"render {render_id} not found")
    return doc


def _find_combo(avatar_ids, top_ids, bottom_ids, jacket_ids, render_id):
    for a in avatar_ids:
        for t in top_ids:
            for b in bottom_ids:
                for j in jacket_ids:
                    if render_id_for(a, t, b, j) == render_id:
                        return a, t, b, j
    return None


def main():
    render_id = sys.argv[1]
    image_path = sys.argv[2]

    db = get_db()
    items = db["items"]
    avatars = db["avatars"]

    # This demo's item/avatar ids are known from ISSUES #21; brute-force match against the
    # deterministic render_id so we don't need a stored (avatar,top,bottom,jacket) tuple on the
    # render doc itself (it isn't kept there -- see backend/avatar/ids.py).
    combo = _find_combo(
        ["avatar_f709dc", "avatar_56501c"],
        ["top_2dd815"],
        ["bottom_6b839f", "bottom_36a1e0"],
        ["jacket_18d0da"],
        render_id,
    )
    if combo is None:
        raise SystemExit(f"could not resolve {render_id} to a known combo; edit the candidate lists")
    avatar_id, top_id, bottom_id, jacket_id = combo
    print(f"{render_id} = {avatar_id} + {top_id} + {bottom_id} + {jacket_id}")

    avatar_doc = avatars.find_one({"avatar_id": avatar_id})
    top_doc = items.find_one({"id": top_id})
    bottom_doc = items.find_one({"id": bottom_id})
    jacket_doc = items.find_one({"id": jacket_id})

    img = Image.open(image_path).convert("RGB")
    generated_rgb = np.asarray(img)

    points = verify._generated_points(generated_rgb)
    point_source = "generated"
    if points is None:
        sw, sh = avatar_doc["source_w"], avatar_doc["source_h"]
        gh, gw = generated_rgb.shape[:2]
        points = verify._scaled_source_points(
            avatar_doc["source_landmarks"], gw / sw, gh / sh
        )
        point_source = "source(scaled)"
    print(f"landmark source: {point_source}")
    for name, pt in points.items():
        print(f"  {name}: ({pt[0]:.1f}, {pt[1]:.1f})")

    checks = [
        ("bottom", GarmentType(bottom_doc["garment_type"]), bottom_doc),
        ("jacket", GarmentType(jacket_doc["garment_type"]), jacket_doc),
    ]

    annotated = img.copy()
    draw = ImageDraw.Draw(annotated)
    colors = {"bottom": (0, 200, 0), "jacket": (255, 0, 255), "jacket_alt": (0, 150, 255)}

    for role, garment_type, item_doc in checks:
        candidates = verify._region_points(garment_type, points)
        if not candidates:
            print(f"{role}: no region point")
            continue
        stored_labs = [tuple(item_doc["primary_color"]["lab"])]
        secondary = item_doc.get("secondary_color")
        if secondary is not None:
            stored_labs.append(tuple(secondary["lab"]))

        best = None
        for i, point in enumerate(candidates):
            sampled_lab = verify._patch_lab_median(generated_rgb, point[0], point[1])
            if sampled_lab is None:
                continue
            de = min(delta_e2000(lab, tuple(sampled_lab)) for lab in stored_labs)
            print(
                f"{role} ({garment_type.value}) candidate[{i}]=({point[0]:.1f},{point[1]:.1f}) "
                f"sampled_lab={tuple(round(float(v), 1) for v in sampled_lab)} dE2000={de:.1f}"
            )
            p = verify._PATCH
            box = [point[0] - p, point[1] - p, point[0] + p, point[1] + p]
            draw.rectangle(box, outline=colors.get(role, (255, 255, 0)), width=2)
            if best is None or de < best[0]:
                best = (de, point)
        if best is not None:
            de, point = best
            print(
                f"{role}: BEST dE2000={de:.1f} at ({point[0]:.1f},{point[1]:.1f}) "
                f"{'FAIL' if de > verify.VERIFY_MAX_DELTA_E else 'ok'}"
            )
            p = verify._PATCH
            box = [point[0] - p, point[1] - p, point[0] + p, point[1] + p]
            draw.rectangle(box, outline=colors.get(role, (255, 255, 0)), width=4)
            draw.text((box[0], box[1] - 14), f"{role} BEST", fill=colors.get(role, (255, 255, 0)))

    out_path = f"media/_preview/{render_id}_sampled.png"
    annotated.save(out_path)
    print(f"annotated image saved to {out_path}")


if __name__ == "__main__":
    main()
