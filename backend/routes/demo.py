"""Secret demo reset (auxiliary, outside the frozen contract, like /api/phone).

POST /api/demo/reset?key=<RESET_KEY> puts the closet back to the demo default listed in
backend/demo_baseline.json: every item not in the baseline is moved to `items_archive`, and every
baseline item that was archived is moved back. Nothing is deleted, so it is reversible. Avatars,
renders and media are left alone.
"""
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["demo"], include_in_schema=False)

BASELINE_FILE = Path(__file__).resolve().parents[1] / "demo_baseline.json"
RESET_KEY = os.environ.get("ATELIER_RESET_KEY", "atelier-demo-reset")


def _baseline_ids() -> set[str]:
    return set(json.loads(BASELINE_FILE.read_text(encoding="utf-8"))["items"])


@router.post("/demo/reset")
def reset_demo(key: str = "", db=Depends(get_db)):
    if key != RESET_KEY:
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Not found."}})
    baseline = _baseline_ids()
    items, archive = db["items"], db["items_archive"]
    archived, restored = [], []
    for doc in list(items.find({})):
        if doc["id"] not in baseline:
            body = {k: v for k, v in doc.items() if k != "_id"}
            if archive.find_one({"id": doc["id"]}) is None:
                archive.insert_one(body)
            items.delete_one({"id": doc["id"]})
            archived.append(doc["id"])
    present = {d["id"] for d in items.find({})}
    for iid in sorted(baseline - present):
        doc = archive.find_one({"id": iid})
        if doc is None:
            continue
        items.insert_one({k: v for k, v in doc.items() if k != "_id"})
        archive.delete_one({"id": iid})
        restored.append(iid)
    logger.info("demo reset: archived %s, restored %s", archived, restored)
    return {"ok": True, "archived": archived, "restored": restored, "items": items.count_documents({})}
