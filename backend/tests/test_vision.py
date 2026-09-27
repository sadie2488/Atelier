"""Vision lane tests. Offline (no mongomock, no network): the items collection is an
in-memory fake overriding `get_db`, like the styling lane's `fake_db` pattern. Segmentation and
color extraction run for real against fixtures/images/*.png (local MediaPipe models, already
cached under backend/vision/models/ -- no network call).

Category/garment_type is inferred from each fixture's filename per the vision lane brief:
jean/short/skirt -> bottoms; dress -> tops+dress; cardigan/sweater/top/polo/cami -> tops+shirt.
The true garment hex is the last #rrggbb in the filename (unused here; color-family agreement
is measured by backend/vision/scripts/eval_fixtures.py, not asserted in the test suite).
"""
from __future__ import annotations

import copy
import io
from pathlib import Path

import pytest

import numpy as np

from backend import config
from backend.db import get_db
from backend.main import app
from backend.vision.checks import _left_right_balance_ok, _no_straight_boundary_run
from backend.vision.segmentation import _bbox_fill_ratio
from backend.vision.session import delete_session, tmp_media_dir
from contract.enums import Category
from contract.schemas import AnalyzeResponse, ErrorResponse, Item, ItemListResponse

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "images"

# Two fixtures confirmed (by manual probe) to segment cleanly and quickly -- kept small so the
# suite stays fast; broader pass-rate reporting lives in eval_fixtures.py, not here.
BOTTOM_FIXTURE = "black Low-Rise Baggy Straight Jean #0f0f11.png"
TOP_FIXTURE = "bold black Off-the-Shoulder Sweater Mini Dress #181516.png"


def _multipart(filename: str, category: str, garment_type: str, color=None, item_name=None):
    data = (FIXTURES_DIR / filename).read_bytes()
    form = {"category": category, "garment_type": garment_type}
    if color is not None:
        form["color"] = color
    if item_name is not None:
        form["item_name"] = item_name
    files = {"image": (filename, io.BytesIO(data), "image/png")}
    return files, form


def _cleanup_media(handle: str | None = None, slug: str | None = None):
    if handle:
        delete_session(handle)
    if slug:
        p = config.MEDIA_DIR / "items" / f"{slug}.png"
        p.unlink(missing_ok=True)


# --------------------------------------------------------------------------------- fake db

class _FakeCollection:
    def __init__(self, docs=None):
        self._docs = docs or []

    def find(self, query=None):
        query = query or {}
        return [copy.deepcopy(d) for d in self._docs if all(d.get(k) == v for k, v in query.items())]

    def find_one(self, query=None):
        query = query or {}
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                return copy.deepcopy(d)
        return None

    def insert_one(self, doc):
        self._docs.append(copy.deepcopy(doc))


@pytest.fixture
def fake_db(client):
    holder = {"items": _FakeCollection()}
    app.dependency_overrides[get_db] = lambda: holder
    yield holder
    app.dependency_overrides.pop(get_db, None)


# --------------------------------------------------------------------------------- analyze

def test_analyze_returns_three_distinct_candidates_and_validates(client, fake_db):
    files, form = _multipart(BOTTOM_FIXTURE, "bottoms", "pants")
    resp = client.post("/api/items/analyze", files=files, data=form)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    validated = AnalyzeResponse.model_validate(body)
    assert [c.index for c in validated.candidates] == [0, 1, 2]
    assert [c.variant.value for c in validated.candidates] == ["tight", "balanced", "generous"]
    urls = {c.cutout_url for c in validated.candidates}
    assert len(urls) == 3   # V-E1: three distinct cutouts
    _cleanup_media(handle=validated.temp_handle)


def test_analyze_persists_nothing(client, fake_db):
    files, form = _multipart(BOTTOM_FIXTURE, "bottoms", "pants")
    resp = client.post("/api/items/analyze", files=files, data=form)
    assert resp.status_code == 200
    handle = resp.json()["temp_handle"]
    assert fake_db["items"].find() == []   # V-E3
    _cleanup_media(handle=handle)


def test_analyze_invalid_category_garment_type_pair_is_400(client, fake_db):
    files, form = _multipart(BOTTOM_FIXTURE, "bottoms", "shirt")   # not a valid pair
    resp = client.post("/api/items/analyze", files=files, data=form)
    assert resp.status_code == 400
    err = ErrorResponse.model_validate(resp.json())
    assert err.error.code.value == "invalid_request"


def test_analyze_undecodable_image_is_unsupported_image(client, fake_db):
    files = {"image": ("bad.png", io.BytesIO(b"not an image"), "image/png")}
    form = {"category": "bottoms", "garment_type": "pants"}
    resp = client.post("/api/items/analyze", files=files, data=form)
    assert resp.status_code == 415
    err = ErrorResponse.model_validate(resp.json())
    assert err.error.code.value == "unsupported_image"


# --------------------------------------------------------------------------------- save

def test_save_persists_item_with_correct_slug_and_cutout(client, fake_db):
    files, form = _multipart(BOTTOM_FIXTURE, "bottoms", "pants", color="Indigo", item_name="Straight Jean")
    analyze_resp = client.post("/api/items/analyze", files=files, data=form)
    assert analyze_resp.status_code == 200
    handle = analyze_resp.json()["temp_handle"]

    save_resp = client.post("/api/items/save", json={"temp_handle": handle, "candidate_index": 1})
    assert save_resp.status_code == 200, save_resp.text
    item = Item.model_validate(save_resp.json())
    assert item.id.startswith("bottom_")
    assert item.category.value == "bottoms"
    assert item.garment_type.value == "pants"
    assert item.cutout_url == f"/media/items/{item.id}.png"
    assert item.retailer_color == "Indigo"
    assert item.retailer_item_name == "Straight Jean"
    assert (config.MEDIA_DIR / "items" / f"{item.id}.png").exists()
    assert fake_db["items"].find_one({"id": item.id}) is not None

    # V-E2/V-A3: nothing left under the temp handle after save
    tmp_dir = tmp_media_dir()
    assert not (tmp_dir / f"{handle}_0.png").exists()
    assert not (tmp_dir / f"{handle}_1.png").exists()
    assert not (tmp_dir / f"{handle}_2.png").exists()

    _cleanup_media(slug=item.id)


def test_save_persists_cutout_to_durable_media_store(client, fake_db, memory_media):
    files, form = _multipart(BOTTOM_FIXTURE, "bottoms", "pants")
    analyze_resp = client.post("/api/items/analyze", files=files, data=form)
    handle = analyze_resp.json()["temp_handle"]

    save_resp = client.post("/api/items/save", json={"temp_handle": handle, "candidate_index": 0})
    assert save_resp.status_code == 200, save_resp.text
    item_id = save_resp.json()["id"]

    assert memory_media[f"items/{item_id}.png"] == (config.MEDIA_DIR / "items" / f"{item_id}.png").read_bytes()

    _cleanup_media(slug=item_id)


def test_save_returns_internal_error_and_inserts_nothing_when_persist_fails(
    client, fake_db, monkeypatch,
):
    from backend import media_store

    def _boom(path):
        raise RuntimeError("gridfs unavailable")

    monkeypatch.setattr(media_store, "persist", _boom)

    files, form = _multipart(BOTTOM_FIXTURE, "bottoms", "pants")
    analyze_resp = client.post("/api/items/analyze", files=files, data=form)
    handle = analyze_resp.json()["temp_handle"]

    save_resp = client.post("/api/items/save", json={"temp_handle": handle, "candidate_index": 0})
    assert save_resp.status_code == 500, save_resp.text
    err = ErrorResponse.model_validate(save_resp.json())
    assert err.error.code.value == "internal_error"
    assert fake_db["items"].find() == []

    # cutout file was moved to media/items/ even though persist failed; clean it up by slug
    # pattern isn't known (insert never happened), so sweep the dir for this test's leftover.
    for p in (config.MEDIA_DIR / "items").glob("bottom_*.png"):
        p.unlink(missing_ok=True)


def test_save_unknown_handle_is_handle_expired(client, fake_db):
    resp = client.post("/api/items/save", json={"temp_handle": "tmp_deadbeef0000", "candidate_index": 0})
    assert resp.status_code == 410
    err = ErrorResponse.model_validate(resp.json())
    assert err.error.code.value == "handle_expired"


# --------------------------------------------------------------------------------- reject

def test_reject_persists_nothing_and_logs(client, fake_db, monkeypatch, tmp_path):
    log_path = tmp_path / "rejections.jsonl"
    monkeypatch.setattr(config, "FAILURE_LOG", log_path)

    files, form = _multipart(TOP_FIXTURE, "tops", "dress")
    analyze_resp = client.post("/api/items/analyze", files=files, data=form)
    assert analyze_resp.status_code == 200
    handle = analyze_resp.json()["temp_handle"]

    reject_resp = client.post("/api/items/reject", json={"temp_handle": handle})
    assert reject_resp.status_code == 200
    assert reject_resp.json() == {"ok": True}
    assert fake_db["items"].find() == []

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json
    entry = json.loads(lines[0])
    assert entry["event"] == "reject_all"
    assert entry["temp_handle"] == handle
    assert len(entry["candidates"]) == 3

    # nothing retained
    tmp_dir = tmp_media_dir()
    for i in range(3):
        assert not (tmp_dir / f"{handle}_{i}.png").exists()


# --------------------------------------------------------------------------------- list/get

def test_list_and_get_item(client, fake_db):
    files, form = _multipart(BOTTOM_FIXTURE, "bottoms", "pants")
    analyze_resp = client.post("/api/items/analyze", files=files, data=form)
    handle = analyze_resp.json()["temp_handle"]
    save_resp = client.post("/api/items/save", json={"temp_handle": handle, "candidate_index": 0})
    item_id = save_resp.json()["id"]

    list_resp = client.get("/api/items")
    assert list_resp.status_code == 200
    validated = ItemListResponse.model_validate(list_resp.json())
    assert any(i.id == item_id for i in validated.items)

    filtered_resp = client.get("/api/items", params={"category": "bottoms"})
    assert filtered_resp.status_code == 200
    assert all(i.category.value == "bottoms" for i in ItemListResponse.model_validate(filtered_resp.json()).items)

    empty_filtered = client.get("/api/items", params={"category": "jackets"})
    assert ItemListResponse.model_validate(empty_filtered.json()).items == []

    get_resp = client.get(f"/api/items/{item_id}")
    assert get_resp.status_code == 200
    Item.model_validate(get_resp.json())

    _cleanup_media(slug=item_id)


def test_get_unknown_item_is_not_found(client, fake_db):
    resp = client.get("/api/items/top_ffffff")
    assert resp.status_code == 404
    err = ErrorResponse.model_validate(resp.json())
    assert err.error.code.value == "not_found"


# --------------------------------------------------------------------------------- V-Q2 checks

def test_no_straight_boundary_run_flags_a_hard_edge_cut():
    # A perfect rectangle has a flat top/bottom edge the full canvas width -- an axis-aligned
    # box cut, exactly what this check exists to catch.
    mask = np.zeros((50, 50), dtype=bool)
    mask[10:40, :] = True
    assert _no_straight_boundary_run(mask) is False


def test_no_straight_boundary_run_passes_a_diamond():
    # A diamond's boundary moves by one column every row: no flat run anywhere near 15% of
    # the canvas width (50 * 0.15 = 7.5).
    n = 50
    mask = np.zeros((n, n), dtype=bool)
    c = n // 2
    for y in range(n):
        half = c - abs(y - c)
        if half > 0:
            mask[y, c - half:c + half] = True
    assert _no_straight_boundary_run(mask) is True


def test_left_right_balance_flags_lopsided_tops_and_bottoms_only():
    mask = np.zeros((10, 10), dtype=bool)
    mask[:, :3] = True   # all mass on the left third; nothing on the right half at all
    assert _left_right_balance_ok(mask, Category.tops) is False
    assert _left_right_balance_ok(mask, Category.bottoms) is False
    # Jackets are legitimately asymmetric (open front, angled shot) -- not checked.
    assert _left_right_balance_ok(mask, Category.jackets) is True


def test_left_right_balance_passes_a_symmetric_mask():
    mask = np.zeros((10, 10), dtype=bool)
    mask[:, 2:8] = True   # centered, even split
    assert _left_right_balance_ok(mask, Category.tops) is True


# --------------------------------------------------------------------------------- V2 checks

def test_bbox_fill_ratio_flags_a_rectangle_but_not_an_irregular_silhouette():
    # V2 (tight waist-down crops, re-dispatch): a mask that fills its own bbox wall-to-wall is
    # exactly the "the mask IS the region/crop box" failure mode -- no garment silhouette was
    # actually carved out of it (see candidate_params.RECTANGULAR_BBOX_FILL_MAX's docstring).
    rect = np.zeros((20, 20), dtype=bool)
    rect[2:18, 2:18] = True
    assert _bbox_fill_ratio(rect) == pytest.approx(1.0)

    # A real garment silhouette (tapered, with corners cut away) never fills its own bbox
    # completely -- a diamond is a clean stand-in.
    n = 20
    diamond = np.zeros((n, n), dtype=bool)
    c = n // 2
    for y in range(n):
        half = c - abs(y - c)
        if half > 0:
            diamond[y, c - half:c + half] = True
    assert _bbox_fill_ratio(diamond) < 0.9


def test_bbox_fill_ratio_of_empty_mask_is_zero():
    assert _bbox_fill_ratio(np.zeros((5, 5), dtype=bool)) == 0.0


def test_list_items_newest_first(client, fake_db):
    fake_db["items"] = _FakeCollection([
        {"id": "top_000001", "category": "tops", "garment_type": "shirt",
         "cutout_url": "/media/items/top_000001.png",
         "primary_color": {"lab": [50, 0, 0], "lch": [50, 0, 0], "hex": "#808080",
                            "name": "unmapped", "family": "unmapped", "is_neutral": True,
                            "everyday_neutral": False},
         "secondary_color": None, "retailer_color": None, "retailer_item_name": None,
         "attributes": {}, "created_at": "2026-01-01T00:00:00Z"},
        {"id": "top_000002", "category": "tops", "garment_type": "shirt",
         "cutout_url": "/media/items/top_000002.png",
         "primary_color": {"lab": [50, 0, 0], "lch": [50, 0, 0], "hex": "#808080",
                            "name": "unmapped", "family": "unmapped", "is_neutral": True,
                            "everyday_neutral": False},
         "secondary_color": None, "retailer_color": None, "retailer_item_name": None,
         "attributes": {}, "created_at": "2026-06-01T00:00:00Z"},
    ])
    resp = client.get("/api/items")
    validated = ItemListResponse.model_validate(resp.json())
    assert [i.id for i in validated.items] == ["top_000002", "top_000001"]


def test_stray_color_rule_drops_foreign_patch_keeps_stripe_band():
    """top_8cfe59: a small detached denim-blue patch near the hem is dropped; a small detached
    cream stripe band of the garment's own color is kept."""
    import numpy as np
    from backend.vision.segmentation import _drop_stray_components

    h, w = 200, 100
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[:] = (220, 210, 185)  # cream garment
    mask = np.zeros((h, w), bool)
    mask[10:100, 10:90] = True     # main body
    mask[110:190, 70:90] = True    # sleeve (large piece)
    mask[120:130, 10:60] = True    # small cream stripe band, low in the extent
    mask[160:185, 10:40] = True    # small patch in the bottom region...
    rgb[160:185, 10:40] = (170, 200, 225)  # ...colored light-blue denim
    out = _drop_stray_components(mask, rgb)
    assert out[120:130, 10:60].all()
    assert not out[160:185, 10:40].any()
    assert out[10:100, 10:90].all() and out[110:190, 70:90].all()
    # without rgb the geometric rule alone keeps the patch (unchanged behavior)
    assert _drop_stray_components(mask)[160:185, 10:40].all()


# ---------------------------------------------------------------- 2.3.0: PATCH /items/{slug} rename

def test_rename_item_changes_only_the_name(client, memory_db):
    import json
    from pathlib import Path
    from contract.schemas import Item
    fx = Path(__file__).resolve().parents[2] / "contract" / "fixtures" / "api" / "get_items_detail.response.json"
    doc = json.loads(fx.read_text(encoding="utf-8"))
    memory_db["items"].insert_one(dict(doc))
    r = client.patch(f"/api/items/{doc['id']}", json={"name": "  My green dress  "})
    assert r.status_code == 200, r.text
    out = Item.model_validate(r.json())
    assert out.retailer_item_name == "My green dress"
    assert out.id == doc["id"] and out.primary_color.hex == doc["primary_color"]["hex"]
    assert client.get(f"/api/items/{doc['id']}").json()["retailer_item_name"] == "My green dress"


def test_rename_item_errors(client, memory_db):
    assert client.patch("/api/items/top_000000", json={"name": "x"}).json()["error"]["code"] == "not_found"
    r = client.patch("/api/items/top_000000", json={"name": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_edit_item_attributes_merge_and_remove(client, memory_db):
    import json
    from pathlib import Path
    from contract.schemas import Item
    fx = Path(__file__).resolve().parents[2] / "contract" / "fixtures" / "api" / "get_items_detail.response.json"
    doc = json.loads(fx.read_text(encoding="utf-8"))
    doc["attributes"] = {"material": "wool", "fit": "loose"}
    memory_db["items"].insert_one(dict(doc))
    r = client.patch(f"/api/items/{doc['id']}", json={"attributes": {"material": "Mohair blend", "fit": "", "vibe": "cozy"}})
    assert r.status_code == 200, r.text
    out = Item.model_validate(r.json())
    assert out.attributes == {"material": "Mohair blend", "vibe": "cozy"}
    assert out.retailer_item_name == doc.get("retailer_item_name")


def test_edit_item_needs_something_to_change(client, memory_db):
    r = client.patch("/api/items/top_000000", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


# --------------------------------------------------------------------------------- flat-lay + auto-tagging

FLATLAY_FIXTURE = Path(__file__).resolve().parents[2] / "media" / "_closet_new" / "29_grey_tee.png"


def _flatlay_analyze_and_save(client):
    if not FLATLAY_FIXTURE.exists():
        pytest.skip("flat-lay fixture not present")
    files = {"image": ("tee.png", io.BytesIO(FLATLAY_FIXTURE.read_bytes()), "image/png")}
    r = client.post("/api/items/analyze", files=files, data={"category": "tops", "garment_type": "shirt"})
    assert r.status_code == 200, r.text
    resp = AnalyzeResponse.model_validate(r.json())
    assert len(resp.candidates) == 3
    s = client.post("/api/items/save", json={"temp_handle": resp.temp_handle, "candidate_index": 1})
    assert s.status_code == 200, s.text
    return Item.model_validate(s.json())


def test_flatlay_upload_falls_back_and_saves(client, fake_db):
    item = _flatlay_analyze_and_save(client)
    assert item.id.startswith("top_")
    assert item.attributes == {}          # no key in tests -> Gemini skipped, degraded state
    assert fake_db["items"].find_one({"id": item.id}) is not None
    _cleanup_media(slug=item.id)


def test_auto_tagging_stores_filtered_attributes(client, fake_db, monkeypatch):
    import json
    from backend.vision import tagging

    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")
    payload = {"subcategory": "T-Shirt ", "sleeve": "short", "fit": "regular", "formality": "casual",
               "bogus": "x", "material": "y" * 61, "pattern": 3}
    monkeypatch.setattr(tagging, "_call", lambda data, cat: json.dumps(payload))
    item = _flatlay_analyze_and_save(client)
    expected = {"subcategory": "t-shirt", "sleeve": "short", "fit": "regular", "formality": "casual"}
    assert item.attributes == expected
    assert fake_db["items"].find_one({"id": item.id})["attributes"] == expected
    _cleanup_media(slug=item.id)


def test_auto_tagging_failure_still_saves_without_attributes(client, fake_db, monkeypatch):
    from backend.vision import tagging

    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")

    def _boom(data, cat):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(tagging, "_call", _boom)
    item = _flatlay_analyze_and_save(client)
    assert item.attributes == {}
    assert fake_db["items"].find_one({"id": item.id}) is not None
    _cleanup_media(slug=item.id)
