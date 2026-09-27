#!/usr/bin/env python3
"""Upload durable local media (items, avatars, renders) to MongoDB so every machine and deploy
serves the same /media files. Safe to re-run: existing keys are skipped unless --force.

    python tools/sync_media.py            # upload what's missing
    python tools/sync_media.py --force    # re-upload everything
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import config, media_store  # noqa: E402

DURABLE_DIRS = ("items", "avatars", "renders")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    uploaded = skipped = 0
    for d in DURABLE_DIRS:
        for path in sorted((config.MEDIA_DIR / d).glob("*")):
            if not path.is_file():
                continue
            key = media_store.key_for(path)
            if not args.force and media_store.get(key) is not None:
                skipped += 1
                continue
            media_store.persist(path)
            uploaded += 1
            print(f"uploaded {key}")
    print(f"{uploaded} uploaded, {skipped} already stored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
