"""V6.2 (bug (b)/(c), re-dispatch) + human-approved real-DB update: re-run V1-V4 for EVERY
existing item in the real closet DB under its EXISTING slug/category/garment_type, after the V2
bottoms-isolation fix, transparent-cutout fix, and V4 display_name addition -- without reseeding
and without allocating any new slug (see backend/vision/scripts/reprocess_item.py, which this
reuses per-item).

For each item:
  - locate its source fixture photo in fixtures/images/ by retailer_item_name (mirrors
    seed_closet.item_name_for's stem-minus-hex mapping, run in reverse);
  - rebuild the three candidates from that fixture under the item's existing category/garment_type;
  - pick the best candidate the same way seed_closet/reprocess_item do (most checks passed,
    "balanced" on a tie);
  - compare the new candidate against the CURRENTLY SAVED cutout on a common, fair subset of
    checks.py's checks (the ones computable from a final cutout PNG alone, since the old item
    has no stored mask/checks to replay): purity_corners_transparent, structural_alpha_present,
    structural_coverage_in_range (canvas-alpha-fraction proxy), structural_largest_cc_ratio,
    completeness_no_straight_run, completeness_left_right_balance;
  - REPLACE (cutout file + GridFS + primary_color/secondary_color/anchors) only if the new
    candidate's score on that shared subset is >= the old cutout's -- ties go to the new
    candidate only if its raw alpha_area_px is also not a regression (guards against "fewer
    checks fail only because there's almost nothing left to fail them on");
  - otherwise KEEP the old cutout/anchors untouched, but still add `display_name` to its
    already-stored primary_color/secondary_color (computed from their existing `lab`, never
    changing hex/lab/name/family).

    .venv/Scripts/python.exe backend/vision/scripts/reprocess_closet.py [--dry-run]

--dry-run   print the keep/replace decision and check scores for every item; write nothing.
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image  # noqa: E402

from contract.enums import Category, GarmentType  # noqa: E402
from contract.tools.color import display_name  # noqa: E402
from backend import config, media_store  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.vision.ingest import build_candidates  # noqa: E402
from backend.vision.checks import _left_right_balance_ok, _no_straight_boundary_run  # noqa: E402

IMAGES_DIR = REPO_ROOT / "fixtures" / "images"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
HEX_SUFFIX_RE = re.compile(r"\s*#[0-9a-fA-F]{6}\s*$")

# The subset of checks.py's checks that can be computed from a final cutout PNG alone (no
# pre-crop mask/skin_mask/independent_extent -- unavailable for an item that's already saved).
_SHARED_CHECK_NAMES = [
    "purity_corners_transparent", "structural_alpha_present", "structural_coverage_in_range",
    "structural_largest_cc_ratio", "completeness_no_straight_run", "completeness_left_right_balance",
]


def item_name_for(path: Path) -> str:
    stem = path.stem
    return HEX_SUFFIX_RE.sub("", stem).strip()


def _fixture_for(retailer_item_name: str) -> Path | None:
    for p in IMAGES_DIR.iterdir():
        if p.suffix.lower() in IMAGE_EXTS and item_name_for(p) == retailer_item_name:
            return p
    return None


def best_candidate_index(candidates: list[dict]) -> int:
    scored = [
        (sum(1 for v in c["checks"].values() if isinstance(v, bool) and v), i)
        for i, c in enumerate(candidates)
    ]
    best_score = max(s for s, _ in scored)
    tied = [i for s, i in scored if s == best_score]
    return 1 if 1 in tied else min(tied)


def _proxy_checks_from_cutout(rgba: np.ndarray, category: Category) -> dict:
    """Same 6 checks as `_SHARED_CHECK_NAMES`, computed straight off a final RGBA cutout (works
    for both the new candidate's array and the old saved PNG -- an apples-to-apples comparison
    neither side gets an unfair advantage on, unlike the full 10-check set which needs pre-crop
    signals only the freshly-built candidate has)."""
    alpha = rgba[..., 3]
    mask = alpha > 0
    h, w = mask.shape
    total = int(mask.sum())
    if total == 0:
        return {name: False for name in _SHARED_CHECK_NAMES}
    corners_transparent = not (alpha[0, 0] or alpha[0, w - 1] or alpha[h - 1, 0] or alpha[h - 1, w - 1])
    labeled, n = ndimage.label(mask)
    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    largest_cc = int(counts.max()) if n else 0
    coverage = total / (h * w)
    return {
        "purity_corners_transparent": bool(corners_transparent),
        "structural_alpha_present": bool(mask.any() and not mask.all()),
        "structural_coverage_in_range": 0.08 <= coverage <= 0.70,
        "structural_largest_cc_ratio": (largest_cc / total) >= 0.90,
        "completeness_no_straight_run": _no_straight_boundary_run(mask),
        "completeness_left_right_balance": _left_right_balance_ok(mask, category),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = get_db()["items"]
    docs = list(items.find({}))
    print(f"{len(docs)} items in the DB\n")

    rows = []
    for doc in docs:
        slug = doc["id"]
        name = doc.get("retailer_item_name")
        fixture = _fixture_for(name) if name else None
        if fixture is None:
            rows.append((slug, name, "SKIPPED (no matching fixture file)"))
            continue

        category = Category(doc["category"])
        garment_type = GarmentType(doc["garment_type"])
        candidates, multi_person, mismatch = build_candidates(fixture.read_bytes(), category, garment_type)
        idx = best_candidate_index(candidates)
        new = candidates[idx]
        new_rgba = new["rgba"]
        new_proxy = _proxy_checks_from_cutout(new_rgba, category)
        new_score = sum(new_proxy.values())
        new_alpha_px = int((new_rgba[..., 3] > 0).sum())

        old_path = config.MEDIA_DIR / "items" / f"{slug}.png"
        old_rgba = np.asarray(Image.open(old_path).convert("RGBA")) if old_path.exists() else None
        if old_rgba is not None:
            old_proxy = _proxy_checks_from_cutout(old_rgba, category)
            old_score = sum(old_proxy.values())
            old_alpha_px = int((old_rgba[..., 3] > 0).sum())
        else:
            old_proxy, old_score, old_alpha_px = {}, -1, 0

        replace = old_rgba is None or (new_score >= old_score and new_alpha_px >= 0.5 * old_alpha_px)

        primary = dict(new["primary_color"])
        secondary = dict(new["secondary_color"]) if new["secondary_color"] else None

        if replace:
            action = f"REPLACED (new {new_score}/6 vs old {old_score}/6, alpha {old_alpha_px}->{new_alpha_px}px)"
            if not args.dry_run:
                old_path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(new_rgba, mode="RGBA").save(old_path)
                media_store.persist(old_path)
                items.update_one({"id": slug}, {"$set": {
                    "primary_color": primary, "secondary_color": secondary, "anchors": new["anchors"],
                }})
        else:
            # V4 (bug (c)): keep the old cutout/color untouched, but still backfill display_name
            # from the ALREADY-STORED lab -- never recompute/replace hex/lab/name/family.
            action = f"kept old (new {new_score}/6 vs old {old_score}/6, alpha {old_alpha_px}->{new_alpha_px}px)"
            if not args.dry_run:
                old_primary = dict(doc["primary_color"])
                old_primary["display_name"] = display_name(tuple(old_primary["lab"]))
                update = {"primary_color": old_primary}
                if doc.get("secondary_color"):
                    old_secondary = dict(doc["secondary_color"])
                    old_secondary["display_name"] = display_name(tuple(old_secondary["lab"]))
                    update["secondary_color"] = old_secondary
                items.update_one({"id": slug}, {"$set": update})

        rows.append((slug, name, action))

    print(f"{'slug':<14} {'retailer_item_name':<55} action")
    for slug, name, action in rows:
        print(f"{slug:<14} {str(name)[:55]:<55} {action}")


if __name__ == "__main__":
    main()
