#!/usr/bin/env python3
"""Validate a JSON response against the contract.

    python tools/validate_response.py <items|outfits|avatar> <file.json>
    python tools/validate_response.py <items|outfits|avatar> -        # read stdin

Passes if the JSON validates against any response model of that lane's endpoints.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contract import schemas as S  # noqa: E402

LANE_PREFIXES = {"items": ("/items",), "outfits": ("/outfits",), "avatar": ("/avatar", "/render")}


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in LANE_PREFIXES:
        print(__doc__)
        return 2
    lane, src = sys.argv[1], sys.argv[2]
    data = json.load(sys.stdin if src == "-" else open(src, encoding="utf-8"))
    models = {m for _, path, _, m in S.ENDPOINTS if m is not None and path.startswith(LANE_PREFIXES[lane])}
    errors = {}
    for model in models:
        try:
            model.model_validate(data)
            print(f"OK   valid {model.__name__}")
            return 0
        except Exception as e:  # pydantic.ValidationError
            errors[model.__name__] = str(e).splitlines()[:4]
    print(f"FAIL matches none of: {', '.join(sorted(errors))}")
    for name, lines in errors.items():
        print(f"  {name}:")
        for ln in lines:
            print(f"    {ln}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
