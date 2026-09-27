"""Read-only check: generate outfits from the real items 5 times (with and without the guide
term) and print guide pair labels, then the palette insight sentences."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.db import get_db
from backend.routes.outfits import _to_item
from backend.styling import pairing_guide as PG
from backend.styling import select as S
from backend.styling import strategies as ST
from backend.styling.explain import guided_fallback
from backend.styling.insights import compute_insights

items = [_to_item(d).model_dump() for d in get_db()["items"].find({})]
by = {c: [i for i in items if i["category"] == c] for c in ("tops", "bottoms", "jackets")}
print(f"{len(items)} items")
for i in items:
    print(f"  {i['id']:14} {i['garment_type'].value if hasattr(i['garment_type'],'value') else i['garment_type']:7} {i['primary_color']['name']:14} -> {PG.item_guide_color(i)}")


def run(label):
    cands = [
        {"strategy": s, "top": t, "bottom": b, "jacket": j, "top_id": t["id"], "bottom_id": b["id"],
         "jacket_id": j["id"] if j else None, "score": max(0.0, min(1.0, sc))}
        for s, t, b, j, sc in ST.generate_candidates(by["tops"], by["bottoms"], by["jackets"])
    ]
    print(f"\n=== {label}: {len(cands)} candidates")
    for seed in range(5):
        chosen = S.select_outfits(cands, 5, rng=random.Random(seed))
        print(f"-- run {seed + 1}")
        for c in chosen:
            q = PG.item_pair_quality(c["top"], c["bottom"])
            names = f"{PG.item_guide_color(c['top'])} + {PG.item_guide_color(c['bottom'])}"
            if c["jacket"]:
                names += f" + {PG.item_guide_color(c['jacket'])} jacket"
            print(f"   {c['score']:.3f} {c['strategy'].value:22} {c['top_id']}/{c['bottom_id']}/{c['jacket_id']}  {names}  [{q}]")
            if label == "after" and seed == 0:
                print("        " + guided_fallback(c["strategy"], c["top"], c["bottom"], c["jacket"]))


orig = ST.pair_adjustment
ST.pair_adjustment = lambda a, b: 0.0
run("before")
ST.pair_adjustment = orig
run("after")

print("\n=== insights")
for s in compute_insights(items)["insights"]:
    print("  " + s)
