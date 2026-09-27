"""Prewarm: right after a scan, start background try-ons for the outfits "generate outfit" is
most likely to pick, so the user's first "see it on me" is usually a cache hit.

Uses the styling lane's own candidate generation and variety pool (read-only import -- the pool
is what select_outfits samples from), best score first, capped at PREWARM_MAX_OUTFITS. Each
outfit goes through service.render(prewarm=True): the SAME render doc (pending -> done/failed)
POST /render would create, keyed by the same render_id, so a later POST /render hits the cache.
Generation runs on background.py's separate, smaller prewarm executor, so a user's click never
queues behind a prewarm job. Everything here is best-effort: any failure is logged and dropped.
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from backend import config
from contract.schemas import Item

from . import ids, service

logger = logging.getLogger(__name__)

PREWARM_ENABLED = os.environ.get("ATELIER_PREWARM_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
PREWARM_MAX_OUTFITS = 6

# One worker: only enumerates outfits and builds local composites; generation itself goes to
# background.py's prewarm executor.
_SCHEDULER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avatar-prewarm")


def _planned(item_docs: list[dict]) -> list[tuple[str, str, Optional[str]]]:
    """The demo's planned outfits (backend/styling/planned.py, env ATELIER_DEMO_OUTFITS) whose
    garments all exist in this closet. Best-effort: missing module or any error -> []."""
    try:
        from backend.styling.planned import planned_outfits
        planned = list(planned_outfits() or [])
    except Exception:
        return []
    existing = {d.get("id") for d in item_docs}
    out = []
    for entry in planned:
        try:
            t, b, j = entry
        except Exception:
            continue
        if t in existing and b in existing and (j is None or j in existing) and (t, b, j) not in out:
            out.append((t, b, j))
    return out


def likely_outfits(item_docs: list[dict], limit: int = PREWARM_MAX_OUTFITS) -> list[tuple[str, str, Optional[str]]]:
    """-> up to `limit` (top_id, bottom_id, jacket_id): the demo's planned outfits first, then
    best score first from the same pool backend/styling/select.py samples "generate outfit" from."""
    planned = _planned(item_docs)[:limit]
    rest = [c for c in _likely_from_pool(item_docs, limit) if c not in planned]
    return (planned + rest)[:limit]


def _likely_from_pool(item_docs: list[dict], limit: int) -> list[tuple[str, str, Optional[str]]]:
    from backend.styling import weights as W
    from backend.styling.strategies import generate_candidates

    items = []
    for doc in item_docs:
        try:
            items.append(Item.model_validate({k: v for k, v in doc.items() if k in Item.model_fields}).model_dump())
        except Exception:
            continue
    tops = [i for i in items if i["category"] == "tops"]
    bottoms = [i for i in items if i["category"] == "bottoms"]
    jackets = [i for i in items if i["category"] == "jackets"]

    ranked = sorted(
        ((score, strategy, top["id"], bottom["id"], jacket["id"] if jacket else None)
         for strategy, top, bottom, jacket, score in generate_candidates(tops, bottoms, jackets)),
        key=lambda t: t[0], reverse=True,
    )
    if not ranked:
        return []
    floor = ranked[0][0] - W.VARIETY_POOL_MARGIN
    pool = [r for r in ranked if r[0] >= W.VARIETY_MIN_SCORE or r[0] >= floor]
    # Greedy through the pool under generate's own per-strategy / shared-garment caps, so the
    # prewarmed set looks like what generate actually returns (not six variants of one dress);
    # then top up from the pool ignoring the caps.
    from collections import Counter
    from backend.styling import select as select_mod
    strat, garm = Counter(), Counter()
    out, seen = [], set()
    for rules in (True, False):
        for _score, strategy, t, b, j in pool:
            if len(out) >= limit:
                break
            c = {"strategy": strategy, "top_id": t, "bottom_id": b, "jacket_id": j}
            if (t, b, j) in seen or (rules and not select_mod._fits_rules(c, strat, garm)):
                continue
            seen.add((t, b, j))
            select_mod._apply(c, strat, garm)
            out.append((t, b, j))
    return out


def prewarm_avatar(avatar_doc: dict, db) -> list[str]:
    """Synchronously enumerate and submit prewarm renders for one avatar. -> render_ids submitted
    (generation itself runs on background.py's prewarm executor)."""
    if not PREWARM_ENABLED:
        return []
    if not (config.GEMINI_API_KEY and avatar_doc.get("source_photo_url")):
        return []
    item_docs = list(db["items"].find({}))
    by_id = {d.get("id"): d for d in item_docs}
    submitted = []
    for top_id, bottom_id, jacket_id in likely_outfits(item_docs):
        render_id = ids.render_id_for(avatar_doc["avatar_id"], top_id, bottom_id, jacket_id)
        try:
            if db["renders"].find_one({"render_id": render_id}) is not None:
                continue  # already requested (by the user or an earlier prewarm)
            service.render(
                render_id, avatar_doc, by_id[top_id], by_id[bottom_id],
                by_id[jacket_id] if jacket_id else None, db["renders"], prewarm=True,
            )
            submitted.append(render_id)
        except Exception:
            logger.exception("avatar: prewarm of %s failed", render_id)
    logger.info("avatar: prewarm submitted %d render(s) for %s", len(submitted), avatar_doc.get("avatar_id"))
    return submitted


def schedule(avatar_doc: dict, db) -> None:
    """Fire-and-forget from the scan route; never blocks, never raises."""
    if not PREWARM_ENABLED:
        return
    try:
        _SCHEDULER.submit(_safe_prewarm, avatar_doc, db)
    except Exception:
        logger.exception("avatar: could not schedule prewarm")


def _safe_prewarm(avatar_doc, db):
    try:
        prewarm_avatar(avatar_doc, db)
    except Exception:
        logger.exception("avatar: prewarm crashed")
