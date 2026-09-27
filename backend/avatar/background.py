"""A7: the generation ladder runs off the request thread, never in it (A-R12). POST /render has
already returned the local composite by the time anything here runs; this module's only job is
to eventually flip a stored render doc from `pending` to `done` (+ generated_url) or `failed`.
Abandonment is harmless -- if nobody is polling, the job still finishes and populates the cache
(BACKEND_API.md).

A-R15 quota discipline: no retries here. A single failure (network, quota, verification) marks
the render `failed` immediately; the contract explicitly treats `failed` as "keep the local
composite, no error" so a quiet failure is the CORRECT behavior, not a degraded one.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from PIL import Image

from contract.enums import GarmentType, RenderStatus

from . import gen_client, media, person, verify
from .errors import AvatarError

logger = logging.getLogger(__name__)

# Small pools: this is a hackathon demo, not a production fan-out. Never joined by request code.
# User-requested renders and scan-time prewarm (prewarm.py) use SEPARATE executors, so a user's
# click never queues behind prewarm jobs.
USER_WORKERS = 4
PREWARM_WORKERS = 2
_EXECUTOR = ThreadPoolExecutor(max_workers=USER_WORKERS, thread_name_prefix="avatar-gen")
_PREWARM_EXECUTOR = ThreadPoolExecutor(max_workers=PREWARM_WORKERS, thread_name_prefix="avatar-gen-prewarm")


def submit(
    render_id: str,
    avatar_doc: dict,
    top_doc: dict,
    bottom_doc: dict,
    jacket_doc: Optional[dict],
    renders_collection,
    prewarm: bool = False,
    attempt: Optional[str] = None,
):
    executor = _PREWARM_EXECUTOR if prewarm else _EXECUTOR
    executor.submit(_run, render_id, avatar_doc, top_doc, bottom_doc, jacket_doc, renders_collection, attempt)


def _claim(renders_collection, render_id: str, attempt: Optional[str]) -> Optional[dict]:
    """Atomically claim a queued `pending` job so exactly one worker runs it (a prewarm job and a
    user's cache-hit resubmission can both be queued for the same doc). -> the doc as it was
    before the claim, or None if someone else claimed it, it settled, or it was reset/deleted."""
    flt = {"render_id": render_id, "status": RenderStatus.pending.value, "claimed": {"$ne": True}}
    if attempt is not None:
        flt["attempt"] = attempt
    return renders_collection.find_one_and_update(
        flt, {"$set": {"claimed": True, "started_at": datetime.now(timezone.utc)}},
    )


def _update(renders_collection, render_id: str, status: RenderStatus, generated_url: Optional[str],
            attempt: Optional[str] = None):
    """Writes only to the attempt this worker claimed: a stale job (its doc deleted and re-inserted
    by a retry) must never overwrite the retry's result. started_at is cleared once settled."""
    renders_collection.update_one(
        {"render_id": render_id, "attempt": attempt},
        {"$set": {"status": status.value, "generated_url": generated_url, "started_at": None}},
    )


def _cutout_frame_landmarks(avatar_doc: dict, cutout_size: tuple[int, int]) -> tuple[dict, tuple[int, int]]:
    """-> ({name: [x, y]}, (w, h)) in the avatar cutout canvas's pixel frame: the stored canvas
    rig (rig_local, same canvas as avatar_url). Falls back to the source-photo landmarks only for
    a legacy doc with no rig."""
    rig_lms = (avatar_doc.get("rig") or {}).get("landmarks")
    if rig_lms:
        return {k: [float(v[0]), float(v[1])] for k, v in rig_lms.items()}, tuple(cutout_size)
    return avatar_doc["source_landmarks"], (avatar_doc["source_w"], avatar_doc["source_h"])


def _run(render_id, avatar_doc, top_doc, bottom_doc, jacket_doc, renders_collection, attempt=None):
    try:
        claimed = _claim(renders_collection, render_id, attempt)
    except Exception:
        logger.exception("avatar: render %s could not be claimed", render_id)
        return
    if claimed is None:
        return  # another worker runs it, or it already settled / was reset
    attempt = claimed.get("attempt")
    try:
        is_dress = GarmentType(top_doc["garment_type"]) == GarmentType.dress

        # The background-removed avatar cutout on plain white, not the raw photo (human request:
        # the try-on keeps the background removed).
        cutout = media.load_media(avatar_doc["avatar_url"]).convert("RGBA")
        person_img = Image.new("RGB", cutout.size, (255, 255, 255))
        person_img.paste(cutout, mask=cutout.getchannel("A"))
        top_img = media.load_media(top_doc["cutout_url"])
        # A dress still has a bottom slot (A-R5: "no exclusion logic") and it is sent too --
        # A-R7 chose an instruction-following model precisely so it can layer them correctly.
        bottom_img = media.load_media(bottom_doc["cutout_url"])
        jacket_img = media.load_media(jacket_doc["cutout_url"]) if jacket_doc is not None else None

        generated = gen_client.generate_tryon(person_img, top_img, bottom_img, jacket_img, is_dress)

        # Gemini was sent the avatar CUTOUT canvas, not the original photo, so the fallback
        # landmarks (and the identity check's head location) must be in that canvas's frame.
        frame_landmarks, frame_size = _cutout_frame_landmarks(avatar_doc, person_img.size)
        jacket_arg = (GarmentType(jacket_doc["garment_type"]), jacket_doc) if jacket_doc is not None else None
        ok, reason = verify.verify_colors(
            np.asarray(generated),
            frame_landmarks,
            frame_size,
            top=(GarmentType(top_doc["garment_type"]), top_doc),
            bottom=(GarmentType(bottom_doc["garment_type"]), bottom_doc),
            jacket=jacket_arg,
            render_id=render_id,
            source_rgb=np.asarray(person_img),  # ISSUES #22: identity check against the scan's own face
        )
        if not ok:
            logger.info("avatar: render %s failed verification: %s", render_id, reason)
            _update(renders_collection, render_id, RenderStatus.failed, None, attempt)
            return

        # Transparent try-on (human request): verification above ran on the RGB white-background
        # image; only now is the person cut out (segmentation, not a white threshold). Degraded
        # state, not a failure: if the cutout fails, the white-background image is saved as is.
        to_save = generated
        try:
            cut = person.cut_out_generated(np.asarray(generated.convert("RGB")))
        except Exception:
            cut = None
        if cut is not None:
            to_save = cut
        else:
            logger.warning("avatar: render %s background cutout failed; keeping white background", render_id)

        generated_url = media.save_png(to_save, "renders", f"{render_id}_generated.png")
        _update(renders_collection, render_id, RenderStatus.done, generated_url, attempt)

    except (gen_client.GenerationError, AvatarError) as e:
        logger.info("avatar: render %s generation failed: %s", render_id, e)
        _update(renders_collection, render_id, RenderStatus.failed, None, attempt)
    except Exception:  # A9: a worker crash must never leave a render stuck in `pending` forever
        logger.exception("avatar: render %s worker crashed", render_id)
        _update(renders_collection, render_id, RenderStatus.failed, None, attempt)
