"""Flat-lay RGB -> transparent cutout cropped to the garment, plus bbox in the source image."""
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

import numpy as np
from scipy import ndimage

from contract.enums import ErrorCode, MASK_MAX_FRACTION, MASK_MIN_FRACTION
from app.pipeline import PipelineError

MaskFn = Callable[[np.ndarray], np.ndarray]  # RGB uint8 -> alpha uint8 (0..255), same HxW


@dataclass
class Cutout:
    rgba: np.ndarray                      # cropped to bbox, alpha 0 outside the garment
    bbox: tuple[int, int, int, int]       # x, y, w, h in the preprocessed image
    mask_fraction: float


@lru_cache(maxsize=1)
def _session():
    from rembg import new_session
    return new_session(os.environ.get("REMBG_MODEL", "u2net"))


def rembg_mask(rgb: np.ndarray) -> np.ndarray:
    from rembg import remove
    return np.asarray(remove(rgb, session=_session(), only_mask=True))


def _close_and_fill(mask: np.ndarray) -> np.ndarray:
    """Pale fabric on a pale sheet leaves gaps in the mask; close small gaps and fill enclosed holes."""
    r = max(1, round(max(mask.shape) * 0.01))
    closed = ndimage.binary_closing(mask, structure=np.ones((2 * r + 1, 2 * r + 1)), border_value=0)
    return ndimage.binary_fill_holes(closed | mask)


def cutout(rgb: np.ndarray, mask_fn: MaskFn = rembg_mask) -> Cutout:
    alpha = np.asarray(mask_fn(rgb)).copy()
    if alpha.ndim == 3:
        alpha = alpha[..., 0].copy()
    mask = _close_and_fill(alpha >= 128)
    alpha[mask & (alpha < 128)] = 255  # gaps filled by _close_and_fill become opaque
    fraction = float(mask.mean())
    if not MASK_MIN_FRACTION <= fraction <= MASK_MAX_FRACTION:
        raise PipelineError(
            ErrorCode.mask_out_of_range,
            f"Garment mask covers {fraction:.0%} of the photo; expected "
            f"{MASK_MIN_FRACTION:.0%}–{MASK_MAX_FRACTION:.0%}. Lay the item flat on a plain sheet.",
        )
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    rgba = np.dstack([rgb, np.where(mask, alpha, 0).astype(np.uint8)])[y0:y1, x0:x1]
    return Cutout(rgba=rgba, bbox=(x0, y0, x1 - x0, y1 - y0), mask_fraction=fraction)
