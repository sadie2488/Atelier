#!/usr/bin/env python3
"""Regenerate every file in contract/fixtures/ and contract/schema.json. HUMAN-OWNED.

Run from the repo root:  python3 -m contract.tools.make_fixtures
Edit the GARMENTS table below to change the fixture closet; colors are computed from hex.
"""
import json
from pathlib import Path

from contract import schemas as S
from contract.enums import NEUTRAL_CHROMA_MAX
from contract.tools.color import hex_to_lab, lab_to_lch

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
API = FIX / "api"
TS = "2026-09-26T09:00:00Z"
USER = "demo"


def oid(kind: int, n: int) -> str:
    """Deterministic 24-hex ids: 1=garment 2=avatar 3=outfit 4=render 5=photo."""
    return f"{kind:x}" + "0" * 19 + f"{n:04x}"


def color(hex_, weight):
    lab = hex_to_lab(hex_)
    L, C, h = (round(v, 2) for v in lab_to_lch(lab))
    return {"lab": [round(v, 2) for v in lab], "lch": [L, C, h % 360],  # 359.996 must not round to 360
            "hex": hex_, "weight": weight}


# n, name(subcategory), category, pattern, formality, ownership, [(hex, weight)], tags
GARMENTS = [
    (1,  "t-shirt",        "top",       "solid",  1, "owned",   [("#f4f2ee", 0.92)],                    ["basic"]),
    (2,  "flannel shirt",  "top",       "plaid",  2, "owned",   [("#a8322d", 0.55), ("#1f2a44", 0.30)], ["casual", "layering"]),
    (3,  "breton top",     "top",       "stripe", 2, "owned",   [("#f2efe8", 0.52), ("#1d2b4f", 0.44)], ["classic"]),
    (4,  "sweater",        "top",       "solid",  3, "owned",   [("#d9a13b", 0.95)],                    ["knit", "warm"]),
    (5,  "hoodie",         "top",       "solid",  1, "owned",   [("#8e9196", 0.94)],                    ["casual"]),
    (6,  "jeans",          "bottom",    "solid",  2, "owned",   [("#1c1c1f", 0.96)],                    ["denim"]),
    (7,  "jeans",          "bottom",    "solid",  2, "owned",   [("#3b5b8a", 0.90)],                    ["denim"]),
    (8,  "chinos",         "bottom",    "solid",  3, "owned",   [("#d8c3a5", 0.95)],                    ["smart casual"]),
    (9,  "midi skirt",     "bottom",    "floral", 3, "owned",   [("#2f4a3a", 0.60), ("#e8b4bc", 0.25)], ["flowy"]),
    (10, "slip dress",     "dress",     "solid",  4, "owned",   [("#111111", 0.97)],                    ["evening"]),
    (11, "overshirt",      "outerwear", "solid",  2, "owned",   [("#5b6b3a", 0.93)],                    ["utility"]),
    (12, "denim jacket",   "outerwear", "solid",  2, "owned",   [("#6f8fb5", 0.91)],                    ["denim"]),
    (13, "sneakers",       "shoes",     "solid",  1, "owned",   [("#f5f5f3", 0.85)],                    ["everyday"]),
    (14, "boots",          "shoes",     "solid",  3, "owned",   [("#5a3a24", 0.92)],                    ["leather"]),
    (15, "wool coat",      "outerwear", "solid",  4, "catalog", [("#c19a6b", 0.96)],                    ["tailored"]),
    (16, "cargo pants",    "bottom",    "solid",  2, "catalog", [("#4b5a3c", 0.95)],                    ["utility"]),
    (17, "knit top",       "top",       "solid",  3, "catalog", [("#e7a5b8", 0.94)],                    ["soft"]),
    (18, "wide trousers",  "bottom",    "solid",  4, "catalog", [("#ece4d6", 0.96)],                    ["tailored"]),
    (19, "sneakers",       "shoes",     "solid",  2, "catalog", [("#7a1f2b", 0.88)],                    ["statement"]),
]

GUEST_COAT = (20, "rain jacket", "outerwear", "solid", 2, "owned", [("#e5b53a", 0.9)], ["guest"])


def garment(row, *, source="flatlay", is_guest=False, photo=None, status="ready"):
    n, sub, cat, pat, form, own, cols, tags = row
    colors = [color(h, w) for h, w in cols]
    return {
        "id": oid(1, n), "user_id": USER, "photo_id": photo or oid(5, n), "source": source,
        "ownership": own, "status": status, "is_guest": is_guest,
        "cutout_url": f"/media/cutouts/{oid(1, n)}.png",
        "bbox": {"x": 40, "y": 60, "w": 900, "h": 940},
        "colors": colors, "is_neutral": colors[0]["lch"][1] < NEUTRAL_CHROMA_MAX,
        "category": cat, "subcategory": sub, "pattern": pat, "formality": form,
        "style_tags": tags, "user_edited": False, "created_at": TS,
    }


def outfit(n, anchor, items, rank, score, bd, reason, src="llm", garments_by_id=None):
    needs = [i for i in items if garments_by_id[i]["ownership"] == "catalog"]
    return {
        "id": oid(3, n), "user_id": USER, "anchor_id": anchor, "item_ids": items,
        "needs_purchase": needs, "rank": rank, "rule_score": score,
        "breakdown": dict(zip(("hue", "pattern", "formality"), bd)),
        "reason": reason, "reason_source": src,
        "model": "gemini-flash" if src == "llm" else None, "created_at": TS,
    }


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def main():
    garments = [garment(r) for r in GARMENTS]
    by_id = {g["id"]: g for g in garments}
    G = lambda n: oid(1, n)  # noqa: E731

    avatar = {"id": oid(2, 1), "user_id": USER, "head_url": f"/media/heads/{oid(2, 1)}.png",
              "head_source": "generated", "is_guest": False, "created_at": TS}
    anchor = G(2)  # the flannel shirt
    outfits = [
        outfit(1, anchor, [G(2), G(6), G(13)], 1, 0.86, (0.88, 0.9, 0.8),
               "Black jeans and white sneakers let the red plaid lead; the navy in the check ties it together.",
               garments_by_id=by_id),
        outfit(2, anchor, [G(2), G(7), G(14), G(11)], 2, 0.79, (0.8, 0.9, 0.7),
               "Warm red against blue denim is a near-complement; olive and brown keep it earthy.",
               garments_by_id=by_id),
        outfit(3, anchor, [G(2), G(18), G(13)], 3, 0.74, (0.82, 0.9, 0.55),
               "Cream wide trousers soften the plaid; you'd need to buy them.",
               src="template", garments_by_id=by_id),
    ]
    render = {"id": oid(4, 1), "avatar_id": avatar["id"], "outfit_id": outfits[0]["id"],
              "image_url": f"/media/renders/{oid(4, 1)}.png", "created_at": TS}
    template = {
        "version": "placeholder-1", "image": "placeholder", "width": 600, "height": 1200,
        "head_slot": {"x": 225, "y": 40, "w": 150, "h": 170},
        "anchors": {
            "top":       {"x": 150, "y": 220, "w": 300, "h": 330},
            "outerwear": {"x": 120, "y": 210, "w": 360, "h": 420},
            "bottom":    {"x": 175, "y": 520, "w": 250, "h": 480},
            "dress":     {"x": 150, "y": 220, "w": 300, "h": 620},
        },
        "shoes_area": {"x": 180, "y": 1040, "w": 240, "h": 120},
        "arms_overlay": None,
        "layer_order": ["bottom", "dress", "top", "outerwear", "arms"],
    }

    guest = garment(GUEST_COAT, source="scan", is_guest=True, photo=oid(5, 100))
    guest["bbox"] = {"x": 210, "y": 330, "w": 560, "h": 610}
    candidates = [
        {"candidate_id": "c1", "segment_class": "coat",
         "cutout_url": f"/media/candidates/{oid(5, 100)}_c1.png", "bbox": guest["bbox"]},
        {"candidate_id": "c2", "segment_class": "upper_clothes",
         "cutout_url": f"/media/candidates/{oid(5, 100)}_c2.png", "bbox": {"x": 380, "y": 360, "w": 220, "h": 420}},
    ]
    patched = dict(garments[4], category="outerwear", user_edited=True)
    swapped = dict(outfits[0], id=oid(3, 4), item_ids=[G(2), G(8), G(13)], rank=1, rule_score=0.81,
                   breakdown={"hue": 0.82, "pattern": 0.9, "formality": 0.7},
                   reason="Beige chinos warm up the red plaid and keep the look smart casual.")

    api = {
        "get_health":            (None, {"status": "ok", "contract_version": S.CONTRACT_VERSION}),
        "post_avatar":           ({"_multipart": {"image": "<face.jpg>", "is_guest": "true"}}, {"avatar": avatar}),
        "post_ingest":           ({"_multipart": {"image": "<waist-up.jpg>", "source": "scan",
                                                  "ownership": "owned", "is_guest": "true"}},
                                  {"photo_id": oid(5, 100), "source": "scan", "candidates": candidates}),
        "post_ingest_select":    ({"candidate_ids": ["c1"]}, {"garments": [guest]}),
        "get_garments":          (None, {"garments": garments + [guest]}),
        "patch_garments":        ({"category": "outerwear"}, patched),
        "delete_garments":       (None, None),
        "post_recommend":        ({"anchor_id": anchor, "limit": 3, "offset": 0, "include_catalog": True},
                                  {"anchor_id": anchor, "outfits": outfits, "total_candidates": 41, "cache_hit": True}),
        "post_recommend_swap":   ({"outfit_id": outfits[0]["id"], "replace_item_id": G(6)}, {"outfit": swapped}),
        "post_render":           ({"avatar_id": avatar["id"], "outfit_id": outfits[0]["id"]}, {"render": render}),
        "post_demo_reset":       (None, {"deleted": {"avatars": 1, "garments": 1, "outfits": 3, "renders": 1}}),
    }
    errors = [
        {"error": {"code": "no_face_detected", "message": "No face found in the capture. Center your face in the outline."}},
        {"error": {"code": "no_garments_found", "message": "No garments detected. Step back so your top is in frame."}},
        {"error": {"code": "not_found", "message": "Garment 100000000000000000000999 does not exist."}},
    ]

    write(FIX / "garments.json", garments)
    write(FIX / "avatar.json", avatar)
    write(FIX / "outfits.json", outfits)
    write(FIX / "render.json", render)
    write(ROOT / "template_body.json", template)
    for name, (req, resp) in api.items():
        if req is not None:
            write(API / f"{name}.request.json", req)
        if resp is not None:
            write(API / f"{name}.response.json", resp)
    write(API / "errors.json", errors)

    from pydantic.json_schema import models_json_schema
    models = [S.Garment, S.Avatar, S.Outfit, S.Render, S.TemplateBody, S.ErrorResponse,
              S.HealthResponse, S.AvatarCreateResponse, S.IngestResponse, S.SelectRequest,
              S.SelectResponse, S.GarmentListResponse, S.GarmentPatch, S.RecommendRequest,
              S.RecommendResponse, S.SwapRequest, S.SwapResponse, S.RenderRequest,
              S.RenderResponse, S.DemoResetResponse]
    _, schema = models_json_schema([(m, "serialization") for m in models],
                                   title=f"Closet app contract {S.CONTRACT_VERSION}")
    write(ROOT / "schema.json", schema)
    print(f"wrote {len(garments)} garments, 3 outfits, {len(api)} endpoint examples, template_body.json, schema.json")


if __name__ == "__main__":
    main()
