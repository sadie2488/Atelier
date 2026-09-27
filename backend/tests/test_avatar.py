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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageOps

from backend import config
from backend.avatar import background, compositing, face, gen_client, ids, person, service, skin, verify
from backend.avatar.gen_client import generate_tryon as _real_generate_tryon  # bound before the
# autouse fixture below monkeypatches gen_client.generate_tryon, so this name still reaches the
# real function -- needed to test the real function's own behavior (the timeout it sends).
from backend.avatar.pose_validation import ARMS_MESSAGE_PREFIX, validate
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


# _good_landmarks() spans roughly x:[0,400] y:[80,700] on its own virtual canvas. Pose validation
# now also checks framing (body height as a fraction of the actual photo height), so the synthetic
# photo's own size must be consistent with that span -- this is that consistent frame size, and
# also the default for _synthetic_png_bytes() below. (420, 900) keeps the resulting frame_fraction
# around 0.77, comfortably inside [MIN_BODY_FRAME_FRACTION, MAX_BODY_FRAME_FRACTION] and close to
# the two real model photos (0.77-0.79, see test_real_model_photos_are_accepted).
_GOOD_FRAME_SIZE = (420, 900)


def _synthetic_png_bytes(color=(200, 150, 120), size=_GOOD_FRAME_SIZE) -> bytes:
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
    assert validate(_good_landmarks(), _GOOD_FRAME_SIZE) is None


def test_pose_rejects_missing_landmarks_with_actionable_reason():
    lm = _good_landmarks()
    lm["left_ankle"] = (230.0, 700.0, 0.1)  # out of frame / not visible
    result = validate(lm, _GOOD_FRAME_SIZE)
    assert result[0].value == "pose_rejected"
    assert result[1] == "Your ankles aren't visible — step back until your feet are in the frame."


def test_pose_rejects_arms_close_to_body_with_actionable_reason():
    lm = _good_landmarks()
    lm["left_elbow"] = (245.0, 200.0, 0.99)  # nearly in line with the torso, not away from it
    result = validate(lm, _GOOD_FRAME_SIZE)
    assert result[0].value == "pose_rejected"
    assert result[1].startswith(ARMS_MESSAGE_PREFIX)


def test_pose_rejects_arm_angle_just_below_new_threshold():
    # ARM_ANGLE_MIN_DEG is 12.0 (human decision 2026-09-26, unchanged by the 2026-09-27 pass).
    # left_elbow placed so the hip-shoulder-elbow angle is exactly 10 degrees -- just under it.
    lm = _good_landmarks()
    lm["left_elbow"] = (259.45614434184796, 249.55190271504677, 0.99)
    result = validate(lm, _GOOD_FRAME_SIZE)
    assert result[0].value == "pose_rejected"
    assert result[1].startswith(ARMS_MESSAGE_PREFIX)
    assert "10°" in result[1] and "12°" in result[1]


def test_pose_accepts_arm_angle_just_above_new_threshold():
    # Same construction as above, but the angle is 14 degrees -- just over the threshold --
    # which real relaxed-stance scans (15-23 degrees) must clear.
    lm = _good_landmarks()
    lm["left_elbow"] = (266.37749933741526, 248.6497719989913, 0.99)
    assert validate(lm, _GOOD_FRAME_SIZE) is None


def test_pose_rejects_reports_every_failing_check_ordered_by_importance():
    """A1 priority bug fix: previously only the FIRST failing check was reported. Now every check
    is evaluated and every failure is reported, most important first (missing landmarks -- the
    scan is fundamentally unusable -- before the fine-grained arm-angle check)."""
    lm = _good_landmarks()
    lm["left_ankle"] = (230.0, 700.0, 0.1)  # missing: most important
    lm["left_elbow"] = (245.0, 200.0, 0.99)  # arms too close: least important of these two
    result = validate(lm, _GOOD_FRAME_SIZE)
    assert result[0].value == "pose_rejected"
    lines = result[1].split("\n")
    assert len(lines) == 2
    assert lines[0] == "Your ankles aren't visible — step back until your feet are in the frame."
    assert lines[1].startswith(ARMS_MESSAGE_PREFIX)


def test_pose_rejects_too_close_to_camera():
    """NEW check (human report 2026-09-27: no way to tell 'too close' apart from a garbled
    rejection). A frame short enough that the body fills > MAX_BODY_FRAME_FRACTION of its height."""
    result = validate(_good_landmarks(), (420, 700))
    assert result is not None
    assert result[0].value == "pose_rejected"
    assert "too close to the camera" in result[1]
    assert "% of the frame height" in result[1]


def test_pose_rejects_too_far_from_camera():
    """NEW check: a frame tall enough that the body fills < MIN_BODY_FRAME_FRACTION of its height."""
    result = validate(_good_landmarks(), (420, 4000))
    assert result is not None
    assert result[0].value == "pose_rejected"
    assert "too far from the camera" in result[1]


def test_pose_rejects_turned_away_from_camera():
    """NEW check: the nose shifted well off the shoulder midpoint (a profile turn), relative to
    shoulder width -- see MAX_FACING_OFFSET_RATIO for why this proxy is used instead of z-depth."""
    lm = _good_landmarks()
    lm["nose"] = (270.0, 80.0, 0.99)  # shoulder_mid_x=200, shoulder_width=100 -> offset ratio 0.7
    result = validate(lm, _GOOD_FRAME_SIZE)
    assert result == (result[0], "Turn to face the camera — your shoulders look rotated.")
    assert result[0].value == "pose_rejected"


@pytest.mark.parametrize("image_name", [
    # The closest fixture to "full body, front-facing" available (see lane report: none of
    # fixtures/images/ actually spans shoulders-to-ankles -- these are garment product photos).
    "leaf green short-sleev midi dress #105243.png",
])
def test_real_photo_with_cropped_legs_is_pose_rejected(image_name):
    """Real MediaPipe run (no mocking): a photo cropped above the ankles must be rejected, not
    silently accepted with bad placement anchors. MediaPipe extrapolates an ankle position even
    past the bottom edge of a cropped frame (visibility can still land above VISIBILITY_MIN), so
    this ends up caught by the framing check instead of the missing-landmark one -- either is a
    correct, actionable rejection for this photo."""
    rgb = np.asarray(Image.open(FIXTURES / image_name).convert("RGB"))
    from backend.avatar.landmarks import detect_landmarks
    landmarks = detect_landmarks(rgb)
    assert landmarks is not None
    result = validate(landmarks, (rgb.shape[1], rgb.shape[0]))
    assert result is not None
    assert result[0].value == "pose_rejected"
    assert "ankles aren't visible" in result[1] or "too close to the camera" in result[1]


MODELS_DIR = Path(__file__).resolve().parents[1] / "avatar" / "models"


@pytest.mark.parametrize("image_name", ["model.sadie.jpeg", "model.lalitha.jpeg"])
def test_real_model_photos_are_accepted(image_name):
    """The two real scans used to calibrate every threshold in pose_validation.py must pass --
    both measured at 14.6-23.8 degree arm angles, 0.77-0.79 frame fraction, ~0.02-0.03 facing
    offset. Skips if the (large, checked-in) fixture is absent."""
    path = MODELS_DIR / image_name
    if not path.is_file():
        pytest.skip(f"{image_name} not present")
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    rgb = np.asarray(img)
    from backend.avatar.landmarks import detect_landmarks
    landmarks = detect_landmarks(rgb)
    assert landmarks is not None
    result = validate(landmarks, (rgb.shape[1], rgb.shape[0]))
    assert result is None, f"{image_name} rejected: {result[1] if result else None}"


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


# ---------------------------------------------------------------- A3 change: real-body avatar

def _fake_segmenter_with_mask(category_mask):
    """A test double for mp_models.image_segmenter -- same shape as skin.py's, but returning a
    caller-supplied category mask instead of running the real model."""
    class _FakeMask:
        def numpy_view(self):
            return category_mask

    class _FakeResult:
        category_mask = _FakeMask()

    class _FakeSegmenter:
        def segment(self, mp_image):
            return _FakeResult()

    return _FakeSegmenter()


def _big_person_mask(crop_shape):
    """crop_shape = (h, w): a big inset blob comfortably over person.MIN_PERSON_FRACTION of that
    crop -- a plausible "person" mask for these tests, not a realistic silhouette."""
    h, w = crop_shape
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[round(h * 0.03):round(h * 0.97), round(w * 0.08):round(w * 0.92)] = 4  # "clothes" category
    return mask


def _crop_shape_for(landmarks, frame_size):
    """-> (bbox, (crop_h, crop_w)) -- the SAME pose bbox build_avatar_visuals will compute, so a
    test's fake mask can be sized to match it exactly (required when the crop is >= 256px on its
    long side, since then person._segment_mask_in_crop does not resize)."""
    rig = compute_rig(landmarks)
    bbox = person.pose_bbox(rig, landmarks, frame_size)
    x0, y0, x1, y1 = bbox
    return bbox, (y1 - y0, x1 - x0)


def _scaled_landmarks(scale, offset=(0.0, 0.0)):
    ox, oy = offset
    return {name: (x * scale + ox, y * scale + oy, v) for name, (x, y, v) in _good_landmarks().items()}


def test_person_cutout_used_when_mask_plausible(monkeypatch):
    lm = _good_landmarks()
    _, crop_shape = _crop_shape_for(lm, PERSON_PHOTO_SIZE)
    rgb = np.full((PERSON_PHOTO_SIZE[1], PERSON_PHOTO_SIZE[0], 3), (40, 40, 40), dtype=np.uint8)
    monkeypatch.setattr(person, "image_segmenter", lambda: _fake_segmenter_with_mask(_big_person_mask(crop_shape)))

    visuals = service.build_avatar_visuals(rgb, lm)

    assert visuals["avatar_kind"] == "real_body"
    aw, ah = visuals["avatar_img"].size
    assert (aw, ah) == (visuals["canvas_w"], visuals["canvas_h"])
    # 1:2 width:height canvas (rounding-tolerant).
    assert abs(aw * 2 - ah) <= 1
    # The avatar image is the real-body cutout, not line art: it carries fully-opaque pixels
    # wherever the (fake) person mask was set.
    alpha = np.array(visuals["avatar_img"])[:, :, 3]
    assert alpha.max() == 255


def test_person_cutout_falls_back_to_photo_crop_when_mask_empty(monkeypatch):
    """A3 change 2026-09-27: no mannequin at all -- a failed/empty mask falls back to a photo
    crop of the person, never the drawn line art."""
    rgb = np.full((PERSON_PHOTO_SIZE[1], PERSON_PHOTO_SIZE[0], 3), (40, 40, 40), dtype=np.uint8)
    empty_mask = np.zeros((10, 10), dtype=np.uint8)  # any all-background mask -- shape irrelevant, see build_person_cutout's early return
    monkeypatch.setattr(person, "image_segmenter", lambda: _fake_segmenter_with_mask(empty_mask))

    visuals = service.build_avatar_visuals(rgb, _good_landmarks())

    assert visuals["avatar_kind"] == "photo_crop"
    assert visuals["avatar_kind"] != "drawn"
    assert visuals["avatar_img"].size == visuals["wireframe_img"].size
    # Still a real photo, not a blank/transparent image: the interior (away from the vignette
    # edge) carries the source photo's own pixel color.
    arr = np.array(visuals["avatar_img"])
    cx, cy = arr.shape[1] // 2, arr.shape[0] // 2
    assert tuple(arr[cy, cx][:3]) == (40, 40, 40)
    assert arr[cy, cx][3] > 200  # opaque at the center


def test_small_person_in_landscape_frame_still_gets_real_body_avatar(monkeypatch):
    """Regression (2026-09-27): a live webcam scan is landscape with the person standing far
    back -- a small fraction of the FULL FRAME (this is exactly what made avatar_858d48,
    avatar_29f549, and avatar_d0809f fall back). Segmenting only the person's own pose bbox
    (person.pose_bbox), not the whole frame, must still succeed even though the person is well
    under MIN_PERSON_FRACTION of the frame overall."""
    frame_size = (1080, 608)  # landscape, like a laptop webcam
    landmarks = _scaled_landmarks(0.2, offset=(480.0, 200.0))
    rgb = np.full((frame_size[1], frame_size[0], 3), (40, 40, 40), dtype=np.uint8)

    bbox, crop_shape = _crop_shape_for(landmarks, frame_size)
    bx0, by0, bx1, by1 = bbox
    crop_fraction_of_frame = ((bx1 - bx0) * (by1 - by0)) / (frame_size[0] * frame_size[1])
    assert crop_fraction_of_frame < person.MIN_PERSON_FRACTION, (
        "test setup: the person must be a tiny fraction of the FULL frame for this regression to mean anything"
    )

    monkeypatch.setattr(person, "image_segmenter", lambda: _fake_segmenter_with_mask(_big_person_mask(crop_shape)))
    visuals = service.build_avatar_visuals(rgb, landmarks)

    assert visuals["avatar_kind"] == "real_body"
    assert visuals["avatar_img"].size == visuals["wireframe_img"].size
    assert abs(visuals["canvas_w"] * 2 - visuals["canvas_h"]) <= 1


def test_local_composite_places_garments_on_real_body_canvas(tmp_path, monkeypatch):
    """A5, on the NEW canvas geometry: garments still land where the (translated) rig says."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    lm = _good_landmarks()
    _, crop_shape = _crop_shape_for(lm, PERSON_PHOTO_SIZE)
    rgb = np.full((PERSON_PHOTO_SIZE[1], PERSON_PHOTO_SIZE[0], 3), (40, 40, 40), dtype=np.uint8)
    monkeypatch.setattr(person, "image_segmenter", lambda: _fake_segmenter_with_mask(_big_person_mask(crop_shape)))

    visuals = service.build_avatar_visuals(rgb, lm)
    assert visuals["avatar_kind"] == "real_body"
    rig, canvas_size = visuals["rig_local"], (visuals["canvas_w"], visuals["canvas_h"])

    shoulder_hip_anchors = {
        "left_shoulder": [0.9, 0.0], "right_shoulder": [0.1, 0.0],
        "left_hip": [0.9, 1.0], "right_hip": [0.1, 1.0],
    }
    top_item = _write_item(tmp_path, "top_realbody", GarmentType.shirt, (0, 255, 0), shoulder_hip_anchors)
    from backend.avatar.service import _load_item_layer
    composed = compositing.composite_outfit(
        visuals["avatar_img"], canvas_size, rig, top=_load_item_layer(top_item),
    )
    sample_x = round(rig.shoulder_mid[0])
    sample_y = round((rig.shoulder_mid[1] + rig.hip_mid[1]) / 2)
    assert composed.getpixel((sample_x, sample_y))[:3] == (0, 255, 0)


def test_scan_endpoint_produces_real_body_avatar_on_1to2_canvas(client, memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr("backend.avatar.service.detect_landmarks", lambda rgb: _good_landmarks())
    _, crop_shape = _crop_shape_for(_good_landmarks(), PERSON_PHOTO_SIZE)
    monkeypatch.setattr(person, "image_segmenter", lambda: _fake_segmenter_with_mask(_big_person_mask(crop_shape)))

    photo = Image.new("RGB", PERSON_PHOTO_SIZE, (40, 40, 40))
    buf = io.BytesIO()
    photo.save(buf, format="PNG")
    resp = client.post("/api/avatar/scan", files={"image": ("photo.png", buf.getvalue(), "image/png")})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    avatar_doc = memory_db["avatars"].find_one({"avatar_id": body["avatar_id"]})
    assert avatar_doc["avatar_kind"] == "real_body"  # DB-only; not in the response contract

    avatar_img = Image.open(tmp_path / body["avatar_url"][len("/media/"):])
    wireframe_img = Image.open(tmp_path / body["wireframe_url"][len("/media/"):])
    assert abs(avatar_img.width * 2 - avatar_img.height) <= 1
    assert avatar_img.size == wireframe_img.size  # same canvas geometry, so the two align


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
        "detect_face_box_near": staticmethod(lambda rgb, head_center, head_radius: None),
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
    assert body["error"]["message"].startswith(ARMS_MESSAGE_PREFIX)


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
    """The local composite path (A1-A6), with generation "possible" (a key is configured) but
    blocked by the no-network autouse fixture -- exercises the full pending -> failed settle, not
    just the pre-A7 shortcut.
    """
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")  # generation "possible"; the
    # no_real_secrets autouse fixture (conftest.py) blanks this by default so tests never depend
    # on backend/.env -- generate_tryon itself is still blocked by _no_network_generation above.
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

    resp2 = client.post("/api/render", json=body)
    assert resp2.status_code == 200
    job2 = resp2.json()
    assert job2["render_id"] == render_id
    assert job2["status"] == "pending"          # a failed try-on is retried, not cached forever
    assert calls == [1], "a failed render must be rebuilt on the next request"


def test_scan_stores_avatar_images_in_durable_media_store(client, memory_db, monkeypatch, tmp_path, memory_media):
    """A7 durable storage: the wireframe, avatar, and source photo saved by scan must all reach
    the durable media store (backend/media_store.py), not just local disk."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    body = _scan_ok(monkeypatch, client, memory_db)
    avatar_id = body["avatar_id"]
    for suffix in ("_wireframe.png", ".png", "_photo.png"):
        key = f"avatars/{avatar_id}{suffix}"
        assert memory_media[key] == (tmp_path / "avatars" / f"{avatar_id}{suffix}").read_bytes()


def test_render_stores_local_composite_in_durable_media_store(client, memory_db, monkeypatch, tmp_path, memory_media):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    avatar = _scan_ok(monkeypatch, client, memory_db)
    _seed_items(memory_db, tmp_path)

    body = {"avatar_id": avatar["avatar_id"], "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb", "jacket_id": None}
    resp = client.post("/api/render", json=body)
    assert resp.status_code == 200, resp.text
    render_id = resp.json()["render_id"]

    key = f"renders/{render_id}_local.png"
    assert memory_media[key] == (tmp_path / "renders" / f"{render_id}_local.png").read_bytes()


def test_render_loads_item_cutout_from_durable_store_when_local_missing(
    client, memory_db, monkeypatch, tmp_path, memory_media,
):
    """A fresh deploy or another machine may not have the item cutout locally -- render must
    fall back to durable storage instead of failing."""
    from backend import media_store

    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    avatar = _scan_ok(monkeypatch, client, memory_db)
    _seed_items(memory_db, tmp_path)

    top_path = tmp_path / "items" / "top_aaaaaa.png"
    media_store.put("items/top_aaaaaa.png", top_path.read_bytes())
    top_path.unlink()
    assert not top_path.is_file()

    body = {"avatar_id": avatar["avatar_id"], "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb", "jacket_id": None}
    resp = client.post("/api/render", json=body)
    assert resp.status_code == 200, resp.text
    job = resp.json()
    assert job["local_url"].startswith("/media/renders/")
    assert (tmp_path / job["local_url"][len("/media/"):]).is_file()
    # load_media caches the fetched cutout back to local disk for next time.
    assert top_path.is_file()


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
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")  # generation "possible" -- see
    # no_real_secrets in conftest.py, which blanks this by default for every test.
    monkeypatch.setattr(gen_client, "generate_tryon", generate_fn)
    # These synthetic "generated" images are flat color blocks -- real pose detection on them
    # would (correctly) find nobody. Force that path deterministically rather than relying on
    # MediaPipe's behavior on a non-photo, so these tests exercise the scaled-source-landmark
    # fallback and stay fast; the generated-image-detection path itself is covered directly
    # against verify.verify_colors below.
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)
    # ISSUES #22: these synthetic images have no face at all (flat color blocks), so the identity
    # check would (correctly) reject every one of them -- bypassed here for the same reason the
    # pose-detection fallback above is forced; the identity check itself is covered directly
    # against verify.verify_identity/verify_colors below, with real face-containing fixtures.
    monkeypatch.setattr(verify, "verify_identity", lambda *a, **k: (True, "ok (bypassed for synthetic test image)"))
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


def _source_landmarks_dict():
    return {name: [x, y] for name, (x, y, _v) in _good_landmarks().items()}


def _paint_patch(img: np.ndarray, point, color, half=40):
    """Paint a square bigger than verify._PATCH centered on `point`, so a sample there is
    unambiguous even with float->int rounding at the edges."""
    x, y = point
    h, w = img.shape[:2]
    x0, x1 = max(0, int(x - half)), min(w, int(x + half))
    y0, y1 = max(0, int(y - half)), min(h, int(y + half))
    img[y0:y1, x0:x1] = color


def test_verify_colors_directly_pass_and_fail(monkeypatch):
    # Deterministic: force the scaled-source-landmark fallback (see _render_with_generation for
    # why real detection on a flat-color synthetic image isn't relied on here).
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)
    source_landmarks = _source_landmarks_dict()
    shirt = (GarmentType.shirt, {"primary_color": {"lab": RED_LAB}})
    pants = (GarmentType.pants, {"primary_color": {"lab": BLUE_LAB}})

    good = np.asarray(_half_and_half_image((255, 0, 0), (0, 0, 255)))
    ok, reason = verify.verify_colors(good, source_landmarks, PERSON_PHOTO_SIZE, top=shirt, bottom=pants)
    assert ok, reason

    bad = np.asarray(_half_and_half_image((0, 255, 0), (0, 255, 0)))
    ok, reason = verify.verify_colors(bad, source_landmarks, PERSON_PHOTO_SIZE, top=shirt, bottom=pants)
    assert not ok
    assert "dE2000" in reason


def test_verify_samples_pose_detected_on_generated_image_when_available(monkeypatch):
    """Re-dispatch fix 1: Gemini re-frames/re-poses the person, so the scaled SOURCE landmarks
    can land on the wrong region. Detecting pose on the GENERATED image itself must be preferred,
    and actually used to pick the sample point, not just attempted."""
    source_landmarks = _source_landmarks_dict()
    source_size = PERSON_PHOTO_SIZE  # (420, 720)

    # A pose MediaPipe would find directly on the generated image: same shape as the source pose
    # but shifted well away from where the scaled source landmarks would land.
    shifted = {name: (x + 600.0, y + 200.0, v) for name, (x, y, v) in _good_landmarks().items()}
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: shifted)

    gen_w, gen_h = 1200, 1000
    img = np.zeros((gen_h, gen_w, 3), dtype=np.uint8)
    img[:, :] = (0, 255, 0)  # green background everywhere except the painted patches below

    shifted_points = {name: (x, y) for name, (x, y, _v) in shifted.items()}
    top_point = verify._region_points(GarmentType.shirt, shifted_points)[0]
    bottom_point = verify._region_points(GarmentType.pants, shifted_points)[0]
    _paint_patch(img, top_point, (255, 0, 0))
    _paint_patch(img, bottom_point, (0, 0, 255))

    shirt = (GarmentType.shirt, {"primary_color": {"lab": RED_LAB}})
    pants = (GarmentType.pants, {"primary_color": {"lab": BLUE_LAB}})

    ok, reason = verify.verify_colors(img, source_landmarks, source_size, top=shirt, bottom=pants)
    assert ok, reason  # sampled at the GENERATED pose's regions, which are painted correctly

    # Without generated-image detection, the scaled SOURCE landmarks land on the green
    # background (a different region entirely) and verification must fail instead of silently
    # passing on the wrong patch.
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)
    ok, reason = verify.verify_colors(img, source_landmarks, source_size, top=shirt, bottom=pants)
    assert not ok


def test_dress_skips_bottom_verification(monkeypatch):
    """Re-dispatch fix 2 (A-R5): a dress covers the bottom, so the bottom's color is never
    checked when the top slot is a dress -- a real render observed this failing every time
    because the bottom garment (layered under the dress) is not what's actually visible there."""
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)
    source_landmarks = _source_landmarks_dict()
    # top-half (dress region) red, matching the dress; bottom-half green, matching neither the
    # bottom's stored color nor anything else -- would fail if the bottom were checked.
    img = np.asarray(_half_and_half_image((255, 0, 0), (0, 255, 0)))
    dress = (GarmentType.dress, {"primary_color": {"lab": RED_LAB}})
    bottom = (GarmentType.pants, {"primary_color": {"lab": BLUE_LAB}})

    ok, reason = verify.verify_colors(img, source_landmarks, PERSON_PHOTO_SIZE, top=dress, bottom=bottom)
    assert ok, reason


def test_jacket_present_skips_top_verification(monkeypatch):
    """Re-dispatch fix 2 (A-R4): a jacket draws over the top, so the top's own color is never
    checked when a jacket is present -- only the jacket and the bottom are."""
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)
    source_landmarks = _source_landmarks_dict()
    # top-half green (the jacket's real color, and NOT the shirt's stored color -- would fail if
    # the shirt were checked); bottom-half blue, matching the bottom.
    img = np.asarray(_half_and_half_image((0, 255, 0), (0, 0, 255)))
    shirt = (GarmentType.shirt, {"primary_color": {"lab": RED_LAB}})  # deliberately wrong
    pants = (GarmentType.pants, {"primary_color": {"lab": BLUE_LAB}})
    jacket = (GarmentType.jacket, {"primary_color": {"lab": GREEN_LAB}})

    ok, reason = verify.verify_colors(
        img, source_landmarks, PERSON_PHOTO_SIZE, top=shirt, bottom=pants, jacket=jacket,
    )
    assert ok, reason


def test_jacket_samples_best_of_several_candidate_points(monkeypatch):
    """ISSUES #21 (2026-09-27): a jacket worn open/off-the-shoulder can leave the near arm's
    shoulder-elbow midpoint sampling bare skin or the top underneath, while the jacket fabric is
    actually at the other arm (or lower, near an elbow). One sample point isn't reliable across
    poses -- verify.py now tries a few (both arms' shoulder-elbow midpoints, plus both elbows) and
    keeps the closest match, mirroring the primary/secondary "best of a few" match already used
    for stored colors. Three of the four candidates here land on background/skin (wrong); only
    the far (right) elbow lands on the actual jacket -- the render must still pass."""
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)
    # Landmarks spaced well apart (further than a patch width) so each candidate point's sample
    # box can't bleed into a neighboring one.
    source_landmarks = {
        "left_shoulder": [300.0, 150.0], "right_shoulder": [100.0, 150.0],
        "left_elbow": [300.0, 400.0], "right_elbow": [100.0, 400.0],
        "left_hip": [250.0, 600.0], "right_hip": [150.0, 600.0],
        "left_knee": [250.0, 700.0], "right_knee": [150.0, 700.0],
    }
    size = (450, 750)
    img = np.full((size[1], size[0], 3), (128, 128, 128), dtype=np.uint8)  # background/skin: gray
    _paint_patch(img, (200.0, 635.0), (0, 0, 255))   # pants sample point -> blue, matches pants
    _paint_patch(img, (100.0, 400.0), (0, 255, 0))   # right elbow only -> green, matches jacket
    # left shoulder-elbow midpoint (300,275), right shoulder-elbow midpoint (100,275), and left
    # elbow (300,400) are left gray -- three of four jacket candidates are "wrong".

    shirt = (GarmentType.shirt, {"primary_color": {"lab": RED_LAB}})
    pants = (GarmentType.pants, {"primary_color": {"lab": BLUE_LAB}})
    jacket = (GarmentType.jacket, {"primary_color": {"lab": GREEN_LAB}})

    ok, reason = verify.verify_colors(img, source_landmarks, size, top=shirt, bottom=pants, jacket=jacket)
    assert ok, reason


def test_primary_or_secondary_color_match(monkeypatch):
    """Re-dispatch fix 3 / DECISIONS V-C6: a hit counts against the item's primary OR secondary
    color, not primary alone."""
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)
    source_landmarks = _source_landmarks_dict()
    img = np.asarray(_half_and_half_image((0, 255, 0), (0, 0, 255)))  # top-half green, bottom blue
    shirt = (GarmentType.shirt, {"primary_color": {"lab": RED_LAB}, "secondary_color": {"lab": GREEN_LAB}})
    pants = (GarmentType.pants, {"primary_color": {"lab": BLUE_LAB}})

    ok, reason = verify.verify_colors(img, source_landmarks, PERSON_PHOTO_SIZE, top=shirt, bottom=pants)
    assert ok, reason


def test_debug_image_saved_on_verification_failure(monkeypatch, tmp_path):
    """Re-dispatch fix 4: a failing render dumps the generated image for a human to inspect,
    under media/_preview/ (debug only -- media.save_png already keeps that out of durable
    storage). A passing render must not leave one behind."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)
    source_landmarks = _source_landmarks_dict()
    shirt = (GarmentType.shirt, {"primary_color": {"lab": RED_LAB}})
    pants = (GarmentType.pants, {"primary_color": {"lab": BLUE_LAB}})

    bad = np.asarray(_half_and_half_image((0, 255, 0), (0, 255, 0)))  # matches neither item
    ok, reason = verify.verify_colors(
        bad, source_landmarks, PERSON_PHOTO_SIZE, top=shirt, bottom=pants, render_id="render_debugtest",
    )
    assert not ok
    debug_path = tmp_path / "_preview" / "render_debugtest_generated_debug.png"
    assert debug_path.is_file()

    good = np.asarray(_half_and_half_image((255, 0, 0), (0, 0, 255)))
    ok, reason = verify.verify_colors(
        good, source_landmarks, PERSON_PHOTO_SIZE, top=shirt, bottom=pants, render_id="render_debugtest_ok",
    )
    assert ok, reason
    assert not (tmp_path / "_preview" / "render_debugtest_ok_generated_debug.png").is_file()


def test_render_returns_immediately_even_with_a_slow_generator(client, memory_db, monkeypatch, tmp_path):
    def _slow(person, top, bottom, jacket, is_dress):
        time.sleep(0.3)
        return _half_and_half_image((255, 0, 0), (0, 0, 255))

    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")  # generation "possible" -- see
    # no_real_secrets in conftest.py, which blanks this by default for every test.
    monkeypatch.setattr(gen_client, "generate_tryon", _slow)
    # ISSUES #22: a flat color block has no face -- bypass identity here too (see
    # _render_with_generation's identical comment); this test is about timing, not verification.
    monkeypatch.setattr(verify, "verify_identity", lambda *a, **k: (True, "ok (bypassed for synthetic test image)"))
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


def test_generate_tryon_sends_image_timeout_not_local_wait_timeout(monkeypatch):
    """A7 bug fix (re-dispatch): the request deadline sent to Gemini must come from
    GEMINI_IMAGE_TIMEOUT_SECONDS (default 60s), not GEMINI_TIMEOUT_SECONDS (8s, meant for local
    waits) -- Gemini rejects deadlines under 10s ("Manually set deadline 8s is too short")."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key-for-test")
    captured = {}

    class _FakeModels:
        def generate_content(self, model, contents, config):
            captured["timeout_ms"] = config["http_options"]["timeout"]
            return type("R", (), {"candidates": []})()

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", _FakeClient)

    person = Image.new("RGB", (10, 10))
    top = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    with pytest.raises(gen_client.GenerationError):  # fake response has no image -- expected
        _real_generate_tryon(person, top, None, None, False)

    assert captured["timeout_ms"] == config.GEMINI_IMAGE_TIMEOUT_SECONDS * 1000
    assert captured["timeout_ms"] >= 10000


# ---------------------------------------------------------------- A7 fix 1: dress + bottom (v2)

def test_prompt_v2_dress_also_describes_the_bottom():
    from backend.avatar.prompt import PROMPT_VERSION, build_prompt
    assert PROMPT_VERSION == "v3"
    assert "must not be edited or modified" in build_prompt(has_jacket=False, is_dress=False)
    text = build_prompt(has_jacket=False, is_dress=True)
    assert "third image is a bottom" in text
    assert "dress worn over this bottom" in text


def test_dress_outfit_sends_bottom_to_generation(client, memory_db, monkeypatch, tmp_path):
    """A-R5/A-R7: a dress still has a bottom slot (no exclusion logic) and it must reach Gemini
    too, not be silently dropped."""
    calls = []

    def spy(person, top, bottom, jacket, is_dress):
        calls.append({"bottom": bottom, "is_dress": is_dress})
        return _half_and_half_image((255, 0, 0), (0, 0, 255))

    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")  # generation "possible" -- see
    # no_real_secrets in conftest.py, which blanks this by default for every test.
    monkeypatch.setattr(gen_client, "generate_tryon", spy)
    monkeypatch.setattr(verify.landmarks, "detect_landmarks", lambda rgb: None)  # see _render_with_generation
    avatar = _scan_ok(monkeypatch, client, memory_db, image_bytes=_synthetic_png_bytes(size=PERSON_PHOTO_SIZE))

    dress = _write_item(tmp_path, "dress_cccccc", GarmentType.dress, (0, 255, 0), {
        "left_shoulder": [0.9, 0.0], "right_shoulder": [0.1, 0.0],
        "left_hip": [0.9, 1.0], "right_hip": [0.1, 1.0],
    })
    bottom = _write_item(tmp_path, "bottom_bbbbbb", GarmentType.pants, (0, 0, 255), {
        "left_hip": [0.9, 0.0], "right_hip": [0.1, 0.0],
        "left_knee": [0.9, 0.5], "right_knee": [0.1, 0.5],
        "left_ankle": [0.9, 1.0], "right_ankle": [0.1, 1.0],
    })
    dress["primary_color"] = {"lab": RED_LAB}
    bottom["primary_color"] = {"lab": BLUE_LAB}
    memory_db["items"].insert_one(dress)
    memory_db["items"].insert_one(bottom)

    body = {"avatar_id": avatar["avatar_id"], "top_id": "dress_cccccc", "bottom_id": "bottom_bbbbbb", "jacket_id": None}
    resp = client.post("/api/render", json=body)
    assert resp.status_code == 200, resp.text
    _wait_for_settled(memory_db["renders"], resp.json()["render_id"])

    assert len(calls) == 1
    assert calls[0]["is_dress"] is True
    assert calls[0]["bottom"] is not None, "the bottom cutout must be sent for a dress outfit too"


# ---------------------------------------------------------------- A7 fix 2: stale pending reaping

def _backdate_to_stale(renders_collection, render_id):
    stale_since = datetime.now(timezone.utc) - timedelta(seconds=service.PENDING_STALE_SECONDS + 1)
    renders_collection.update_one(
        {"render_id": render_id},
        {"$set": {"status": "pending", "generated_url": None, "pending_since": stale_since}},
    )


def test_stale_pending_render_settles_to_failed_on_get(client, memory_db, monkeypatch, tmp_path):
    """A restart-orphaned `pending` job (backdated pending_since) must not poll forever."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    avatar = _scan_ok(monkeypatch, client, memory_db, image_bytes=_synthetic_png_bytes(size=PERSON_PHOTO_SIZE))
    _seed_items(memory_db, tmp_path)

    body = {"avatar_id": avatar["avatar_id"], "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb", "jacket_id": None}
    resp = client.post("/api/render", json=body)
    render_id = resp.json()["render_id"]

    # Let the (blocked-by-default) background job settle it once, then re-open it as a long
    # -stuck `pending` row -- exactly what a process restart mid-generation would leave behind.
    _wait_for_settled(memory_db["renders"], render_id)
    _backdate_to_stale(memory_db["renders"], render_id)

    get_resp = client.get(f"/api/render/{render_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["status"] == "failed"
    assert body["generated_url"] is None

    # The stored doc itself must be settled too, not just this one response.
    doc = memory_db["renders"].find_one({"render_id": render_id})
    assert doc["status"] == "failed"


def test_stale_pending_render_settles_on_post_cache_hit(client, memory_db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    avatar = _scan_ok(monkeypatch, client, memory_db, image_bytes=_synthetic_png_bytes(size=PERSON_PHOTO_SIZE))
    _seed_items(memory_db, tmp_path)

    body = {"avatar_id": avatar["avatar_id"], "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb", "jacket_id": None}
    resp = client.post("/api/render", json=body)
    render_id = resp.json()["render_id"]
    _wait_for_settled(memory_db["renders"], render_id)
    _backdate_to_stale(memory_db["renders"], render_id)

    resp2 = client.post("/api/render", json=body)  # cache hit path
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "failed"
    assert resp2.json()["render_id"] == render_id


def test_fresh_pending_render_is_not_reaped(client, memory_db, monkeypatch, tmp_path):
    """A job pending well within PENDING_STALE_SECONDS must be left alone."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")  # generation "possible" -- see
    # no_real_secrets in conftest.py, which blanks this by default for every test.

    def _slow(person, top, bottom, jacket, is_dress):
        time.sleep(0.2)
        return _half_and_half_image((255, 0, 0), (0, 0, 255))

    monkeypatch.setattr(gen_client, "generate_tryon", _slow)
    avatar = _scan_ok(monkeypatch, client, memory_db, image_bytes=_synthetic_png_bytes(size=PERSON_PHOTO_SIZE))
    _seed_colored_items(memory_db, tmp_path, RED_LAB, BLUE_LAB)

    body = {"avatar_id": avatar["avatar_id"], "top_id": "top_aaaaaa", "bottom_id": "bottom_bbbbbb", "jacket_id": None}
    resp = client.post("/api/render", json=body)
    render_id = resp.json()["render_id"]

    get_resp = client.get(f"/api/render/{render_id}")  # immediately -- nowhere near stale
    assert get_resp.json()["status"] == "pending"

    _wait_for_settled(memory_db["renders"], render_id)


# ---------------------------------------------------------------- A9 robustness: real-photo fixes

def test_face_detect_near_crops_and_maps_box_back(monkeypatch):
    """A9/A-B6: a full-body frame is too small for direct face detection (see face.py docstring)
    -- detect_face_box_near must crop around the rig's head estimate and translate whatever box
    the detector finds in that crop back into full-frame pixel coordinates."""
    head_center = (100.0, 80.0)
    head_radius = 20.0
    pad = head_radius * 3.0  # detect_face_box_near's default pad_factor
    rgb = np.zeros((600, 800, 3), dtype=np.uint8)

    seen_crop_shapes = []

    def fake_detect(crop):
        seen_crop_shapes.append(crop.shape)
        return (5, 5, 15, 15)  # a box in the CROP's own coordinates

    monkeypatch.setattr(face, "detect_face_box", fake_detect)
    box = face.detect_face_box_near(rgb, head_center, head_radius)

    expected_cx0 = max(0, int(head_center[0] - pad))
    expected_cy0 = max(0, int(head_center[1] - pad))
    assert box == (expected_cx0 + 5, expected_cy0 + 5, expected_cx0 + 15, expected_cy0 + 15)
    assert len(seen_crop_shapes) == 1
    # The crop actually shrank the search region -- not the whole frame handed to the detector.
    assert seen_crop_shapes[0][0] < rgb.shape[0] and seen_crop_shapes[0][1] < rgb.shape[1]


def test_face_detect_near_returns_none_when_crop_finds_nothing(monkeypatch):
    """A-B8: no rung below this one -- a miss on the crop means no composited face, not a crash
    or a second full-frame attempt."""
    monkeypatch.setattr(face, "detect_face_box", lambda crop: None)
    rgb = np.zeros((600, 800, 3), dtype=np.uint8)
    assert face.detect_face_box_near(rgb, (100.0, 80.0), 20.0) is None


def test_downscale_caps_long_side_of_large_photo():
    """A9: an uncapped phone photo must be brought down to MAX_LONG_SIDE before it reaches
    landmarking, drawing, storage, or generation."""
    big = Image.new("RGB", (4000, 3000), (100, 120, 140))
    scaled = service._downscale(big)
    assert max(scaled.size) <= service.MAX_LONG_SIDE
    assert abs(scaled.width / scaled.height - big.width / big.height) < 0.01  # aspect preserved


def test_downscale_leaves_small_photo_untouched():
    small = Image.new("RGB", (400, 300), (10, 20, 30))
    scaled = service._downscale(small)
    assert scaled.size == small.size


def test_decode_image_downscales_and_corrects_orientation():
    """End to end through _decode_image: a large photo comes out at or under MAX_LONG_SIDE."""
    big = Image.new("RGB", (3200, 2400), (50, 60, 70))
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    rgb = service._decode_image(buf.getvalue())
    assert max(rgb.shape[:2]) <= service.MAX_LONG_SIDE


def test_skin_sampling_uses_segmenter_skin_category_median_in_lab(monkeypatch):
    """A-B5: skin tone comes from the segmenter's skin-category pixels, as the median in Lab --
    not a mean in RGB, and not the (very different) non-skin background."""
    rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    # Row 0: "skin" pixels -- two similar mid-tones plus a shadow and a blown highlight, both of
    # which the median-in-Lab step must exclude.
    rgb[0, 0] = (200, 150, 130)
    rgb[0, 1] = (202, 152, 131)
    rgb[0, 2] = (0, 0, 0)
    rgb[0, 3] = (255, 255, 255)
    # Rows 1-3: background -- a completely different color that must never leak into the result.
    rgb[1:, :] = (10, 200, 10)

    category_mask = np.zeros((4, 4), dtype=np.uint8)
    category_mask[0, :] = 2  # body-skin (see mp_models.py's category list)

    class _FakeMask:
        def numpy_view(self):
            return category_mask

    class _FakeResult:
        category_mask = _FakeMask()

    class _FakeSegmenter:
        def segment(self, mp_image):
            return _FakeResult()

    monkeypatch.setattr(skin, "image_segmenter", lambda: _FakeSegmenter())

    r, g, b = skin.sample_skin_tone(rgb, {"nose": (0.0, 0.0, 0.99)})

    # Close to the two clean mid-tone skin pixels, not dragged toward black, white, or green.
    assert abs(r - 201) <= 3 and abs(g - 151) <= 3 and abs(b - 130) <= 3


def test_skin_sampling_falls_back_to_face_region_when_no_skin_pixels(monkeypatch):
    """A-B8: segmentation finding no skin (e.g. long sleeves and pants) falls back to the face
    region, which is always available. The face patch (a 12x12 window, see skin._PATCH) must be
    fully inside the "face" colored block, or the sample would pick up the surrounding color."""
    rgb = np.full((30, 30, 3), (10, 200, 10), dtype=np.uint8)  # clothes/background everywhere
    rgb[9:21, 9:21] = (220, 180, 150)  # a face-colored block big enough to fully contain the patch

    category_mask = np.zeros((30, 30), dtype=np.uint8)  # all background -- no skin category present

    class _FakeMask:
        def numpy_view(self):
            return category_mask

    class _FakeResult:
        category_mask = _FakeMask()

    class _FakeSegmenter:
        def segment(self, mp_image):
            return _FakeResult()

    monkeypatch.setattr(skin, "image_segmenter", lambda: _FakeSegmenter())

    r, g, b = skin.sample_skin_tone(rgb, {"nose": (15.0, 15.0, 0.99)}, face_patch_center=(15.0, 15.0))
    assert (r, g, b) != (10, 200, 10)
    assert abs(r - 220) <= 3 and abs(g - 180) <= 3 and abs(b - 150) <= 3


# ---------------------------------------------------------------- ISSUES #22: identity check

MODEL_PHOTOS_DIR = Path(__file__).resolve().parents[1] / "avatar" / "models"


def _load_model_photo(name: str) -> tuple[np.ndarray, dict]:
    """-> (rgb, points). Real pose landmarks are needed for _head_geometry to seed the
    face-near-head crop -- these are full-body photos, too small for direct full-frame face
    detection (see face.py's docstring), exactly like a real avatar scan/generated render."""
    from PIL import ImageOps
    from backend.avatar.landmarks import detect_landmarks as _detect_landmarks
    path = MODEL_PHOTOS_DIR / f"model.{name}.jpeg"
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img = service._downscale(img)
    rgb = np.asarray(img)
    lm = _detect_landmarks(rgb)
    points = {n: (v[0], v[1]) for n, v in lm.items()} if lm is not None else {}
    return rgb, points


def test_verify_identity_passes_for_the_same_person():
    """The simplest real check: a photo verified against ITSELF must never be flagged as a
    different person or a cropped-out face."""
    rgb, points = _load_model_photo("sadie")
    ok, reason = verify.verify_identity(rgb, points, rgb, points)
    assert ok, reason


@pytest.mark.xfail(reason="human decision 2026-09-27: eye-spacing check disabled (false failures on real "
                          "try-ons); skin tone alone doesn't separate these two faces", strict=False)
def test_verify_identity_fails_for_a_different_person():
    """ISSUES #22: a real generation swap -- two different real faces -- must be caught."""
    source, source_points = _load_model_photo("sadie")
    generated, generated_points = _load_model_photo("lalitha")
    ok, reason = verify.verify_identity(generated, generated_points, source, source_points)
    assert not ok
    assert reason.startswith("identity:")


def test_verify_identity_fails_when_face_is_cropped_out_of_frame():
    """ISSUES #22: Gemini sometimes crops the face out entirely -- no face at all must fail, not
    silently pass because the garment color happened to match."""
    source, source_points = _load_model_photo("sadie")
    # The bottom third of the photo -- legs/feet only, no face anywhere in frame. No pose landmarks
    # passed for it either (a real crop this tight wouldn't detect a pose pointing at a head above
    # the frame), so there's nothing to seed a face-near-head search with.
    h, w = source.shape[:2]
    legs_only = source[round(h * 0.7):, :]
    ok, reason = verify.verify_identity(legs_only, None, source, source_points)
    assert not ok
    assert reason == "identity: no face detected in the generated image"


def test_verify_identity_never_raises_on_garbage_input():
    """A9 spirit: a detection crash must not become an unhandled exception. A total non-photo on
    both sides has no face anywhere -- correctly rejected, not silently passed, and (the actual
    point of this test) no exception escapes `verify_identity` over it."""
    garbage = np.zeros((5, 5, 3), dtype=np.uint8)
    ok, reason = verify.verify_identity(garbage, None, garbage, {})
    assert ok is False
    assert reason == "identity: no face detected in the generated image"


def test_bottom_with_hallucinated_hip_anchors_is_placed_body_width_and_upright(tmp_path, monkeypatch, capsys):
    """Real catalog regression: pose landmarks on headless bottoms photos land off the garment
    (hips below the cutout, 30 deg apart). Placement must reject them and size the waistband to
    the avatar's hips instead of blowing the cutout up 2-10x and tilting it."""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    rig, canvas_size, _ = _avatar_doc_from_good_pose()
    item = _write_item(tmp_path, "bottom_000009", GarmentType.pants, (0, 0, 255), {
        "left_hip": [0.27, 1.27], "right_hip": [0.15, 1.27],
        "left_knee": [0.27, 1.33], "right_knee": [0.14, 1.28],
        "left_ankle": [0.26, 1.35], "right_ankle": [0.20, 1.27],
    }, size=(120, 300))
    from backend.avatar.service import _load_item_layer
    from backend.avatar.placement import place_item, WAISTBAND_TO_HIP_JOINT
    cutout, anchors, garment_type = _load_item_layer(item)
    layer = place_item(cutout, anchors, garment_type, rig, canvas_size)
    assert "implausible" in capsys.readouterr().out
    alpha = np.array(layer)[:, :, 3] > 0
    ys, xs = np.where(alpha)
    top_row = np.where(alpha[ys.min()])[0]
    width = top_row.max() - top_row.min() + 1
    assert abs(width / (WAISTBAND_TO_HIP_JOINT * rig.hip_width) - 1.0) < 0.1
    # upright: the top row is as wide as the whole layer (a rotated rectangle's is not)
    assert width >= 0.95 * (xs.max() - xs.min() + 1)
