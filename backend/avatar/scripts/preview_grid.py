"""Batch try-on preview for one avatar: renders every top x bottom (x jacket) combination through
the SAME path POST /render uses (ids.render_id_for -> service.render -> background._run), so every
result lands in the `renders` collection / media store exactly as the app would have cached it.
Then writes a numbered contact sheet PNG and a CSV to media/_preview/.

Generation runs synchronously in this script's own thread pool: background.submit is swapped for
a direct call to background._run in the calling thread, so service.render and background._run
themselves are untouched and the render docs are identical to the app's. Failure reasons are
taken from the avatar lane's own log lines, captured per worker thread.

COSTS GEMINI QUOTA: one call per combination rendered (skipped ones are free).

    .venv/Scripts/python.exe -m backend.avatar.scripts.preview_grid --avatar avatar_8e1b9d
        [--jackets none|picked|all] [--workers 4] [--only-missing]
        [--limit-tops N] [--limit-bottoms N]
        [--rerun <render_id>] [--rerun-item <item_id>]
        [--combos "top_x,bottom_y[,jacket_z];top_a,bottom_b"]   (just these outfits)

Without --only-missing every combination in the grid is deleted and regenerated (like a fresh
POST /render after a failure). --only-missing keeps `done` renders (and fresh `pending` ones) and
only generates the rest. --rerun / --rerun-item delete the matching render docs + their stored
images and regenerate only those, then still write a sheet for them.
"""
import argparse
import csv
import logging
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from backend import config, media_store
from backend.db import get_db
from backend.avatar import background, ids, media, service
from contract.enums import RenderStatus

PREVIEW_DIR = config.MEDIA_DIR / "_preview"

# --- run background._run inline instead of on the app's executors -------------------------------


def _inline_submit(render_id, avatar_doc, top_doc, bottom_doc, jacket_doc, renders_collection, prewarm=False):
    background._run(render_id, avatar_doc, top_doc, bottom_doc, jacket_doc, renders_collection)


background.submit = _inline_submit  # service.render calls background.submit(...) via the module


# --- per-thread capture of the avatar lane's log lines (the failure reason) ----------------------


class _ThreadLog(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines: dict[int, list[str]] = {}
        self.lock = threading.Lock()

    def emit(self, record):
        try:
            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                msg += f" [{type(record.exc_info[1]).__name__}: {record.exc_info[1]}]"
        except Exception:
            return
        with self.lock:
            self.lines.setdefault(record.thread, []).append(msg)

    def take(self) -> list[str]:
        with self.lock:
            return self.lines.pop(threading.get_ident(), [])


_LOG = _ThreadLog()
_av_logger = logging.getLogger("backend.avatar")
_av_logger.addHandler(_LOG)
_av_logger.setLevel(logging.INFO)


def _reason(lines: list[str]) -> str:
    for key in ("failed verification", "generation failed", "worker crashed", "verify identity failed"):
        for ln in reversed(lines):
            if key in ln:
                return ln.split(": ", 1)[-1] if key != "worker crashed" else ln
    return " | ".join(lines[-2:]) if lines else ""


# --- enumeration ---------------------------------------------------------------------------------


def _label(doc: Optional[dict]) -> str:
    if doc is None:
        return "-"
    name = doc.get("retailer_item_name") or doc.get("garment_type", "")
    color = doc.get("retailer_color")
    return f"{doc['id']} {color + ' ' if color else ''}{name}"


def enumerate_combos(item_docs, jackets_mode, limit_tops=None, limit_bottoms=None):
    tops = sorted((d for d in item_docs if d.get("category") == "tops"), key=lambda d: d["id"])
    bottoms = sorted((d for d in item_docs if d.get("category") == "bottoms"), key=lambda d: d["id"])
    jackets = sorted((d for d in item_docs if d.get("category") == "jackets"), key=lambda d: d["id"])
    if limit_tops:
        tops = tops[:limit_tops]
    if limit_bottoms:
        bottoms = bottoms[:limit_bottoms]
    top_ids = {d["id"] for d in tops}
    bottom_ids = {d["id"] for d in bottoms}

    combos = [(t["id"], b["id"], None) for t in tops for b in bottoms]
    if jackets_mode == "all":
        combos += [(t["id"], b["id"], j["id"]) for t in tops for b in bottoms for j in jackets]
    elif jackets_mode == "picked":
        from backend.avatar.prewarm import likely_outfits
        picked = [c for c in likely_outfits(item_docs, limit=10**6) if c[2]]
        combos += [c for c in picked if c[0] in top_ids and c[1] in bottom_ids]
    return combos


def all_combos(item_docs):
    return enumerate_combos(item_docs, "all")


# --- deletion (for --rerun / regenerate) ---------------------------------------------------------


def delete_render(db, render_id: str) -> None:
    db["renders"].delete_one({"render_id": render_id})
    for suffix in ("_local.png", "_generated.png"):
        rel = f"renders/{render_id}{suffix}"
        p = config.MEDIA_DIR / rel
        if p.is_file():
            p.unlink()
        try:
            bucket = media_store._bucket()
            for old in bucket.find({"filename": rel}):
                bucket.delete(old._id)
        except Exception as e:
            print(f"  warn: could not delete {rel} from durable storage: {e}")


# --- one combination -----------------------------------------------------------------------------


def run_one(db, avatar_doc, by_id, combo, only_missing):
    top_id, bottom_id, jacket_id = combo
    rid = ids.render_id_for(avatar_doc["avatar_id"], top_id, bottom_id, jacket_id)
    row = {"top_id": top_id, "bottom_id": bottom_id, "jacket_id": jacket_id or "", "render_id": rid,
           "status": "", "seconds": 0.0, "reason": "", "generated_url": "", "local_url": ""}
    existing = db["renders"].find_one({"render_id": rid})
    if existing is not None:
        existing = service.settle_if_stale(existing, db["renders"])
    if only_missing and existing is not None and existing.get("status") in (RenderStatus.done.value, RenderStatus.pending.value):
        row.update(status=f"{existing['status']} (cached)", generated_url=existing.get("generated_url") or "",
                   local_url=existing.get("local_url") or "")
        return row
    if existing is not None:
        delete_render(db, rid)

    _LOG.take()
    t0 = time.perf_counter()
    try:
        service.render(rid, avatar_doc, by_id[top_id], by_id[bottom_id],
                       by_id[jacket_id] if jacket_id else None, db["renders"])
    except Exception as e:
        row.update(status="failed", reason=f"render crashed: {type(e).__name__}: {e}")
    row["seconds"] = round(time.perf_counter() - t0, 1)
    lines = _LOG.take()
    doc = db["renders"].find_one({"render_id": rid}) or {}
    if not row["status"]:
        row["status"] = doc.get("status", "missing")
    row["generated_url"] = doc.get("generated_url") or ""
    row["local_url"] = doc.get("local_url") or ""
    if row["status"] != RenderStatus.done.value and not row["reason"]:
        row["reason"] = _reason(lines) or ("no GEMINI_API_KEY or source photo" if not lines else "")
    print(f"  {row['status']:<8} {row['seconds']:>5}s {rid} {top_id}/{bottom_id}/{jacket_id or '-'} {row['reason']}")
    return row


# --- contact sheet -------------------------------------------------------------------------------

TILE_W, IMG_H, LABEL_H, COLS = 300, 450, 110, 5


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def contact_sheet(rows, by_id, out_path: Path):
    n = len(rows)
    cols = min(COLS, max(1, n))
    nrows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TILE_W, max(1, nrows) * (IMG_H + LABEL_H)), "white")
    d = ImageDraw.Draw(sheet)
    f_small, f_big = _font(12), _font(16)
    for i, r in enumerate(rows):
        x, y = (i % cols) * TILE_W, (i // cols) * (IMG_H + LABEL_H)
        ok = r["status"].startswith("done") and r["generated_url"]
        if ok:
            try:
                img = media.load_media(r["generated_url"]).convert("RGB")
                img.thumbnail((TILE_W - 8, IMG_H - 8))
                sheet.paste(img, (x + (TILE_W - img.width) // 2, y + (IMG_H - img.height) // 2))
            except Exception as e:
                ok = False
                r["reason"] = r["reason"] or f"could not load image: {e}"
        if not ok:
            d.rectangle([x + 4, y + 4, x + TILE_W - 4, y + IMG_H - 4], fill=(170, 170, 170))
            msg = f"{r['status'].upper()}\n\n" + "\n".join(textwrap.wrap(r["reason"] or "(no reason logged)", 34))
            d.multiline_text((x + 14, y + 20), msg, fill="black", font=f_small)
        d.text((x + 8, y + 6), f"#{i + 1}", fill=(200, 0, 0), font=f_big)
        lab = [f"T: {_label(by_id.get(r['top_id']))}", f"B: {_label(by_id.get(r['bottom_id']))}",
               f"J: {_label(by_id.get(r['jacket_id'])) if r['jacket_id'] else '-'}",
               f"{r['status']}  {r['seconds']}s  {r['render_id']}"]
        ty = y + IMG_H + 4
        for ln in lab:
            for part in textwrap.wrap(ln, 44)[:2]:
                d.text((x + 8, ty), part, fill="black", font=f_small)
                ty += 14
        d.rectangle([x, y, x + TILE_W - 1, y + IMG_H + LABEL_H - 1], outline=(220, 220, 220))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


# --- main ----------------------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--avatar", required=True)
    ap.add_argument("--jackets", choices=("none", "picked", "all"), default="none")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only-missing", action="store_true")
    ap.add_argument("--limit-tops", type=int)
    ap.add_argument("--limit-bottoms", type=int)
    ap.add_argument("--rerun", metavar="RENDER_ID")
    ap.add_argument("--rerun-item", metavar="ITEM_ID")
    ap.add_argument("--combos", metavar='"top,bottom[,jacket];..."',
                    help="render just these outfits (overrides the grid flags)")
    args = ap.parse_args(argv)

    db = get_db()
    avatar_doc = db["avatars"].find_one({"avatar_id": args.avatar})
    if avatar_doc is None:
        raise SystemExit(f"no avatar {args.avatar!r}")
    if not config.GEMINI_API_KEY:
        print("warning: GEMINI_API_KEY is not set -- every render will be `failed` (local composite only)")
    item_docs = list(db["items"].find({}))
    by_id = {d["id"]: d for d in item_docs}

    only_missing = args.only_missing
    if args.rerun or args.rerun_item:
        universe = all_combos(item_docs)
        if args.rerun:
            combos = [c for c in universe if ids.render_id_for(args.avatar, *c) == args.rerun]
            if not combos:
                raise SystemExit(f"{args.rerun} is not a combination of {args.avatar} with the current closet")
        else:
            if args.rerun_item not in by_id:
                raise SystemExit(f"no item {args.rerun_item!r}")
            # every EXISTING render of this avatar that uses the item
            combos = [c for c in universe if args.rerun_item in c
                      and db["renders"].find_one({"render_id": ids.render_id_for(args.avatar, *c)})]
            if not combos:
                print(f"no existing renders use {args.rerun_item}; nothing to rerun")
                return 0
        only_missing = False  # run_one deletes the doc + images, then regenerates
        tag = f"rerun_{args.rerun or args.rerun_item}"
    elif args.combos:
        combos = []
        for part in filter(None, (p.strip() for p in args.combos.split(";"))):
            f = [x.strip() for x in part.split(",")]
            if len(f) not in (2, 3):
                raise SystemExit(f"bad combo {part!r}: want top,bottom[,jacket]")
            for x in f:
                if x not in by_id:
                    raise SystemExit(f"no item {x!r}")
            combos.append((f[0], f[1], f[2] if len(f) == 3 else None))
        tag = "combos"
    else:
        combos = enumerate_combos(item_docs, args.jackets, args.limit_tops, args.limit_bottoms)
        tag = f"{args.jackets}"

    print(f"{args.avatar}: {len(combos)} combination(s), {args.workers} worker(s), only_missing={only_missing}")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, args.workers), thread_name_prefix="preview-grid") as ex:
        rows = list(ex.map(lambda c: run_one(db, avatar_doc, by_id, c, only_missing), combos))
    total = round(time.perf_counter() - t0, 1)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = PREVIEW_DIR / f"grid_{args.avatar}_{tag}_{stamp}"
    contact_sheet(rows, by_id, base.with_suffix(".png"))
    with open(base.with_suffix(".csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["n", "top_id", "bottom_id", "jacket_id", "render_id", "status",
                                           "seconds", "reason", "generated_url", "local_url"])
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow({"n": i + 1, **r})
    done = sum(r["status"].startswith("done") for r in rows)
    print(f"total {total}s; {done}/{len(rows)} done")
    print(f"sheet: {base.with_suffix('.png')}")
    print(f"csv:   {base.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
