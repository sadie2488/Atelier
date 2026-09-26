"""A5: local compositing. Draw order bottom -> top-or-dress -> jacket (A-R4). A dress is a top;
it layers over the bottom -- no exclusion logic (A-R5).
"""
from typing import Optional

from PIL import Image

from contract.enums import GarmentType

from .placement import place_item
from .rig import Rig

Layer = tuple[Image.Image, dict, GarmentType]  # (cutout, anchors, garment_type)


def composite_outfit(
    avatar_img: Image.Image,
    canvas_size: tuple[int, int],
    rig: Rig,
    bottom: Optional[Layer] = None,
    top: Optional[Layer] = None,
    jacket: Optional[Layer] = None,
) -> Image.Image:
    result = avatar_img.copy()
    for item in (bottom, top, jacket):
        if item is None:
            continue
        cutout, anchors, garment_type = item
        layer = place_item(cutout, anchors, garment_type, rig, canvas_size)
        result = Image.alpha_composite(result, layer)
    return result
