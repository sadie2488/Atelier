"""Local review tool: rate garment cutout quality against their source photos.

Read-only against the real database (`backend.db.get_db()["items"]`). Never writes to the
database or to any repo file. Renders one self-contained review.html (images embedded as
base64 data URIs) so it can be opened directly from disk, with no server needed.

Usage:
    .venv/Scripts/python.exe tools/review_cutouts.py [--out DIR]

Ratings are kept in the page itself via localStorage and can be exported as
cutout_ratings.json from the page ("Export ratings" button). This script does not read or
write ratings; it only builds the page fresh from the current closet each run.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
FIXTURES_DIR = REPO_ROOT / "fixtures" / "images"
DEFAULT_OUT = Path(
    r"C:\Users\sadie\AppData\Local\Temp\claude\c--Users-sadie-OneDrive-Desktop-Closet-Atelier"
    r"\98295bae-ee98-4c5d-afd9-1990e7a884db\scratchpad\review"
)

THUMB_HEIGHT = 360

# Category display order: bottoms first, then the rest alphabetically-ish by common sense.
CATEGORY_ORDER = ["bottoms", "tops", "jackets"]

HEX_SUFFIX_RE = re.compile(r"\s*#[0-9a-fA-F]{6}\s*$")
WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Collapse whitespace (tolerating double spaces) and lowercase for matching."""
    return WHITESPACE_RE.sub(" ", name).strip().lower()


def build_fixture_index() -> dict[str, Path]:
    """Map normalized retailer_item_name -> fixture photo path.

    Fixture filenames are "<retailer item name> #rrggbb.<ext>" (sometimes with no space, or a
    double space, before the '#'). Strip the trailing hex-color suffix and extension, then
    normalize whitespace to match against Item.retailer_item_name.
    """
    index: dict[str, Path] = {}
    if not FIXTURES_DIR.is_dir():
        return index
    for path in FIXTURES_DIR.iterdir():
        if not path.is_file():
            continue
        stem = path.stem
        stem = HEX_SUFFIX_RE.sub("", stem)
        key = normalize_name(stem)
        index[key] = path
    return index


def image_to_data_uri(data: bytes, *, checker_bg: bool = False) -> str:
    """Downscale to ~THUMB_HEIGHT tall and return a base64 data: URI.

    Cutouts keep their alpha channel (composited onto nothing, browser handles transparency);
    the checkerboard behind them is CSS, not baked into the image, so it stays crisp at any
    zoom and clearly shows leftover background / holes.
    """
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        if im.mode not in ("RGBA", "RGB"):
            im = im.convert("RGBA" if "A" in im.mode else "RGB")
        w, h = im.size
        if h > THUMB_HEIGHT:
            new_w = max(1, round(w * THUMB_HEIGHT / h))
            im = im.resize((new_w, THUMB_HEIGHT), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "PNG" if im.mode == "RGBA" else "PNG"
        im.save(buf, format=fmt)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"


def load_cutout_bytes(item_id: str) -> bytes | None:
    """Local media/items/<id>.png first (cache), else GridFS via backend.media_store."""
    from backend import config

    local_path = config.MEDIA_DIR / "items" / f"{item_id}.png"
    if local_path.is_file():
        return local_path.read_bytes()

    from backend import media_store

    return media_store.get(f"items/{item_id}.png")


def swatch_html(color: dict | None, label: str) -> str:
    if not color:
        return ""
    hexval = html.escape(color.get("hex", "#000000"))
    name = html.escape(color.get("display_name") or color.get("name") or hexval)
    return (
        '<div class="swatch">'
        f'<span class="swatch-color" style="background:{hexval}"></span>'
        f'<span class="swatch-label">{label}: {name} <code>{hexval}</code></span>'
        "</div>"
    )


def build_card(item: dict, fixture_index: dict[str, Path]) -> tuple[str, bool]:
    item_id = item.get("id", "unknown")
    category = item.get("category", "unknown")
    garment_type = item.get("garment_type", "unknown")
    retailer_name = item.get("retailer_item_name") or ""

    # source photo
    source_missing = True
    source_html = '<div class="ph missing">no source photo found</div>'
    if retailer_name:
        fixture_path = fixture_index.get(normalize_name(retailer_name))
        if fixture_path is not None:
            try:
                data = fixture_path.read_bytes()
                uri = image_to_data_uri(data)
                source_html = f'<img src="{uri}" alt="source photo">'
                source_missing = False
            except Exception as exc:  # pragma: no cover - defensive, surfaced in the page
                source_html = f'<div class="ph missing">source photo failed to load: {html.escape(str(exc))}</div>'

    # cutout
    cutout_html = '<div class="ph missing">no cutout found</div>'
    try:
        cutout_bytes = load_cutout_bytes(item_id)
    except Exception as exc:  # pragma: no cover - defensive
        cutout_bytes = None
        cutout_html = f'<div class="ph missing">cutout failed to load: {html.escape(str(exc))}</div>'
    if cutout_bytes:
        try:
            uri = image_to_data_uri(cutout_bytes)
            cutout_html = f'<img src="{uri}" alt="cutout">'
        except Exception as exc:  # pragma: no cover - defensive
            cutout_html = f'<div class="ph missing">cutout failed to decode: {html.escape(str(exc))}</div>'

    swatches = swatch_html(item.get("primary_color"), "primary") + swatch_html(
        item.get("secondary_color"), "secondary"
    )

    title = html.escape(retailer_name or item_id)
    meta = html.escape(f"{item_id} \u00b7 {category} / {garment_type}")

    card = f"""
    <div class="card" data-item-id="{html.escape(item_id)}">
      <div class="card-header">
        <div class="card-title">{title}</div>
        <div class="card-meta">{meta}</div>
      </div>
      <div class="panes">
        <div class="pane">
          <div class="pane-label">source</div>
          <div class="frame">{source_html}</div>
        </div>
        <div class="pane">
          <div class="pane-label">cutout</div>
          <div class="frame checker">{cutout_html}</div>
        </div>
        <div class="pane swatches-pane">
          <div class="pane-label">colors</div>
          {swatches or '<div class="ph missing">no colors</div>'}
        </div>
      </div>
      <div class="controls">
        <div class="rating-buttons">
          <button type="button" class="rate-btn" data-rating="good">Good</button>
          <button type="button" class="rate-btn" data-rating="ok">OK</button>
          <button type="button" class="rate-btn" data-rating="bad">Bad</button>
        </div>
        <label class="best-of">
          <input type="checkbox" class="best-of-checkbox">
          best of category
        </label>
        <textarea class="notes" placeholder="notes..." rows="2"></textarea>
      </div>
    </div>
    """
    return card, source_missing


PAGE_CSS = """
:root {
  color-scheme: light;
  --bg: #f5f5f3;
  --card-bg: #ffffff;
  --border: #ddd;
  --text: #1a1a1a;
  --muted: #6b6b6b;
  --good: #2e7d32;
  --ok: #b8860b;
  --bad: #c62828;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 16px;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
}
h1 { font-size: 1.3rem; margin: 0 0 4px; }
.subtitle { color: var(--muted); font-size: 0.85rem; margin: 0 0 12px; }
.summary-bar {
  position: sticky;
  top: 0;
  z-index: 5;
  background: var(--bg);
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 16px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.summary-text { font-weight: 600; }
.export-btn {
  margin-left: auto;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #222;
  color: #fff;
  cursor: pointer;
  font-size: 0.9rem;
}
.export-btn:hover { background: #000; }
.category-heading {
  font-size: 1.05rem;
  margin: 20px 0 10px;
  padding-bottom: 4px;
  border-bottom: 2px solid var(--border);
}
.grid { display: flex; flex-direction: column; gap: 14px; }
.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
}
.card.rated-good { border-left: 5px solid var(--good); }
.card.rated-ok { border-left: 5px solid var(--ok); }
.card.rated-bad { border-left: 5px solid var(--bad); }
.card-header { margin-bottom: 8px; }
.card-title { font-weight: 600; }
.card-meta { color: var(--muted); font-size: 0.78rem; }
.panes {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.pane-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin-bottom: 4px;
}
.frame {
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  background: #fafafa;
}
.frame img { max-width: 100%; max-height: 100%; object-fit: contain; }
.frame.checker {
  background-image:
    linear-gradient(45deg, #999 25%, transparent 25%),
    linear-gradient(-45deg, #999 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #999 75%),
    linear-gradient(-45deg, transparent 75%, #999 75%);
  background-size: 20px 20px;
  background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
  background-color: #444;
}
.ph.missing {
  color: #a33;
  font-size: 0.78rem;
  padding: 8px;
  text-align: center;
}
.swatches-pane { display: flex; flex-direction: column; gap: 6px; }
.swatch { display: flex; align-items: center; gap: 6px; font-size: 0.78rem; }
.swatch-color {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  border: 1px solid #0002;
  flex-shrink: 0;
}
.swatch-label code { font-size: 0.7rem; color: var(--muted); }
.controls {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.rating-buttons { display: flex; gap: 6px; }
.rate-btn {
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  font-size: 0.85rem;
}
.rate-btn[data-rating="good"].active { background: var(--good); color: #fff; border-color: var(--good); }
.rate-btn[data-rating="ok"].active { background: var(--ok); color: #fff; border-color: var(--ok); }
.rate-btn[data-rating="bad"].active { background: var(--bad); color: #fff; border-color: var(--bad); }
.best-of { display: flex; align-items: center; gap: 4px; font-size: 0.82rem; color: var(--muted); }
.notes {
  flex: 1 1 200px;
  min-width: 160px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: inherit;
  font-size: 0.82rem;
  resize: vertical;
}
@media (max-width: 700px) {
  .panes { grid-template-columns: 1fr; }
  .frame { height: 260px; }
  .summary-bar { flex-direction: column; align-items: stretch; }
  .export-btn { margin-left: 0; }
}
"""

PAGE_JS = r"""
(function () {
  var STORAGE_KEY = "atelier_cutout_ratings_v1";

  function safeGet() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function safeSet(data) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (e) {
      /* ignore (private browsing, quota, etc.) */
    }
  }

  var ratings = safeGet();

  function updateSummary() {
    var counts = { good: 0, ok: 0, bad: 0 };
    var cards = document.querySelectorAll(".card");
    cards.forEach(function (card) {
      var id = card.getAttribute("data-item-id");
      var r = ratings[id];
      if (r && r.rating && counts.hasOwnProperty(r.rating)) {
        counts[r.rating]++;
      }
    });
    var total = cards.length;
    var el = document.getElementById("summary-text");
    if (el) {
      el.textContent =
        counts.good + " good / " + counts.ok + " ok / " + counts.bad + " bad of " + total;
    }
    return counts;
  }

  function applyCardState(card) {
    var id = card.getAttribute("data-item-id");
    var r = ratings[id] || {};
    card.classList.remove("rated-good", "rated-ok", "rated-bad");
    if (r.rating) card.classList.add("rated-" + r.rating);
    card.querySelectorAll(".rate-btn").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-rating") === r.rating);
    });
    var notes = card.querySelector(".notes");
    if (notes) notes.value = r.notes || "";
    var bestOf = card.querySelector(".best-of-checkbox");
    if (bestOf) bestOf.checked = !!r.bestOf;
  }

  function saveCard(card) {
    var id = card.getAttribute("data-item-id");
    var activeBtn = card.querySelector(".rate-btn.active");
    var notes = card.querySelector(".notes");
    var bestOf = card.querySelector(".best-of-checkbox");
    ratings[id] = {
      rating: activeBtn ? activeBtn.getAttribute("data-rating") : null,
      notes: notes ? notes.value : "",
      bestOf: bestOf ? bestOf.checked : false,
    };
    safeSet(ratings);
    updateSummary();
  }

  document.querySelectorAll(".card").forEach(function (card) {
    applyCardState(card);

    card.querySelectorAll(".rate-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var alreadyActive = btn.classList.contains("active");
        card.querySelectorAll(".rate-btn").forEach(function (b) {
          b.classList.remove("active");
        });
        if (!alreadyActive) btn.classList.add("active");
        saveCard(card);
      });
    });

    var notes = card.querySelector(".notes");
    if (notes) {
      notes.addEventListener("input", function () {
        saveCard(card);
      });
    }

    var bestOf = card.querySelector(".best-of-checkbox");
    if (bestOf) {
      bestOf.addEventListener("change", function () {
        saveCard(card);
      });
    }
  });

  updateSummary();

  var exportBtn = document.getElementById("export-btn");
  if (exportBtn) {
    exportBtn.addEventListener("click", function () {
      var counts = updateSummary();
      var payload = {
        timestamp: new Date().toISOString(),
        summary: counts,
        ratings: ratings,
      };
      try {
        var blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "cutout_ratings.json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (e) {
        alert("Export failed: " + e);
      }
    });
  }
})();
"""


def build_html(items: list[dict], fixture_index: dict[str, Path]) -> tuple[str, int, int]:
    by_category: dict[str, list[dict]] = {}
    for item in items:
        by_category.setdefault(item.get("category", "unknown"), []).append(item)

    ordered_categories = [c for c in CATEGORY_ORDER if c in by_category]
    ordered_categories += sorted(c for c in by_category if c not in CATEGORY_ORDER)

    sections = []
    missing_source_count = 0
    for category in ordered_categories:
        cat_items = sorted(by_category[category], key=lambda it: it.get("id", ""))
        cards = []
        for item in cat_items:
            card_html, missing = build_card(item, fixture_index)
            cards.append(card_html)
            if missing:
                missing_source_count += 1
        sections.append(
            f'<h2 class="category-heading">{html.escape(category)} '
            f'<span style="color:#999;font-weight:400;font-size:0.8em;">'
            f"({len(cat_items)})</span></h2>"
            f'<div class="grid">{"".join(cards)}</div>'
        )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body_sections = "\n".join(sections)

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atelier cutout review</title>
<style>{PAGE_CSS}</style>
</head>
<body>
  <h1>Atelier cutout review</h1>
  <p class="subtitle">Generated {generated_at} &middot; {len(items)} items. Ratings are saved in this browser
    only (localStorage) &mdash; use Export to save them to a file.</p>
  <div class="summary-bar">
    <span class="summary-text" id="summary-text">0 good / 0 ok / 0 bad of {len(items)}</span>
    <button type="button" class="export-btn" id="export-btn">Export ratings</button>
  </div>
  {body_sections}
  <script>{PAGE_JS}</script>
</body>
</html>
"""
    return page, len(items), missing_source_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local HTML review page for closet cutouts.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory for review.html")
    args = parser.parse_args()

    from backend.db import get_db

    db = get_db()
    items = list(db["items"].find({}))
    for item in items:
        item.pop("_id", None)

    fixture_index = build_fixture_index()
    page, item_count, missing_source_count = build_html(items, fixture_index)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "review.html"
    out_path.write_text(page, encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    print(f"Wrote {out_path} ({item_count} items, {size_kb:.1f} KB, {missing_source_count} missing source photos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
