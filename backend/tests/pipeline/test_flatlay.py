import io

import numpy as np
import pytest
from PIL import Image

from contract.enums import IMAGE_LONG_SIDE_PX, NEUTRAL_CHROMA_MAX, ErrorCode
from contract.schemas import Color
from app.pipeline import PipelineError
from app.pipeline.bgremove import cutout
from app.pipeline.color import extract_colors
from app.pipeline.preprocess import gray_world, preprocess


# ---------------------------------------------------------------- preprocess

def _jpeg_with_orientation(w, h, orientation):
    img = Image.new("RGB", (w, h), (120, 120, 120))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_exif_rotation_and_long_side():
    out = preprocess(_jpeg_with_orientation(400, 200, 6))  # 6 = rotate 90° CW
    h, w, _ = out.shape
    assert h == IMAGE_LONG_SIDE_PX and w == IMAGE_LONG_SIDE_PX // 2


def test_small_image_scaled_up_to_long_side():
    out = preprocess(Image.new("RGB", (100, 300), (50, 60, 70)))
    assert max(out.shape[:2]) == IMAGE_LONG_SIDE_PX


def test_gray_world_neutralizes_cast():
    tinted = np.full((10, 10, 3), (140, 120, 110), np.uint8)
    means = gray_world(tinted).reshape(-1, 3).mean(axis=0)
    assert means.max() - means.min() < 3


# ---------------------------------------------------------------- bgremove

def _rect_mask(h, w, box):
    def fn(rgb):
        m = np.zeros(rgb.shape[:2], np.uint8)
        x, y, bw, bh = box
        m[y:y + bh, x:x + bw] = 255
        return m
    return fn


def test_cutout_bbox_and_alpha():
    rgb = np.full((100, 200, 3), 200, np.uint8)
    c = cutout(rgb, _rect_mask(100, 200, (20, 10, 50, 40)))
    assert c.bbox == (20, 10, 50, 40)
    assert c.rgba.shape == (40, 50, 4)
    assert (c.rgba[..., 3] == 255).all()
    assert c.mask_fraction == pytest.approx(0.1)


def test_cutout_fills_mask_holes():
    def holey(rgb):
        m = np.zeros(rgb.shape[:2], np.uint8)
        m[10:90, 20:120] = 255
        m[40:60, 60:80] = 40  # pale fabric the matting model missed
        return m
    c = cutout(np.full((100, 200, 3), 200, np.uint8), holey)
    assert (c.rgba[..., 3] == 255).all()


@pytest.mark.parametrize("box", [(0, 0, 5, 5), (0, 0, 200, 100)])
def test_cutout_mask_out_of_range(box):
    rgb = np.zeros((100, 200, 3), np.uint8)
    with pytest.raises(PipelineError) as e:
        cutout(rgb, _rect_mask(100, 200, box))
    assert e.value.code == ErrorCode.mask_out_of_range


# ---------------------------------------------------------------- color

def _rgba(parts, size=100):
    """parts: list of (rgb, rows, alpha); stacked vertically, total rows == size."""
    rows = []
    for rgb, n, a in parts:
        rows.append(np.tile(np.array([*rgb, a], np.uint8), (n, size, 1)))
    return np.vstack(rows)


def _validate(colors):
    for c in colors:
        Color.model_validate(c)
    weights = [c["weight"] for c in colors]
    assert weights == sorted(weights, reverse=True)
    assert sum(weights) <= 1.0001


def test_two_colors_weights():
    colors, neutral = extract_colors(_rgba([((200, 30, 30), 70, 255), ((20, 30, 90), 30, 255)]))
    _validate(colors)
    assert len(colors) == 2
    assert colors[0]["weight"] == pytest.approx(0.7, abs=0.01)
    assert colors[0]["hex"] == "#c81e1e"
    assert not neutral


def test_similar_shades_merge():
    colors, _ = extract_colors(_rgba([((200, 30, 30), 50, 255), ((205, 35, 32), 50, 255)]))
    assert len(colors) == 1
    assert colors[0]["weight"] == pytest.approx(1.0, abs=0.001)


def test_small_cluster_dropped():
    colors, _ = extract_colors(_rgba([((200, 30, 30), 95, 255), ((20, 200, 40), 5, 255)]))
    assert len(colors) == 1
    assert colors[0]["weight"] == pytest.approx(0.95, abs=0.01)


def test_transparent_pixels_ignored():
    colors, _ = extract_colors(_rgba([((20, 200, 40), 60, 0), ((30, 30, 160), 40, 255)]))
    assert len(colors) == 1 and colors[0]["weight"] == pytest.approx(1.0)


def test_neutral_gray():
    colors, neutral = extract_colors(_rgba([((128, 128, 128), 100, 255)]))
    _validate(colors)
    assert neutral and colors[0]["lch"][1] < NEUTRAL_CHROMA_MAX


def test_at_most_four_colors():
    parts = [((250, 0, 0), 20, 255), ((0, 200, 0), 20, 255), ((0, 0, 250), 20, 255),
             ((250, 250, 0), 20, 255), ((0, 0, 0), 20, 255)]
    colors, _ = extract_colors(_rgba(parts))
    _validate(colors)
    assert 1 <= len(colors) <= 4
