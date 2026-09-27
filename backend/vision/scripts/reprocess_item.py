"""V6.1 isolation (re-dispatch): re-run V1-V4 for ONE existing item under its EXISTING slug, after
a segmentation/isolation fix, without reseeding or touching any other item.

Does NOT allocate a new slug and does NOT touch retailer_color/retailer_item_name/created_at --
only the fields the pipeline actually recomputes: primary_color, secondary_color, anchors, and
the cutout PNG at media/items/<slug>.png (both on local disk and in GridFS via
backend.media_store.persist -- see that module's docstring for why both are required).

The item's category/garment_type are read from its EXISTING DB document (never re-guessed from
the filename), so this always reprocesses under the same garment_type the item was originally
saved with.

    .venv/Scripts/python.exe backend/vision/scripts/reprocess_item.py <slug> "<fixture file path>"

Picks the candidate passing the most automated checks (backend/vision/checks.py), same rule as
backend/vision/scripts/seed_closet.py's best_candidate_index, falling back to the "balanced"
candidate (index 1) on a tie.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from contract.enums import Category, GarmentType  # noqa: E402
from backend import config, media_store  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.vision.ingest import build_candidates  # noqa: E402
from PIL import Image  # noqa: E402


def best_candidate_index(candidates: list[dict]) -> int:
    """Mirrors seed_closet.best_candidate_index, but reading checks directly off the freshly
    built candidates (no analyze session involved here -- this script never goes through the
    HTTP /analyze endpoint)."""
    scored = [
        (sum(1 for v in c["checks"].values() if isinstance(v, bool) and v), i)
        for i, c in enumerate(candidates)
    ]
    best_score = max(s for s, _ in scored)
    tied = [i for s, i in scored if s == best_score]
    return 1 if 1 in tied else min(tied)


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <slug> <fixture file path>")
        raise SystemExit(2)

    slug, fixture_path = sys.argv[1], Path(sys.argv[2])
    if not fixture_path.is_absolute():
        fixture_path = REPO_ROOT / fixture_path
    if not fixture_path.exists():
        print(f"fixture file not found: {fixture_path}")
        raise SystemExit(1)

    items = get_db()["items"]
    doc = items.find_one({"id": slug})
    if doc is None:
        print(f"no item with id {slug!r} in the DB -- nothing reprocessed.")
        raise SystemExit(1)

    category = Category(doc["category"])
    garment_type = GarmentType(doc["garment_type"])
    print(f"reprocessing {slug} ({doc.get('retailer_item_name')!r}) as "
          f"category={category.value} garment_type={garment_type.value} from {fixture_path.name}")

    candidates, multi_person, category_mismatch = build_candidates(
        fixture_path.read_bytes(), category, garment_type,
    )
    idx = best_candidate_index(candidates)
    chosen = candidates[idx]
    print(f"chosen candidate: index={idx} variant={chosen['variant'].value} "
          f"checks_passed={sum(1 for v in chosen['checks'].values() if v is True)}/"
          f"{sum(1 for v in chosen['checks'].values() if isinstance(v, bool))} "
          f"multi_person={multi_person} category_mismatch={category_mismatch}")

    dest_path = config.MEDIA_DIR / "items" / f"{slug}.png"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(chosen["rgba"], mode="RGBA").save(dest_path)
    media_store.persist(dest_path)

    items.update_one(
        {"id": slug},
        {"$set": {
            "primary_color": chosen["primary_color"],
            "secondary_color": chosen["secondary_color"],
            "anchors": chosen["anchors"],
        }},
    )
    print(f"overwrote {dest_path} and updated {slug}'s primary_color/secondary_color/anchors.")
    print(f"primary_color={chosen['primary_color']} secondary_color={chosen['secondary_color']}")


if __name__ == "__main__":
    main()
