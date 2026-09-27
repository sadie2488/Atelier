"""Avatar lane tests (A1-A7). Fast and offline: pose-validation logic is tested directly on
constructed landmark dicts; the scan endpoint uses monkeypatched detection except for two real
MediaPipe runs against fixture photos (no full-body fixture exists yet -- see the lane report).

A7 (generation) never makes a real network call in tests: `_no_network_generation` below is
autouse and replaces `gen_client.generate_tryon` with something that raises, for every test in
this file, unless a test explicitly monkeypatches it back to something else. A real
GEMINI_API_KEY is configured in this environment (backend/.env), so without this guard, any test
that scans an avatar and renders would silently place a real, billed Gemini call.
"""
import io
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend import config
from backend.avatar import background, compositing, gen_client, ids, service, verify
from backend.avatar.pose_validation import ARMS_MESSAGE, STEP_BACK_MESSAGE, validate
from backend.avatar.rig import compute_rig, translate, canvas_bbox
from backend.avatar.draw import draw_avatar, draw_wireframe
from contract.enums import GarmentType

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "images"


@pytest.fixture(autouse=True)
def _no_network_generation(monkeypatch):
    def _blocked(*a, **k):
        raise gen_client.GenerationError("blocked in tests -- monkeypatch generate_tryon")
    monkeypatch.setattr(gen_client, "generate_tryon", _blocked)


def _wait_until(predicate, timeout=2.0, interval=0.01):
    """Poll a background job's result without sleeping longer than necessary."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("timed out waiting for the background render job")


def _wait_for_settled(renders_collection, render_id, timeout=2.0):
    """-> the render doc once its status is no longer `pending`."""
    def _check():
        doc = renders_collection.find_one({"render_id": render_id})
        return doc if doc and doc["status"] != "pending" else None
    return _wait_until(_check, timeout=timeout)


# ---------------------------------------------------------------- landmark builders

def _good_landmarks():
    return {
        "nose": (200.0, 80.0, 0.99),
        "left_shoulder": (250.0, 150.0, 0.99), "right_shoulder": (150.0, 150.0, 0.99),
        "left_elbow": (350.0, 160.0, 0.99), "right_elbow": (50.0, 160.0, 0.99),
        "left_wrist": (400.0, 170.0, 0.99), "right_wrist": (10.0, 170.0, 0.99),
        "left_hip": (230.0, 400.0, 0.99), "right_hip": (170.0, 400.0, 0.99),
        "left_knee": (230.0, 560.0, 0.99), "right_knee": (170.0, 560.0, 0.99),
        "left_ankle": (230.0, 700.0, 0.99), "right_ankle": (170.0, 700.0, 0.99),
    }


def _synthetic_png_bytes(color=(200, 150, 120), size=(64, 128)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# _good_landmarks() spans roughly x:[0,400] y:[80,700] -- A7 tests need a "source photo" big
# enough that those coordinates (and generation/verification sampling around them) land inside
# the image instead of being clipped to nothing.
PERSON_PHOTO_SIZE = (420, 720)


# ---------------------------------------------------------------- A1: pose validation

def test_pose_accepts_good_standing_pose():
    assert validate(_good_landmarks()) is None


def test_pose_rejects_missing_landmarks_with_actionable_reason():
    lm = _good_landmarks()
    lm["left_ankle"] = (230.0, 700.0, 0.1)  # out of frame / not visible
    result = validate(lm)
    assert result == (result[0], STEP_BACK_MESSAGE)
    assert result[0].value == "pose_rejected"


def test_pose_rejects_arms_close_to_body_with_actionable_reason():
    lm = _good_landmarks()
    lm["left_elbow"] = (245.0, 200.0, 0.99)  # nearly in line with the torso, not away from it
    result = validate(lm)
    assert result == (result[0], ARMS_MESSAGE)
    assert result[0].value == "pose_rejected"


@pytest.mark.parametrize("image_name", [
    # The closest fixture to "full body, front-facing" available (see lane report: none of
    # fixtures/images/ actually spans shoulders-to-ankles -- these are garment product photos).
    "leaf green short-sleev midi dress #105243.png",
])
def test_real_photo_with_cropped_legs_is_pose_rejected(image_name):
    """Real MediaPipe run (no mocking): a photo cropped above the ankles must be rejected, not
    silently accepted with bad placement anchors."""
    rgb = np.asarray(Image.open(FIXTURES / image_name).convert("RGB"))
    from backend.avatar.landmarks import detect_landmarks
    landmarks = detect_landmarks(rgb)
    assert landmarks is not None
    result = validate(landmarks)
    assert result is not None
    assert result[0].value == "pose_rejected"
    assert result[1] == STEP_BACK_MESSAGE


def test_real_blank_image_has_no_person_detected():
    from backend.avatar.landmarks import detect_landmarks
    blank = np.full((400, 300, 3), 30, dtype=np.uint8)
    assert detect_landmarks(blank) is None


# ---------------------------------------------------------------- A2/A3: rig + assembly

def test_rig_and_avatar_assembly_deterministic():
    lm = _good_landmarks()
    rig = compute_rig(lm)
    x0, y0, x1, y1 = canvas_bbox(rig)
    w, h = max(1, round(x1 - x0)), max(1, round(y1 - y0))
    local = translate(rig, -x0, -y0)

    wf1 = draw_wireframe(local, (w, h)).tobytes()
    wf2 = draw_wireframe(local, (w, h)).tobytes()
    assert wf1 == wf2

    av1 = draw_avatar(local, (w, h), (210, 180, 160), None).tobytes()
    av2 = draw_avatar(local, (w, h), (210, 180, 160), None).tobytes()
    assert av1 == av2
    # The wireframe is a strict outline; the assembled avatar additionally fills the body, so
    # it must not be pixel-identical to the wireframe alone.
    assert av1 != wf1


def test_missing_landmarks_are_not_a_valid_rig_input():
    """A-B8: there is no rung below landmarks -- compute_rig requires all of them present."""
    lm = _good_landmarks()
    del lm["left_hip"]
    with pytest.raises(KeyError):
        compute_rig(lm)


# ---------------------------------------------------------------- helpers shared by A4/A5/A6

def _solid_cutout(color, size=(120, 300)):
    return Image.new("RGBA", size, (*color, 255))


def _avatar_doc_from_good_pose():
    lm = _good_landmarks()
    rig = compute_rig(lm)
    x0, y0, x1, y1 = canvas_bbox(rig)
    w, h = max(1, round(x1 - x0)), max(1, round(y1 - y0))
    local = translate(rig, -x0, -y0)
    from backend.avatar.rig import rig_to_dict
    return local, (w, h), rig_to_dict(local)


def _write_item(media_dir: Path, slug: str, garment_type: GarmentType, color, anchors, size=(120, 300)):
    cutout = _solid_cutout(color, size)
    items_dir = media_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    cutout.save(items_dir / f"{slug}.png")
    return {
        "id": slug,
        "cutout_url": f"/media/items/{slug}.png",
        "garment_type": garment_type.value,
        "anchors": anchors,
    }


# ---------------------------------------------------------------- A4/A5: placement + compositing

def test_composite_draw_order_bottom_top_jacket(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    rig, canvas_size, _rig_dict = _avatar_doc_from_good_pose()

    # Anchors normalized to a 120x300 cutout, positioned so all three garments fully overlap
    # the shoulder/hip span -- draw order is the only thing under test here.
    shoulder_hip_anchors = {
        "left_shoulder": [0.9, 0.0], "right_shoulder": [0.1, 0.0],
        "left_hip": [0.9, 1.0], "right_hip": [0.1, 1.0],
    }
    bottom_item = _write_item(tmp_path, "bottom_000001", GarmentType.pants, (0, 0, 255), {
        "left_hip": [0.9, 0.0], "right_hip": [0.1, 0.0],
        "left_knee": [0.9, 0.5], "right_knee": [0.1, 0.5],
        "left_ankle": [0.9, 1.0], "right_ankle": [0.1, 1.0],
    })
    top_item = _write_item(tmp_path, "top_000001", GarmentType.shirt, (0, 255, 0), shoulder_hip_anchors)
    jacket_item = _write_item(tmp_path, "jacket_000001", GarmentType.jacket, (255, 0, 0), shoulder_hip_anchors)

    avatar_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    from backend.avatar.service import _load_item_layer
    composed = compositing.composite_outfit(
        avatar_img, canvas_size, rig,
        bottom=_load_item_layer(bottom_item), top=_load_item_layer(top_item), jacket=_load_item_layer(jacket_item),
    )
    # Sample a point inside the shoulder/hip span, where all three garments overlap: the
    # topmost layer (jacket, drawn last) must win.
    sample_x, sample_y = round(rig.shoulder_mid[0]), round((rig.shoulder_mid[1] + rig.hip_mid[1]) / 2)
    assert composed.getpixel((sample_x, sample_y))[:3] == (255, 0, 0)


def test_dress_layers_over_bottom_no_exclusion(tmp_path, monkeypatch):
    """A-R5: a dress is a top; it must still show over the bottom, not exclude it elsewhere."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    rig, canvas_size, _ = _avatar_doc_from_good_pose()

    bottom_item = _write_item(tmp_path, "bottom_000002", GarmentType.pants, (0, 0, 255), {
        "left_hip": [0.9, 0.0], "right_hip": [0.1, 0.0],
        "left_knee": [0.9, 0.5], "right_knee": [0.1, 0.5],
        "left_ankle": [0.9, 1.0], "right_ankle": [0.1, 1.0],
    }, size=(120, 320))
    dress_item = _write_item(tmp_path, "dress_000001", GarmentType.dress, (0, 255, 0), {
        "left_shoulder": [0.9, 0.0], "right_shoulder": [0.1, 0.0],
        "left_hip": [0.9, 0.5], "right_hip": [0.1, 0.5],
        "left_ankle": [0.9, 1.0], "right_ankle": [0.1, 1.0],
    }, size=(120, 320))

    avatar_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    from backend.avatar.service import _load_item_layer
    composed = compositing.composite_outfit(
        avatar_img, canvas_size, rig,
        bottom=_load_item_layer(bottom_item), top=_load_item_layer(dress_item),
    )
    sample_x, sample_y = round(rig.shoulder_mid[0]), round((rig.shoulder_mid[1] + rig.hip_mid[1]) / 2)
    assert composed.getpixel((sample_x, sample_y))[:3] == (0, 255, 0)  # dress wins over the torso


def test_placement_falls_back_when_anchor_missing(tmp_path, monkeypatch, capsys):
    """A4: a missing required anchor logs and falls back instead of failing the render."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    rig, canvas_size, _ = _avatar_doc_from_good_pose()
    item = _write_item(tmp_path, "top_000002", GarmentType.shirt, (9, 9, 9), {})  # no anchors at all
    from backend.avatar.service import _load_item_layer
    from backend.avatar.placement import place_item
    cutout, anchors, garment_type = _load_item_layer(item)
    layer = place_item(cutout, anchors, garment_type, rig, canvas_size)  # must not raise
    assert layer.size == canvas_size
    assert "fallback" in capsys.readouterr().out


# ---------------------------------------------------------------- A6: render endpoint

def _scan_ok(monkeypatch, client, memory_db, image_bytes=None):
    monkeypatch.setattr("backend.avatar.service.detect_landmarks", lambda rgb: _good_landmarks())
    monkeypatch.setattr("backend.avatar.service.face", type("F", (), {
        "detect_face_box": staticmethod(lambda rgb: None),
    }))
    resp = client.post(
        "/api/avatar/scan",
        files={"image": ("photo.png", image_bytes or _synthetic_png_bytes(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_scan_endpoint_happy_path(client, memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    body = _scan_ok(monkeypatch, client, memory_db)
    assert body["avatar_id"].startswith("avatar_")
    assert body["wireframe_url"].startswith("/media/avatars/")
    assert body["avatar_url"].startswith("/media/avatars/")
    for url in (body["wireframe_url"], body["avatar_url"]):
        assert (tmp_path / url[len("/media/"):]).is_file()

    get_resp = client.get(f"/api/avatar/{body['avatar_id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["avatar_id"] == body["avatar_id"]


def test_scan_endpoint_pose_rejected_response_shape(client, memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    bad_landmarks = _good_landmarks()
    bad_landmarks["left_elbow"] = (245.0, 200.0, 0.99)
    monkeypatch.setattr("backend.avatar.service.detect_landmarks", lambda rgb: bad_landmarks)
    resp = client.post(
        "/api/avatar/scan",
        files={"image": ("photo.png", _synthetic_png_bytes(), "image/png")},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "pose_rejected"
    assert body["error"]["message"] == ARMS_MESSAGE


def test_scan_endpoint_unsupported_image(client, memory_db):
    resp = client.post("/api/avatar/scan", files={"image": ("photo.png", b"not an image", "image/png")})
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_image"


def test_get_unknown_avatar_is_not_found(client, memory_db):
    resp = client.get("/api/avatar/avatar_ffffff")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def _seed_items(memory_db, tmp_path):
    top = _write_item(tmp_path, "top_aaaaaa", GarmentType.shirt, (0, 255, 0), {
        "left_shoulder": [0.9, 0.0], "right_shoulder": [0.1, 0.0],
        "left_hip": [0.9, 1.0], "right_hip": [0.1, 1.0],
    })
    bottom = _write_item(tmp_path, "bottom_bbbbbb", GarmentType.pants, (0, 0, 255), {
        "left_hip": [0.9, 0.0], "right_hip": [0.1, 0.0],
        "left_knee": [0.9, 0.5], "right_knee": [0.1, 0.5],
        "left_ankle": [0.9, 1.0], "right_ankle": [0.1, 1.0],
    })
    memory_db["items"].insert_one(top)
    memory_db["items"].insert_one(bottom)
    return top, bottom


def test_render_endpoint_local_composite_and_cache(client, memory_db, monkeypatch, tmp_path):
    """The local composite path (A1-A6), with generation "possible" (a real key is configured)
    but blocked by the autouse fixture -- exercises the full pending -> failed settle, not just
    the pre-A7 shortcut.
    """
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    avatar = _scan_ok(monkeypatch, client, memory_db)
    _seed_items(memory_db, tmp_path)

    body = {"avatar_id": avatar["avatar_id"], "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb", "jacket_id": None}

    t0 = time.perf_counter()
    resp1 = client.post("/api/render", json=body)
    cold_ms = (time.perf_counter() - t0) * 1000
    assert resp1.status_code == 200, resp1.text
    job1 = resp1.json()
    assert job1["status"] == "pending"         # a real key + source photo -> generation attempted
    assert job1["generated_url"] is None
    assert job1["local_url"].startswith("/media/renders/")
    assert (tmp_path / job1["local_url"][len("/media/"):]).is_file()
    assert cold_ms < 1500, f"cold composite took {cold_ms:.0f}ms"

    render_id = job1["render_id"]
    settled = _wait_for_settled(memory_db["renders"], render_id)
    assert settled["status"] == "failed"       # generate_tryon is blocked in tests -- see autouse fixture
    assert settled["generated_url"] is None

    real_render = service.render
    calls = []
    monkeypatch.setattr(service, "render", lambda *a, **k: calls.append(1) or real_render(*a, **k))

    t1 = time.perf_counter()
    resp2 = client.post("/api/render", json=body)
    cached_ms = (time.perf_counter() - t1) * 1000
    assert resp2.status_code == 200
    job2 = resp2.json()
    assert job2["render_id"] == render_id
    assert job2["status"] == "failed"
    assert calls == [], "cache hit must not recompute the composite"
    assert cached_ms < 200, f"cached lookup took {cached_ms:.0f}ms"

    get_resp = client.get(f"/api/render/{render_id}")
    assert get_resp.status_code == 200
    assert get_resp.json() == job2


def test_render_unknown_avatar_is_not_found(client, memory_db):
    resp = client.post("/api/render", json={
        "avatar_id": "avatar_ffffff", "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb",
    })
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_render_unknown_item_is_not_found(client, memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    avatar = _scan_ok(monkeypatch, client, memory_db)
    resp = client.post("/api/render", json={
        "avatar_id": avatar["avatar_id"], "top_id": "top_ffffff", "bottom_id": "bottom_bbbbbb",
    })
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_render_id_is_deterministic_cache_key():
    a = ids.render_id_for("avatar_abc123", "top_1", "bottom_1", None)
    b = ids.render_id_for("avatar_abc123", "top_1", "bottom_1", None)
    c = ids.render_id_for("avatar_abc123", "top_1", "bottom_1", "jacket_1")
    assert a == b
    assert a != c
    assert a.startswith("render_") and len(a) == len("render_") + 12


# ---------------------------------------------------------------- A7: generation + verification

from contract.tools.color import hex_to_lab  # noqa: E402 -- test-only, computes expected Lab

RED_LAB = list(hex_to_lab("#ff0000"))
BLUE_LAB = list(hex_to_lab("#0000ff"))
GREEN_LAB = list(hex_to_lab("#00ff00"))


def _seed_colored_items(memory_db, tmp_path, top_lab, bottom_lab):
    top = _write_item(tmp_path, "top_aaaaaa", GarmentType.shirt, (0, 255, 0), {
        "left_shoulder": [0.9, 0.0], "right_shoulder": [0.1, 0.0],
        "left_hip": [0.9, 1.0], "right_hip": [0.1, 1.0],
    })
    bottom = _write_item(tmp_path, "bottom_bbbbbb", GarmentType.pants, (0, 0, 255), {
        "left_hip": [0.9, 0.0], "right_hip": [0.1, 0.0],
        "left_knee": [0.9, 0.5], "right_knee": [0.1, 0.5],
        "left_ankle": [0.9, 1.0], "right_ankle": [0.1, 1.0],
    })
    top["primary_color"] = {"lab": top_lab}
    bottom["primary_color"] = {"lab": bottom_lab}
    memory_db["items"].insert_one(top)
    memory_db["items"].insert_one(bottom)


def _render_with_generation(client, memory_db, monkeypatch, tmp_path, generate_fn):
    """Scan (with a big enough source photo for A7 sampling), seed red-top/blue-bottom items,
    monkeypatch the Gemini call, POST /render, and wait for the background job to settle."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(gen_client, "generate_tryon", generate_fn)
    avatar = _scan_ok(monkeypatch, client, memory_db, image_bytes=_synthetic_png_bytes(size=PERSON_PHOTO_SIZE))
    _seed_colored_items(memory_db, tmp_path, RED_LAB, BLUE_LAB)

    body = {"avatar_id": avatar["avatar_id"], "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb", "jacket_id": None}
    resp = client.post("/api/render", json=body)
    assert resp.status_code == 200, resp.text
    job = resp.json()
    assert job["status"] == "pending"
    render_id = job["render_id"]
    settled = _wait_for_settled(memory_db["renders"], render_id)
    return settled, tmp_path


def _half_and_half_image(top_color, bottom_color, size=PERSON_PHOTO_SIZE):
    """A stand-in "generated" photo: top half one color (covers the shirt sample point around
    y=275), bottom half another (covers the pants sample point around y=456; see verify.py)."""
    w, h = size
    img = Image.new("RGB", (w, h), bottom_color)
    top_half = Image.new("RGB", (w, h // 2), top_color)
    img.paste(top_half, (0, 0))
    return img


def test_generation_success_marks_done_with_verified_colors(client, memory_db, monkeypatch, tmp_path):
    good_image = _half_and_half_image((255, 0, 0), (0, 0, 255))
    settled, media_dir = _render_with_generation(
        client, memory_db, monkeypatch, tmp_path,
        lambda person, top, bottom, jacket, is_dress: good_image,
    )
    assert settled["status"] == "done"
    assert settled["generated_url"] is not None
    assert settled["generated_url"].startswith("/media/renders/")
    assert (media_dir / settled["generated_url"][len("/media/"):]).is_file()


def test_generation_raises_marks_failed(client, memory_db, monkeypatch, tmp_path):
    def _boom(person, top, bottom, jacket, is_dress):
        raise gen_client.GenerationError("simulated 429 resource_exhausted")

    settled, _ = _render_with_generation(client, memory_db, monkeypatch, tmp_path, _boom)
    assert settled["status"] == "failed"
    assert settled["generated_url"] is None


def test_generation_wrong_color_fails_verification(client, memory_db, monkeypatch, tmp_path):
    wrong_image = _half_and_half_image((0, 255, 0), (0, 255, 0))  # green, matches neither item
    settled, _ = _render_with_generation(
        client, memory_db, monkeypatch, tmp_path,
        lambda person, top, bottom, jacket, is_dress: wrong_image,
    )
    assert settled["status"] == "failed"
    assert settled["generated_url"] is None


def test_verify_colors_directly_pass_and_fail():
    landmarks = {name: [x, y] for name, (x, y, _v) in _good_landmarks().items()}
    good = np.asarray(_half_and_half_image((255, 0, 0), (0, 0, 255)))
    ok, reason = verify.verify_colors(
        good, landmarks, PERSON_PHOTO_SIZE,
        [(GarmentType.shirt, {"lab": RED_LAB}), (GarmentType.pants, {"lab": BLUE_LAB})],
    )
    assert ok, reason

    bad = np.asarray(_half_and_half_image((0, 255, 0), (0, 255, 0)))
    ok, reason = verify.verify_colors(
        bad, landmarks, PERSON_PHOTO_SIZE,
        [(GarmentType.shirt, {"lab": RED_LAB}), (GarmentType.pants, {"lab": BLUE_LAB})],
    )
    assert not ok
    assert "dE2000" in reason


def test_render_returns_immediately_even_with_a_slow_generator(client, memory_db, monkeypatch, tmp_path):
    def _slow(person, top, bottom, jacket, is_dress):
        time.sleep(0.3)
        return _half_and_half_image((255, 0, 0), (0, 0, 255))

    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(gen_client, "generate_tryon", _slow)
    avatar = _scan_ok(monkeypatch, client, memory_db, image_bytes=_synthetic_png_bytes(size=PERSON_PHOTO_SIZE))
    _seed_colored_items(memory_db, tmp_path, RED_LAB, BLUE_LAB)

    body = {"avatar_id": avatar["avatar_id"], "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb", "jacket_id": None}
    t0 = time.perf_counter()
    resp = client.post("/api/render", json=body)
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 200
    job = resp.json()
    assert job["status"] == "pending"
    assert elapsed < 0.25, f"POST /render blocked on the generator: {elapsed:.2f}s"

    render_id = job["render_id"]
    settled = _wait_for_settled(memory_db["renders"], render_id)
    assert settled["status"] == "done"  # proves the slow call really did run, just not on this thread


def test_background_worker_never_makes_a_real_network_call_by_default(memory_db):
    """Sanity check on the autouse fixture itself: without an explicit monkeypatch, generation
    must fail closed, never reach the network."""
    with pytest.raises(gen_client.GenerationError):
        gen_client.generate_tryon(None, None, None, None, False)
