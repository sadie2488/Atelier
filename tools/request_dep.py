#!/usr/bin/env python3
"""Lanes request a dependency here instead of editing requirements.txt. The PM installs it.

    python tools/request_dep.py <package> --lane <vision|styling|avatar> --reason "<why>"
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "contract" / "DEP_REQUESTS.jsonl"

p = argparse.ArgumentParser()
p.add_argument("package")
p.add_argument("--lane", required=True, choices=["vision", "styling", "avatar"])
p.add_argument("--reason", required=True)
a = p.parse_args()
entry = {"package": a.package, "lane": a.lane, "reason": a.reason,
         "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "requested"}
with LOG.open("a", encoding="utf-8") as f:
    f.write(json.dumps(entry) + "\n")
print(f"Requested {a.package} for {a.lane}. Continue with what is installed; the PM will install it.")
