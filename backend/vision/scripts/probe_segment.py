"""Debug probe: run V1+V2 on a fixture image and print mask stats. Not imported anywhere.

    .venv/Scripts/python.exe backend/vision/scripts/probe_segment.py "<fixture filename>" <garment_type>
"""
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from contract.enums import GarmentType  # noqa: E402
from backend.vision.preprocess import load_and_normalize  # noqa: E402
from backend.vision.segmentation import segment  # noqa: E402


def main():
    fname = sys.argv[1] if len(sys.argv) > 1 else "brown Mock Neck Cardigan Sweater #60859b.png"
    gtype = GarmentType(sys.argv[2]) if len(sys.argv) > 2 else GarmentType.shirt
    path = REPO_ROOT / "fixtures" / "images" / fname
    data = path.read_bytes()
    t0 = time.time()
    rgb = load_and_normalize(data)
    t1 = time.time()
    result = segment(rgb, gtype)
    t2 = time.time()
    print(f"image {rgb.shape} preprocess={t1 - t0:.2f}s segment={t2 - t1:.2f}s multi_person={result.multi_person}")
    print("region_box_px", result.region_box_px)
    masks = list(result.variants.items())
    for name, m in masks:
        print(f"  {name:9} coverage={m.mean():.1%} area_px={m.sum()}")
    for i in range(len(masks)):
        for j in range(i + 1, len(masks)):
            (n1, m1), (n2, m2) = masks[i], masks[j]
            inter = (m1 & m2).sum()
            union = (m1 | m2).sum()
            iou = inter / union if union else 1.0
            print(f"  IoU {n1}/{n2} = {iou:.3f}")


if __name__ == "__main__":
    main()
