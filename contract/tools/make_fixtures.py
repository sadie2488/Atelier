#!/usr/bin/env python3
"""Regenerate every file in contract/fixtures/ and contract/schema.json. HUMAN-OWNED.

Run from the repo root:  python -m contract.tools.make_fixtures
Edit the ITEMS table below to change the fixture closet; every color field is computed
from hex via colors.json (nearest CIEDE2000 center), so the fixtures cannot drift.
Deterministic: same table, same output.
"""
import hashlib
import json
from pathlib import Path

from contract import schemas as S
from contract.enums import NEUTRAL_CHROMA_MAX, SLUG_PREFIX, GarmentType
from contract.tools.color import hex_to_lab, lab_to_lch, nearest_color

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
API = FIX / "api"


def hexid(seed: str, n: int = 6) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()[:n]


def color(hex_: str) -> dict:
    lab = tuple(round(v, 2) for v in hex_to_lab(hex_))
    L, C, h = (round(v, 2) for v in lab_to_lch(lab))
    name, family, everyday = nearest_color(lab)
    return {"lab": list(lab), "lch": [L, C, h % 360],  # 359.996 must not round to 360
            "hex": hex_, "name": name, "family": family,
            "is_neutral": C < NEUTRAL_CHROMA_MAX, "everyday_neutral": everyday}


# key, category, garment_type, primary hex, secondary hex, retailer color, retailer item name
# Listed oldest first; created_at is one hour apart.
ITEMS = [
    ("white-tee",     "tops",    "shirt",  "#f4f2ee", None,      "Optic White",  "Essential Crew Tee"),
    ("red-shirt",     "tops",    "shirt",  "#b23a35", None,      "Brick Red",    "Relaxed Poplin Shirt"),
    ("blue-oxford",   "tops",    "shirt",  "#a9c4e0", None,      "Sky Blue",     "Oxford Button-Down"),
    ("floral-dress",  "tops",    "dress",  "#3d7a4a", "#e8b4bc", "Forest Floral", "Tiered Midi Dress"),
    ("denim-jeans",   "bottoms", "pants",  "#3b5b8a", None,      "Mid Wash",     "Straight Leg Jean"),
    ("beige-chinos",  "bottoms", "pants",  "#d8c3a5", None,      "Stone",        "Slim Chino"),
    ("black-skirt",   "bottoms", "skirt",  "#1c1c1f", None,      "Black",        "A-Line Mini Skirt"),
    ("olive-shorts",  "bottoms", "shorts", "#6b6b3a", None,      "Olive",        "Utility Short"),
    ("navy-jacket",   "jackets", "jacket", "#1f2a44", None,      "Navy",         "Cropped Chore Jacket"),
    ("camel-coat",    "jackets", "coat",   "#b8864f", None,      "Camel",        "Wool Blend Overcoat"),
]


def slug(key: str, garment_type: str) -> str:
    return f"{SLUG_PREFIX[GarmentType(garment_type)]}_{hexid('item:' + key)}"


def ts(hour: int) -> str:
    return f"2026-09-26T{hour:02d}:00:00Z"


def item(row, n: int) -> dict:
    key, cat, gt, prim, sec, rcolor, rname = row
    sid = slug(key, gt)
    return {
        "id": sid, "category": cat, "garment_type": gt,
        "cutout_url": f"/media/items/{sid}.png",
        "primary_color": color(prim),
        "secondary_color": color(sec) if sec else None,
        "retailer_color": rcolor, "retailer_item_name": rname,
        "attributes": {}, "created_at": ts(8 + n),
    }


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    items = [item(r, n) for n, r in enumerate(ITEMS)]
    items_newest_first = sorted(items, key=lambda i: i["created_at"], reverse=True)
    I = {r[0]: slug(r[0], r[2]) for r in ITEMS}  # noqa: E741

    def outfit(n, strategy, top, bottom, jacket, score, explanation):
        return {"outfit_id": f"outfit_{hexid(f'outfit:{n}')}", "strategy": strategy,
                "top_id": I[top], "bottom_id": I[bottom], "jacket_id": I[jacket] if jacket else None,
                "explanation": explanation, "score": score}

    outfits = [
        outfit(1, "neutral_anchor", "red-shirt", "black-skirt", None, 0.91,
               "A black skirt lets the brick-red shirt lead without competing with it."),
        outfit(2, "everyday_neutral_base", "blue-oxford", "beige-chinos", None, 0.86,
               "Stone chinos are an easy everyday base for a soft sky-blue oxford."),
        outfit(3, "analogous", "floral-dress", "olive-shorts", None, 0.81,
               "Forest green and olive sit side by side on the color wheel, so the look reads calm."),
        outfit(4, "sandwich", "white-tee", "denim-jeans", "navy-jacket", 0.78,
               "Navy jacket and denim bookend the outfit; the white tee breaks it up."),
        outfit(5, "neutral_anchor", "white-tee", "olive-shorts", "camel-coat", 0.72,
               "A white tee anchors olive shorts, and the camel coat adds warmth."),
    ]

    avatar_id = f"avatar_{hexid('avatar:1')}"
    avatar = {"avatar_id": avatar_id,
              "wireframe_url": f"/media/avatars/{avatar_id}_wireframe.png",
              "avatar_url": f"/media/avatars/{avatar_id}.png",
              "created_at": ts(7)}
    avatar_scan = {k: v for k, v in avatar.items() if k != "created_at"}

    top, bottom = outfits[0]["top_id"], outfits[0]["bottom_id"]
    render_id = f"render_{hexid(f'{avatar_id}|{top}|{bottom}|', 12)}"
    render_pending = {"render_id": render_id, "status": "pending",
                      "local_url": f"/media/renders/{render_id}_local.png", "generated_url": None}
    render_done = dict(render_pending, status="done",
                       generated_url=f"/media/renders/{render_id}_generated.png")

    # analyze -> save: a new green overshirt; three variants of slightly different color
    handle = f"tmp_{hexid('handle:1', 12)}"
    variant_hex = ["#4f6b45", "#4d6a44", "#526d48"]
    candidates = [{"index": k, "variant": v, "cutout_url": f"/media/tmp/{handle}_{k}.png",
                   "primary_color": color(variant_hex[k]), "secondary_color": None}
                  for k, v in enumerate(["tight", "balanced", "generous"])]
    saved_id = slug("green-overshirt", "shirt")
    saved = {"id": saved_id, "category": "tops", "garment_type": "shirt",
             "cutout_url": f"/media/items/{saved_id}.png",
             "primary_color": candidates[1]["primary_color"], "secondary_color": None,
             "retailer_color": "Moss", "retailer_item_name": "Garment-Dyed Overshirt",
             "attributes": {}, "created_at": ts(20)}

    api = {
        "get_health":             (None, {"status": "ok", "db": "ok"}),
        "post_items_analyze":     ({"_multipart": {"image": "<garment.jpg>", "category": "tops",
                                                   "garment_type": "shirt", "color": "Moss",
                                                   "item_name": "Garment-Dyed Overshirt"}},
                                   {"temp_handle": handle, "candidates": candidates}),
        "post_items_save":        ({"temp_handle": handle, "candidate_index": 1}, saved),
        "post_items_reject":      ({"temp_handle": handle}, {"ok": True}),
        "get_items":              (None, {"items": items_newest_first}),
        "get_items_detail":       (None, items[3]),
        "post_outfits_generate":  ({}, {"outfits": outfits}),
        "post_avatar_scan":       ({"_multipart": {"image": "<full-body.jpg>"}}, avatar_scan),
        "get_avatar_detail":      (None, avatar),
        "post_render":            ({"avatar_id": avatar_id, "top_id": top, "bottom_id": bottom,
                                    "jacket_id": None}, render_pending),
        "get_render_detail":      (None, render_done),
    }
    errors = [
        {"error": {"code": "pose_rejected", "message": "Move your arms slightly away from your body."}},
        {"error": {"code": "no_person_detected", "message": "No person found in the photo. Step back so your whole body is in the outline."}},
        {"error": {"code": "invalid_request", "message": "garment_type 'pants' is not valid for category 'tops' (allowed: dress, shirt)."}},
        {"error": {"code": "handle_expired", "message": f"Temp handle {handle} has expired. Please rescan the item."}},
        {"error": {"code": "not_found", "message": "Item top_000000 does not exist."}},
    ]

    for old in API.glob("*.json"):
        old.unlink()
    write(FIX / "items.json", items)
    write(FIX / "outfits.json", outfits)
    write(FIX / "avatar.json", avatar)
    write(FIX / "render.json", [render_pending, render_done])
    for name, (req, resp) in api.items():
        if req is not None:
            write(API / f"{name}.request.json", req)
        write(API / f"{name}.response.json", resp)
    write(API / "errors.json", errors)

    from pydantic.json_schema import models_json_schema
    _, schema = models_json_schema([(m, "serialization") for m in S.API_MODELS],
                                   title=f"Atelier contract {S.CONTRACT_VERSION}")
    write(ROOT / "schema.json", schema)
    print(f"wrote {len(items)} items, {len(outfits)} outfits, {len(api)} endpoint examples, schema.json")


if __name__ == "__main__":
    main()
