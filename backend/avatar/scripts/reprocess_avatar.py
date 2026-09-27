"""A3 change (human decision 2026-09-26): rebuild ONE existing avatar's images and DB-only
geometry with the new real-body-cutout code, in place -- the avatar_id and every contract field
value (avatar_url, wireframe_url) stay exactly the same; only the file CONTENTS at those same
media keys change (overwritten locally and re-persisted to GridFS via backend.avatar.media).

Also regenerates the local composite (local_url) of every existing `renders` doc that belongs to
this avatar, in place -- same local_url key, freshly composited against the new avatar image and
rig. `status` and `generated_url` are never touched: the cached Gemini image stays valid (it was
generated from the unchanged source photo, not from the avatar image).

The renders collection does not store which (avatar_id, top_id, bottom_id, jacket_id) a render_id
came from -- render_id is a one-way hash of that tuple (backend/avatar/ids.py). With a catalog
this small, this script just re-derives every plausible combination for THIS avatar_id from the
`items` collection and checks which hashes already exist in `renders` -- a handful of hashes, not
a search of the DB.

    .venv/Scripts/python.exe backend/avatar/scripts/reprocess_avatar.py <avatar_id>
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from backend.db import get_db  # noqa: E402
from backend.avatar import compositing, ids, media  # noqa: E402
from backend.avatar.landmarks import detect_landmarks  # noqa: E402
from backend.avatar.rig import rig_from_dict, rig_to_dict  # noqa: E402
from backend.avatar.service import _load_item_layer, build_avatar_visuals  # noqa: E402

TOP_SLOT_TYPES = ("shirt", "dress")
BOTTOM_SLOT_TYPES = ("pants", "shorts", "skirt")
JACKET_SLOT_TYPES = ("jacket", "coat")


def _find_avatars_renders(db, avatar_id: str) -> dict[str, dict]:
    """-> {render_id: render_doc} for every EXISTING render doc that is this avatar's, found by
    re-deriving render_id for every (top, bottom, jacket-or-none) combination in the catalog and
    keeping only the ones that already exist in `renders`."""
    items = list(db["items"].find({}))
    top_ids = [i["id"] for i in items if i.get("garment_type") in TOP_SLOT_TYPES]
    bottom_ids = [i["id"] for i in items if i.get("garment_type") in BOTTOM_SLOT_TYPES]
    jacket_ids = [None] + [i["id"] for i in items if i.get("garment_type") in JACKET_SLOT_TYPES]

    found = {}
    for top_id in top_ids:
        for bottom_id in bottom_ids:
            for jacket_id in jacket_ids:
                rid = ids.render_id_for(avatar_id, top_id, bottom_id, jacket_id)
                doc = db["renders"].find_one({"render_id": rid})
                if doc is not None:
                    found[rid] = {"top_id": top_id, "bottom_id": bottom_id, "jacket_id": jacket_id}
    return found


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <avatar_id>")
        raise SystemExit(2)
    avatar_id = sys.argv[1]

    db = get_db()
    avatars = db["avatars"]
    renders = db["renders"]
    items = db["items"]

    doc = avatars.find_one({"avatar_id": avatar_id})
    if doc is None:
        print(f"no avatar with id {avatar_id!r} in the DB -- nothing reprocessed.")
        raise SystemExit(1)

    rgb = np.asarray(media.load_media(doc["source_photo_url"]).convert("RGB"))
    landmarks = detect_landmarks(rgb)
    if landmarks is None:
        print(f"{avatar_id}: no landmarks detected on its own stored source photo -- aborting "
              f"(this would have failed the original scan too).")
        raise SystemExit(1)

    visuals = build_avatar_visuals(rgb, landmarks)

    wireframe_url = media.save_png(visuals["wireframe_img"], "avatars", f"{avatar_id}_wireframe.png")
    avatar_url = media.save_png(visuals["avatar_img"], "avatars", f"{avatar_id}.png")
    assert wireframe_url == doc["wireframe_url"] and avatar_url == doc["avatar_url"], (
        "reprocessing must overwrite the SAME media keys, not allocate new ones"
    )

    avatars.update_one({"avatar_id": avatar_id}, {"$set": {
        "rig": rig_to_dict(visuals["rig_local"]),
        "canvas_w": visuals["canvas_w"],
        "canvas_h": visuals["canvas_h"],
        "avatar_kind": visuals["avatar_kind"],
    }})
    print(f"{avatar_id}: avatar_kind={visuals['avatar_kind']} "
          f"canvas={visuals['canvas_w']}x{visuals['canvas_h']} -- avatar_url/wireframe_url overwritten in place.")

    rig_local = visuals["rig_local"]
    canvas_size = (visuals["canvas_w"], visuals["canvas_h"])
    avatar_img = visuals["avatar_img"]

    combos = _find_avatars_renders(db, avatar_id)
    refreshed = 0
    for rid, combo in combos.items():
        top_doc = items.find_one({"id": combo["top_id"]})
        bottom_doc = items.find_one({"id": combo["bottom_id"]})
        jacket_doc = items.find_one({"id": combo["jacket_id"]}) if combo["jacket_id"] else None

        composed = compositing.composite_outfit(
            avatar_img, canvas_size, rig_local,
            bottom=_load_item_layer(bottom_doc), top=_load_item_layer(top_doc),
            jacket=_load_item_layer(jacket_doc) if jacket_doc is not None else None,
        )
        local_url = media.save_png(composed, "renders", f"{rid}_local.png")
        renders.update_one({"render_id": rid}, {"$set": {"local_url": local_url}})  # status/generated_url untouched
        refreshed += 1

    print(f"{avatar_id}: {refreshed} render(s) had their local composite regenerated in place "
          f"(status/generated_url left untouched).")


if __name__ == "__main__":
    main()
