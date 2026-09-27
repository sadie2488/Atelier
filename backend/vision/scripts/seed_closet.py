"""D4: seed the real closet DB from fixtures/images/ through the real HTTP endpoints (no
dependency override -- this writes to the real MongoDB from backend/.env and real media under
media/items/). Idempotent: a photo whose inferred item_name already exists as a
retailer_item_name is skipped.

    .venv/Scripts/python.exe backend/vision/scripts/seed_closet.py [--dry-run] [--reset]

--dry-run   POST /analyze only; nothing is saved (the temp session is rejected to clean up).
--reset     delete only items whose retailer_item_name matches a fixture stem (and their
            media/items/<slug>.png), then reseed normally. Never touches anything else.
"""
import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from contract.enums import Category, GarmentType  # noqa: E402
from backend import config  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.vision.session import load_session  # noqa: E402

IMAGES_DIR = REPO_ROOT / "fixtures" / "images"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
HEX_SUFFIX_RE = re.compile(r"\s*#[0-9a-fA-F]{6}\s*$")
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def item_name_for(path: Path) -> str:
    """Filename stem with the trailing '#hex' (and any leading space) removed."""
    stem = path.stem
    return HEX_SUFFIX_RE.sub("", stem).strip()


def infer_category_garment(fname: str) -> tuple[Category, GarmentType]:
    """Priority order: dress is checked before jean/short so that "short sleeve ... dress" /
    "short-sleev midi dress" filenames (real fixtures) classify as dresses, not shorts."""
    low = fname.lower()
    if "dress" in low:
        return Category.tops, GarmentType.dress
    if "jean" in low or "pant" in low:
        return Category.bottoms, GarmentType.pants
    if "skirt" in low:
        return Category.bottoms, GarmentType.skirt
    if "short" in low:
        return Category.bottoms, GarmentType.shorts
    if "jacket" in low or "blazer" in low:
        return Category.jackets, GarmentType.jacket
    if "coat" in low:
        return Category.jackets, GarmentType.coat
    return Category.tops, GarmentType.shirt  # cardigan/sweater/top/polo/cami/tee/shirt


def best_candidate_index(temp_handle: str, api_candidates: list[dict]) -> int:
    """Pick the candidate passing the most automated checks (backend/vision/checks.py), read
    from the analyze session (checks aren't in the API response). Falls back to index 1
    ("balanced") if the session can't be reached, or on a tie."""
    session = load_session(temp_handle)
    if session is None:
        return 1
    scored = []
    for c in session["candidates"]:
        checks = c.get("checks", {})
        score = sum(1 for v in checks.values() if isinstance(v, bool) and v)
        scored.append((score, c["index"]))
    if not scored:
        return 1
    best_score = max(s for s, _ in scored)
    tied = [i for s, i in scored if s == best_score]
    return 1 if 1 in tied else min(tied)


def reset_matching(client: TestClient, files: list[Path]) -> None:
    db = get_db()
    items = db["items"]
    stems = {item_name_for(f) for f in files}
    media_dir = config.MEDIA_DIR / "items"
    removed = 0
    for name in stems:
        for doc in list(items.find({"retailer_item_name": name})):
            slug = doc["id"]
            png = media_dir / f"{slug}.png"
            if png.exists():
                png.unlink()
            items.delete_one({"id": slug})
            removed += 1
    print(f"--reset: removed {removed} existing item(s) matching fixture stems")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="analyze only, never save")
    parser.add_argument("--reset", action="store_true", help="delete matching items first, then reseed")
    args = parser.parse_args()

    files = sorted(p for p in IMAGES_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not files:
        print(f"no images found in {IMAGES_DIR}")
        return

    client = TestClient(app)

    if args.reset:
        reset_matching(client, files)

    items_coll = get_db()["items"]
    rows = []

    for path in files:
        item_name = item_name_for(path)
        category, garment_type = infer_category_garment(path.name)

        existing = items_coll.find_one({"retailer_item_name": item_name})
        if existing is not None:
            color = existing.get("primary_color", {})
            rows.append((path.name, f"skipped (exists {existing['id']})", category.value,
                         garment_type.value, f"{color.get('name', '?')} {color.get('hex', '?')}"))
            continue

        data = path.read_bytes()
        files_payload = {"image": (path.name, data, CONTENT_TYPES[path.suffix.lower()])}
        form = {"category": category.value, "garment_type": garment_type.value, "item_name": item_name}

        resp = client.post("/api/items/analyze", data=form, files=files_payload)
        if resp.status_code != 200:
            code = resp.json().get("error", {}).get("code", resp.status_code)
            rows.append((path.name, f"error {code}", category.value, garment_type.value, "-"))
            continue

        body = resp.json()
        temp_handle = body["temp_handle"]
        candidates = body["candidates"]
        idx = best_candidate_index(temp_handle, candidates)
        primary = candidates[idx]["primary_color"]

        if args.dry_run:
            client.post("/api/items/reject", json={"temp_handle": temp_handle})
            rows.append((path.name, f"analyzed (dry-run, candidate {idx})", category.value,
                         garment_type.value, f"{primary['name']} {primary['hex']}"))
            continue

        save_resp = client.post("/api/items/save", json={"temp_handle": temp_handle, "candidate_index": idx})
        if save_resp.status_code != 200:
            code = save_resp.json().get("error", {}).get("code", save_resp.status_code)
            rows.append((path.name, f"error {code}", category.value, garment_type.value, "-"))
            continue

        item = save_resp.json()
        rows.append((path.name, f"saved {item['id']}", category.value, garment_type.value,
                     f"{item['primary_color']['name']} {item['primary_color']['hex']}"))

    print()
    print(f"{'file':<62} {'result':<28} {'category':<9} {'garment_type':<8} color")
    for name, result, cat, gtype, color in rows:
        print(f"{name[:62]:<62} {result:<28} {cat:<9} {gtype:<8} {color}")


if __name__ == "__main__":
    main()
