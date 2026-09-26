"""Debug probe: run V1-V4 over every fixtures/images/*.png and report candidate-check pass
rates, primary-color family agreement against the filename's true hex, and analyze latency.
Not imported anywhere; not a test (no assertions, no fixtures/golden dependency -- V-Q4 golden
references don't exist yet).

    .venv/Scripts/python.exe backend/vision/scripts/eval_fixtures.py
"""
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from contract.enums import GarmentType  # noqa: E402
from contract.tools.color import nearest_color  # noqa: E402
from backend.vision.ingest import build_candidates  # noqa: E402

HEX_RE = re.compile(r"#([0-9a-fA-F]{6})")


def infer_garment_type(fname: str) -> GarmentType:
    low = fname.lower()
    if "dress" in low:
        return GarmentType.dress
    if "jean" in low:
        return GarmentType.pants
    if "skirt" in low:
        return GarmentType.skirt
    if "short" in low:
        return GarmentType.shorts
    return GarmentType.shirt   # cardigan/sweater/top/polo/cami/etc.


def main():
    images_dir = REPO_ROOT / "fixtures" / "images"
    files = sorted(images_dir.glob("*.png"))
    latencies = []
    agree, total_scored = 0, 0
    check_totals: dict[str, list[bool]] = {}
    failures = []

    # one discarded warmup run (V-Q6), to exclude cold MediaPipe init from latency numbers
    if files:
        try:
            build_candidates(files[0].read_bytes(), infer_garment_type(files[0].name))
        except Exception:
            pass

    for f in files:
        matches = HEX_RE.findall(f.name)
        true_hex = "#" + matches[-1].lower() if matches else None
        gtype = infer_garment_type(f.name)
        data = f.read_bytes()
        t0 = time.time()
        try:
            candidates, multi_person = build_candidates(data, gtype)
        except Exception as e:
            failures.append((f.name, str(e)))
            continue
        dt = time.time() - t0
        latencies.append(dt)

        balanced = candidates[1]
        for name, ok in balanced["checks"].items():
            if isinstance(ok, bool):
                check_totals.setdefault(name, []).append(ok)

        if true_hex:
            from contract.tools.color import hex_to_lab
            true_family = nearest_color(hex_to_lab(true_hex))[1]
            got_family = balanced["primary_color"]["family"]
            total_scored += 1
            match = true_family == got_family
            agree += int(match)
            print(f"{'OK  ' if match else 'MISS'} {f.name[:60]:60} true={true_family:12} "
                  f"got={got_family:12} hex={balanced['primary_color']['hex']} dt={dt:.2f}s")

    print()
    print(f"analyzed {len(latencies)}/{len(files)} images, {len(failures)} raised")
    for name, msg in failures:
        print(f"  FAILED {name}: {msg}")
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        print(f"latency p50={p50:.2f}s p95={p95:.2f}s max={max(latencies):.2f}s")
    if total_scored:
        print(f"color family agreement: {agree}/{total_scored} = {agree / total_scored:.0%}")
    print("check pass rates (balanced candidate):")
    for name, results in check_totals.items():
        print(f"  {name:32} {sum(results)}/{len(results)}")


if __name__ == "__main__":
    main()
