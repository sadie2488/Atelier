#!/usr/bin/env python3
"""Every media URL in a response is relative (/media/...) and resolves to a file.

    python tools/check_media.py <response.json> [more.json ...]
    python tools/check_media.py -                                  # read stdin

Exit 0 = all good, 1 = an absolute URL or a missing file.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402


def strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)
    elif isinstance(node, str):
        yield node


def main() -> int:
    srcs = sys.argv[1:]
    if not srcs:
        print(__doc__)
        return 2
    bad = checked = 0
    for src in srcs:
        data = json.load(sys.stdin if src == "-" else open(src, encoding="utf-8"))
        for s in strings(data):
            if "/media/" not in s:
                continue
            checked += 1
            if not s.startswith("/media/"):
                print(f"ABSOLUTE  {s}")
                bad += 1
            elif not (config.MEDIA_DIR / s[len("/media/"):]).is_file():
                print(f"MISSING   {s}  (looked in {config.MEDIA_DIR})")
                bad += 1
    print(f"{checked} media URL(s) checked, {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
