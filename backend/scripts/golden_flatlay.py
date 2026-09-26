"""Golden check for the flat-lay pipeline.

For every flat-lay seed photo in fixtures/flatten/ (one garment laid flat on a plain sheet),
the hand-labelled hex is the last `#rrggbb` in the filename. A photo passes when the labelled
color's family (contract/colors.json, nearest center by CIEDE2000) matches the family of any
extracted color. Human decision (2026-09-26): on two-tone garments the label names the pattern
color (green stripes on cream), which the contract stores after the larger neutral base.
Pass overall at >= 80% of photos.

Run from backend/:  python scripts/golden_flatlay.py [photo_dir]
Needs the rembg model (downloaded on first run).
"""
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path[:0] = [str(BACKEND), str(ROOT)]

import numpy as np  # noqa: E402
from skimage.color import deltaE_ciede2000, rgb2lab  # noqa: E402

from app.pipeline import PipelineError  # noqa: E402
from app.pipeline.bgremove import cutout  # noqa: E402
from app.pipeline.color import extract_colors  # noqa: E402
from app.pipeline.preprocess import preprocess  # noqa: E402

PASS_RATE = 0.80
IMAGES = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "fixtures" / "flatten"
PALETTE = json.loads((ROOT / "contract" / "colors.json").read_text())
MAX_DE = PALETTE["_meta"]["max_assignment_delta_e"]
CENTERS = [(c["name"], c["family"], np.array(c["lab"], float)) for c in PALETTE["colors"]]


def hex_to_lab(hex_: str) -> np.ndarray:
    rgb = np.array([int(hex_[i:i + 2], 16) for i in (1, 3, 5)], float) / 255
    return rgb2lab(rgb.reshape(1, 1, 3)).reshape(3)


def name_family(lab) -> tuple[str, str]:
    d, name, fam = min((float(deltaE_ciede2000(lab, c)), n, f) for n, f, c in CENTERS)
    return (name, fam) if d <= MAX_DE else ("unmapped", "unmapped")


def main() -> int:
    if not IMAGES.is_dir():
        print(f"No photo folder at {IMAGES}. Add flat-lay photos named '<anything> #rrggbb.jpg'.")
        return 1
    photos = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    hits = total = 0
    for p in photos:
        m = re.findall(r"#([0-9a-fA-F]{6})", p.stem)
        if not m:
            print(f"SKIP  {p.name} (no #hex label)")
            continue
        total += 1
        want_name, want_fam = name_family(hex_to_lab("#" + m[-1].lower()))
        try:
            colors, neutral = extract_colors(cutout(preprocess(p)).rgba)
        except PipelineError as e:
            print(f"FAIL  {p.name[:48]:48} error={e.code.value}")
            continue
        got = [(name_family(np.array(c["lab"])), c) for c in colors]
        match = next(((nf, c) for nf, c in got if nf[1] == want_fam), None)
        ok = match is not None
        hits += ok
        (got_name, got_fam), c = match or got[0]
        print(f"{'ok  ' if ok else 'MISS'}  {p.name[:48]:48} want {want_fam}/{want_name:10} "
              f"got {got_fam}/{got_name:10} {c['hex']} w={c['weight']:.2f}")
    rate = hits / total if total else 0.0
    print(f"\nfamily match {hits}/{total} = {rate:.0%} (need {PASS_RATE:.0%})")
    return 0 if total and rate >= PASS_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
