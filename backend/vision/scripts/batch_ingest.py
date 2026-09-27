"""Batch closet ingest: a folder of retail photos + a manifest CSV -> saved items, exactly as if
each were added through the UI (POST /api/items/analyze then POST /api/items/save; the route
functions are called directly, not over HTTP). Produces contact sheets for review.

Usage (repo root, .venv/Scripts/python.exe):

  # 1. template manifest (fill in category + garment_type; item_name / color optional)
  batch_ingest.py --make-manifest <folder>                 -> <folder>/manifest.csv
  # 2. safety first
  batch_ingest.py --backup                                 -> media/_backup/items_<ts>.json
  batch_ingest.py --archive-current --dry-run              (prints the plan)
  batch_ingest.py --archive-current --yes                  (items -> items_archive, reversible)
  batch_ingest.py --restore-archive --yes                  (undo: items_archive -> items)
  # 3. ingest (writes a backup automatically first; --preview = analyze only, save nothing)
  batch_ingest.py --ingest <folder> [--manifest m.csv] [--workers 4] [--preview] [--out dir]
                  [--flatlay]   (garment-alone product photos: backend/vision/flatlay.py)
  #    (--preview writes to <folder>/_atelier_preview; a real run refuses an out dir that
  #     already has results.json)
  # 4. fixes (the out dir defaults to <folder>/_atelier_out)
  batch_ingest.py --replace <item_id> --candidate <0|1|2> --out <folder>/_atelier_out
  batch_ingest.py --replace <item_id> --image <photo> [--candidate n] --out <folder>/_atelier_out

--sandbox <dir> runs everything against <dir> as MEDIA_DIR and a JSON-file fake DB at
<dir>/db.json (no MongoDB, no GridFS) -- for dry runs.

Candidate choice: the candidate passing the most automated checks (backend/vision/checks.py);
ties prefer "balanced" (index 1), then the lowest index. Same rule as seed_closet.py.
"""
import argparse
import csv
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MANIFEST_COLS = ["file", "category", "garment_type", "item_name", "color"]


# ----------------------------------------------------------------------------- sandbox fake DB
class _FileCollection:
    def __init__(self, store, name):
        self.store, self.name = store, name

    @property
    def docs(self):
        return self.store.data.setdefault(self.name, [])

    @staticmethod
    def _match(d, flt):
        return all(d.get(k) == v for k, v in (flt or {}).items())

    def find(self, flt=None, projection=None):
        return [dict(d) for d in self.docs if self._match(d, flt)]

    def find_one(self, flt=None, projection=None):
        return next((dict(d) for d in self.docs if self._match(d, flt)), None)

    def insert_one(self, doc):
        self.docs.append(json.loads(json.dumps(doc, default=str)))
        self.store.flush()

    def insert_many(self, docs):
        for d in docs:
            self.docs.append(json.loads(json.dumps(d, default=str)))
        self.store.flush()

    def update_one(self, flt, update):
        for d in self.docs:
            if self._match(d, flt):
                d.update(json.loads(json.dumps(update.get("$set", {}), default=str)))
        self.store.flush()

    def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if self._match(d, flt):
                del self.docs[i]
                break
        self.store.flush()

    def delete_many(self, flt):
        self.store.data[self.name] = [d for d in self.docs if not self._match(d, flt)]
        self.store.flush()

    def count_documents(self, flt=None):
        return len(self.find(flt))


class _FileDB:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def __getitem__(self, name):
        return _FileCollection(self, name)

    def flush(self):
        self.path.write_text(json.dumps(self.data, indent=1, default=str), encoding="utf-8")


# ----------------------------------------------------------------------------- setup
def _setup(sandbox: str | None):
    """Import backend modules (after MEDIA_DIR env is set) and return the db handle."""
    from backend import db as db_mod, media_store
    if sandbox:
        sdir = Path(sandbox).resolve()
        fake = _FileDB(sdir / "db.json")
        db_mod.get_db = lambda: fake                       # route + media_store both go here
        media_store.put = lambda key, data: None           # file already on sandbox disk
        return fake
    return db_mod.get_db()


def _ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _checks_score(checks: dict) -> tuple[int, int]:
    bools = [v for v in checks.values() if isinstance(v, bool)]
    return sum(bools), len(bools)


def best_index(cands: list[dict]) -> int:
    scored = [(_checks_score(c["checks"])[0], c["index"]) for c in cands]
    if not scored:
        return 1
    top = max(s for s, _ in scored)
    tied = [i for s, i in scored if s == top]
    return 1 if 1 in tied else min(tied)


# ----------------------------------------------------------------------------- analyze (worker)
_ATEXIT = []


def _close_mp():
    """Close the cached MediaPipe models before interpreter teardown (their __del__ otherwise
    prints harmless-but-noisy TypeErrors at exit)."""
    from backend.vision import mp_models
    for fn in (mp_models.pose_landmarker, mp_models.image_segmenter):
        if fn.cache_info().currsize:
            try:
                fn().close()
            except Exception:
                pass
            fn.cache_clear()


def analyze_one(path: str, category: str, garment_type: str, color: str | None,
                item_name: str | None, flatlay: bool = False) -> dict:
    """Runs the POST /items/analyze route function in-process. Returns {"temp_handle": ...}
    or {"error": {...}}. Safe in a worker process (touches only disk under MEDIA_DIR)."""
    import asyncio
    import atexit
    if not _ATEXIT:
        atexit.register(_close_mp)
        _ATEXIT.append(1)
    import io
    from fastapi import UploadFile
    from backend.routes import items as items_route
    from backend.routes.items import analyze
    if flatlay:  # batch-only: garment-alone product photos, no person (backend/vision/flatlay.py)
        from backend.vision.flatlay import analyze_flatlay_bytes
        items_route.build_candidates = analyze_flatlay_bytes

    p = Path(path)
    up = UploadFile(file=io.BytesIO(p.read_bytes()), filename=p.name)
    resp = asyncio.run(analyze(image=up, category=category, garment_type=garment_type,
                               color=color or None, item_name=item_name or None))
    if hasattr(resp, "temp_handle"):
        return {"temp_handle": resp.temp_handle}
    return json.loads(resp.body)


def _worker_init(media_dir: str | None):
    if media_dir:
        os.environ["MEDIA_DIR"] = media_dir


# ----------------------------------------------------------------------------- manifest
def make_manifest(folder: Path):
    files = sorted(p.name for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    out = folder / "manifest.csv"
    if out.exists():
        print(f"{out} already exists; not overwriting.")
        raise SystemExit(1)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MANIFEST_COLS)
        for name in files:
            w.writerow([name, "", "", "", ""])
    print(f"wrote {out} ({len(files)} images). Fill category (tops|bottoms|jackets) and "
          f"garment_type (shirt|dress | pants|skirt|shorts | jacket|coat); item_name and "
          f"color (e.g. #1c1c1c) are optional.")


def read_manifest(path: Path, folder: Path) -> list[dict]:
    from pydantic import ValidationError
    from contract.schemas import AnalyzeForm
    rows, errors = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, r in enumerate(csv.DictReader(f), start=1):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("file"):
                continue
            img = folder / r["file"]
            if not img.exists():
                errors.append(f"row {n}: file not found: {img}")
            try:
                AnalyzeForm(category=r.get("category"), garment_type=r.get("garment_type"),
                            color=r.get("color") or None, item_name=r.get("item_name") or None)
            except ValidationError as e:
                errors.append(f"row {n} ({r['file']}): {e.errors()[0]['msg']}")
            rows.append({"row": n, **r, "path": str(img)})
    if errors:
        print("manifest errors:\n  " + "\n  ".join(errors))
        raise SystemExit(1)
    return rows


# ----------------------------------------------------------------------------- backup / archive
def backup(db) -> Path:
    from backend import config
    docs = list(db["items"].find({}))  # a real Mongo cursor can only be read once
    for d in docs:
        d.pop("_id", None)
    keys = [f"items/{d['id']}.png" for d in docs]
    out = config.MEDIA_DIR / "_backup" / f"items_{_ts()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"count": len(docs), "media_keys": keys, "items": docs},
                              indent=1, default=str), encoding="utf-8")
    print(f"backup: {len(docs)} item(s) -> {out}")
    return out


def _move(db, src: str, dst: str, dry: bool, yes: bool):
    docs = list(db[src].find({}))  # a real Mongo cursor can only be read once
    ids = [d["id"] for d in docs]
    print(f"plan: copy {len(docs)} doc(s) from '{src}' to '{dst}' (upsert by id), then delete "
          f"them from '{src}'. Media files / GridFS are NOT touched. ids: {', '.join(ids) or '-'}")
    if dry or not yes:
        print("dry run -- nothing changed." if dry else "not acting: pass --yes to do it.")
        return
    backup(db)
    for d in docs:
        d.pop("_id", None)
        if db[dst].find_one({"id": d["id"]}) is None:
            db[dst].insert_one(d)
        db[src].delete_one({"id": d["id"]})
    print(f"done: '{src}' now has {len(list(db[src].find({})))}, '{dst}' has {len(list(db[dst].find({})))}.")


# ----------------------------------------------------------------------------- contact sheets
def _font(size):
    from PIL import ImageFont
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _checker(w, h, sq=12):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(im)
    for y in range(0, h, sq):
        for x in range(0, w, sq):
            if (x // sq + y // sq) % 2:
                d.rectangle([x, y, x + sq - 1, y + sq - 1], fill=(228, 228, 228))
    return im


def _thumb(png: Path, w, h):
    from PIL import Image
    bg = _checker(w, h)
    if png and png.exists():
        im = Image.open(png).convert("RGBA")
        im.thumbnail((w - 8, h - 8))
        bg.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
    return bg


def _hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _tile(num, png, lines, color, w=260, ih=300):
    from PIL import Image, ImageDraw
    th = ih + 96
    tile = Image.new("RGB", (w, th), "white")
    tile.paste(_thumb(png, w, ih), (0, 0))
    d = ImageDraw.Draw(tile)
    d.rectangle([0, 0, 44, 28], fill=(30, 30, 30))
    d.text((6, 3), f"#{num}", fill="white", font=_font(18))
    y = ih + 4
    if color:
        d.rectangle([6, y, 34, y + 28], fill=_hex_rgb(color["hex"]), outline=(120, 120, 120))
    for i, line in enumerate(lines):
        d.text((40 if i < 2 else 6, y + i * 18), line[:36], fill=(20, 20, 20), font=_font(14))
    d.rectangle([0, 0, w - 1, th - 1], outline=(200, 200, 200))
    return tile


def _grid(tiles, cols, out: Path, title: str):
    from PIL import Image, ImageDraw
    if not tiles:
        return
    tw, th = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 8, rows * th + (rows + 1) * 8 + 36), "white")
    ImageDraw.Draw(sheet).text((10, 8), title, fill="black", font=_font(20))
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet.paste(t, (8 + c * (tw + 8), 44 + r * (th + 8)))
    sheet.save(out)
    print(f"sheet: {out}")


def render_sheets(out_dir: Path, results: list[dict]):
    from backend import config
    chosen_tiles, cand_tiles = [], []
    for r in results:
        num = r["row"]
        if r.get("error"):
            chosen_tiles.append(_tile(num, None, [r["file"][:36], "ERROR", r["error"][:36]], None))
            continue
        ci = r["chosen_index"]
        c = r["candidates"][ci]
        p, t = _checks_score(c["checks"])
        pc = c["primary_color"]
        live = config.MEDIA_DIR / "items" / f"{r['item_id']}.png" if r.get("item_id") else None
        png = live if live and live.exists() else out_dir / c["png"]
        chosen_tiles.append(_tile(num, png, [
            pc.get("display_name") or pc["name"], pc["hex"],
            f"{r.get('item_id') or '(not saved)'}  cand {ci} {c['variant']}",
            f"{r['category']}/{r['garment_type']}  checks {p}/{t}",
        ], pc))
        for c in r["candidates"]:
            p, t = _checks_score(c["checks"])
            pc = c["primary_color"]
            mark = " <- chosen" if c["index"] == ci else ""
            cand_tiles.append(_tile(num, out_dir / c["png"], [
                pc.get("display_name") or pc["name"], pc["hex"],
                f"cand {c['index']} {c['variant']}{mark}",
                f"checks {p}/{t}  {r.get('item_id') or ''}",
            ], pc, w=220, ih=250))
    _grid(chosen_tiles, 6, out_dir / "contact_sheet.png", f"Atelier batch -- chosen cutouts ({len(results)})")
    _grid(cand_tiles, 6, out_dir / "candidates_sheet.png",
          "All candidates per item (row #, cand 0 tight / 1 balanced / 2 generous)")


def write_results(out_dir: Path, results: list[dict]):
    (out_dir / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["row", "file", "item_id", "category", "garment_type", "chosen_index", "variant",
                    "checks_passed", "primary_hex", "primary_name", "display_name",
                    "secondary_hex", "error"])
        for r in results:
            if r.get("error"):
                w.writerow([r["row"], r["file"], "", r["category"], r["garment_type"], "", "", "",
                            "", "", "", "", r["error"]])
                continue
            c = r["candidates"][r["chosen_index"]]
            p, t = _checks_score(c["checks"])
            sc = c["secondary_color"] or {}
            w.writerow([r["row"], r["file"], r.get("item_id") or "", r["category"], r["garment_type"],
                        r["chosen_index"], c["variant"], f"{p}/{t}", c["primary_color"]["hex"],
                        c["primary_color"]["name"], c["primary_color"].get("display_name"),
                        sc.get("hex", ""), ""])
    print(f"results: {out_dir / 'results.json'} , {out_dir / 'results.csv'}")


# ----------------------------------------------------------------------------- ingest
def _collect(handle: str, out_dir: Path, tag: str) -> list[dict]:
    """Copy the 3 candidate PNGs out of media/tmp and return the session's candidate records."""
    from backend.vision.session import load_session, tmp_media_dir
    sess = load_session(handle)
    cdir = out_dir / "candidates"
    cdir.mkdir(parents=True, exist_ok=True)
    cands = []
    for c in sess["candidates"]:
        dst = cdir / f"{tag}_{c['index']}.png"
        shutil.copyfile(tmp_media_dir() / c["filename"], dst)
        cands.append({**{k: c[k] for k in ("index", "variant", "primary_color", "secondary_color",
                                           "anchors", "checks")}, "png": f"candidates/{dst.name}"})
    return cands


def _save(db, handle: str, idx: int) -> dict:
    from contract.schemas import SaveRequest
    from backend.routes.items import save
    resp = save(SaveRequest(temp_handle=handle, candidate_index=idx), db=db)
    if hasattr(resp, "id"):
        return {"item_id": resp.id}
    return json.loads(resp.body)


def _run_analyses(jobs: list[tuple], workers: int, media_dir: str | None) -> list[dict]:
    if workers <= 1:
        return [analyze_one(*j) for j in jobs]
    from concurrent.futures import ProcessPoolExecutor
    # MediaPipe models are process-global singletons (not shared across threads), so parallelism
    # is one process per worker; analyze only touches disk, saves stay in this process.
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                             initargs=(media_dir,)) as ex:
        futs = [ex.submit(analyze_one, *j) for j in jobs]
        out = []
        for j, f in zip(jobs, futs):
            try:
                out.append(f.result())
            except Exception as e:
                out.append({"error": {"code": "analyze_failed", "message": str(e)}})
            print(f"  analyzed {Path(j[0]).name}: {out[-1].get('temp_handle') or out[-1]['error']['code']}")
        return out


def ingest(db, folder: Path, manifest: Path, out_dir: Path, workers: int, preview: bool,
           media_dir: str | None, flatlay: bool = False):
    from backend.vision.session import delete_session
    rows = read_manifest(manifest, folder)
    if (out_dir / "results.json").exists():
        print(f"{out_dir / 'results.json'} already exists (a previous batch); pass a different --out.")
        raise SystemExit(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not preview:
        backup(db)
    print(f"analyzing {len(rows)} photo(s) with {workers} worker(s)...")
    jobs = [(r["path"], r["category"], r["garment_type"], r.get("color"), r.get("item_name"),
             flatlay) for r in rows]
    analyses = _run_analyses(jobs, workers, media_dir)

    results = []
    for r, a in zip(rows, analyses):
        base = {"row": r["row"], "file": r["file"], "category": r["category"],
                "garment_type": r["garment_type"]}
        if "error" in a:
            results.append({**base, "error": f"{a['error']['code']}: {a['error']['message']}"})
            continue
        handle = a["temp_handle"]
        cands = _collect(handle, out_dir, f"row{r['row']:02d}")
        idx = best_index(cands)
        entry = {**base, "chosen_index": idx, "candidates": cands, "item_id": None}
        if preview:
            delete_session(handle)
        else:
            s = _save(db, handle, idx)
            if "item_id" in s:
                entry["item_id"] = s["item_id"]
            else:
                entry = {**base, "error": f"save {s['error']['code']}: {s['error']['message']}"}
        results.append(entry)
        print(f"  row {r['row']:>2} {r['file'][:40]:<40} -> {entry.get('item_id') or entry.get('error') or '(preview)'}"
              + (f" cand {idx}" if "chosen_index" in entry else ""))

    write_results(out_dir, results)
    render_sheets(out_dir, results)


# ----------------------------------------------------------------------------- replace
def _apply(db, item_id: str, src_png: Path, cand: dict):
    from backend import config, media_store
    dest = config.MEDIA_DIR / "items" / f"{item_id}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_png, dest)
    media_store.persist(dest)
    db["items"].update_one({"id": item_id}, {"$set": {
        "primary_color": cand["primary_color"], "secondary_color": cand["secondary_color"],
        "anchors": cand["anchors"]}})


def replace(db, item_id: str, out_dir: Path, candidate: int | None, image: Path | None):
    from backend.vision.session import delete_session
    doc = db["items"].find_one({"id": item_id})
    if doc is None:
        print(f"no item {item_id!r} in items.")
        raise SystemExit(1)
    rpath = out_dir / "results.json"
    results = json.loads(rpath.read_text(encoding="utf-8")) if rpath.exists() else []
    entry = next((r for r in results if r.get("item_id") == item_id), None)

    if image is not None:
        a = analyze_one(str(image), doc["category"], doc["garment_type"],
                        doc.get("retailer_color"), doc.get("retailer_item_name"))
        if "error" in a:
            print(f"analyze failed: {a['error']}")
            raise SystemExit(1)
        cands = _collect(a["temp_handle"], out_dir, f"{item_id}_{_ts()}")
        delete_session(a["temp_handle"])
        if entry is None:
            entry = {"row": len(results) + 1, "category": doc["category"],
                     "garment_type": doc["garment_type"], "item_id": item_id}
            results.append(entry)
        entry.update({"file": image.name, "candidates": cands})
        idx = best_index(cands) if candidate is None else candidate
    else:
        if entry is None:
            print(f"{item_id} is not in {rpath}; use --image to re-ingest it from a photo.")
            raise SystemExit(1)
        idx = candidate
    if idx not in (0, 1, 2):
        print("--candidate must be 0, 1 or 2")
        raise SystemExit(2)
    cand = entry["candidates"][idx]
    entry["chosen_index"] = idx
    entry.pop("error", None)
    _apply(db, item_id, out_dir / cand["png"], cand)
    p, t = _checks_score(cand["checks"])
    print(f"{item_id}: now candidate {idx} ({cand['variant']}), checks {p}/{t}, "
          f"primary {cand['primary_color']['hex']} {cand['primary_color'].get('display_name')}")
    write_results(out_dir, results)
    render_sheets(out_dir, results)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--make-manifest", metavar="FOLDER")
    ap.add_argument("--ingest", metavar="FOLDER")
    ap.add_argument("--manifest", help="default <folder>/manifest.csv")
    ap.add_argument("--out", help="output dir (default <folder>/_atelier_out)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--preview", action="store_true", help="ingest: analyze + sheets only, save nothing")
    ap.add_argument("--replace", metavar="ITEM_ID")
    ap.add_argument("--candidate", type=int)
    ap.add_argument("--image")
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--archive-current", action="store_true")
    ap.add_argument("--restore-archive", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--flatlay", action="store_true",
                    help="ingest: photos are flat-lay / cut-out garments with no person")
    ap.add_argument("--sandbox", metavar="DIR", help="use DIR as MEDIA_DIR + a JSON fake DB")
    a = ap.parse_args()

    media_dir = None
    if a.sandbox:
        media_dir = str(Path(a.sandbox).resolve())
        Path(media_dir).mkdir(parents=True, exist_ok=True)
        os.environ["MEDIA_DIR"] = media_dir               # before backend.config is imported
        print(f"SANDBOX: MEDIA_DIR={media_dir}, DB={media_dir}\\db.json (Mongo/GridFS untouched)")

    if a.make_manifest:
        return make_manifest(Path(a.make_manifest))

    db = _setup(a.sandbox)
    if a.backup:
        backup(db)
    if a.archive_current:
        _move(db, "items", "items_archive", a.dry_run, a.yes)
    if a.restore_archive:
        _move(db, "items_archive", "items", a.dry_run, a.yes)
    if a.ingest:
        folder = Path(a.ingest)
        manifest = Path(a.manifest) if a.manifest else folder / "manifest.csv"
        preview = a.preview or a.dry_run
        out = Path(a.out) if a.out else folder / ("_atelier_preview" if preview else "_atelier_out")
        ingest(db, folder, manifest, out, a.workers, preview, media_dir, a.flatlay)
    if a.replace:
        if a.candidate is None and not a.image:
            ap.error("--replace needs --candidate N and/or --image PATH")
        if not a.out:
            ap.error("--replace needs --out <the batch output dir>")
        replace(db, a.replace, Path(a.out), a.candidate, Path(a.image) if a.image else None)


if __name__ == "__main__":
    main()
