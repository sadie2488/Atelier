"""A-R9: the Gemini generation prompt is a versioned artifact. Bump PROMPT_VERSION whenever the
wording changes and re-run a small eval set (see backend/avatar/scripts/gen_probe.py) before
trusting a new version in the demo. The model version is pinned in backend/config.py and kept
beside the prompt here deliberately -- a prompt tuned against one image model does not
necessarily transfer to another.

A-R7: this is the primary try-on path (one call, instruction-following, tolerates stylized
input). Its known weakness is garment fidelity (texture/print/logo drift); that is acceptable
here. Identity drift (face, body, pose, background) is not -- the prompt weights preservation
over fidelity, and A-R10's ΔE check gates the swap on color only.
"""
from backend.config import GEMINI_IMAGE_MODEL

PROMPT_VERSION = "v5"  # v5: replace all clothing; layer bottom -> top -> jacket; plain white background (human request)
# v4: the clothes must fit naturally (human request)
# v3: the face must not be edited at all; full-length framing (human request)
# v2: a dress outfit now also sends and describes the bottom (A-R5/A-R7)
MODEL = GEMINI_IMAGE_MODEL  # pinned; never "latest" (A-R8)

_REPLACE = (
    "Remove every piece of clothing the person is currently wearing and replace it completely "
    "with the garments shown; none of their original clothing may remain visible."
)

_FIT = (
    "Make the clothes fit naturally: sized to this person's body, with realistic drape, folds, "
    "and shadows, as if they were really wearing them."
)

_FACE = (
    "The person's face must not be edited or modified in any way: keep the exact same face, "
    "features, expression, hair, skin tone, makeup and accessories pixel-faithful to the first "
    "image. Do not beautify, retouch, re-light, reshape, or replace the face, and do not swap in "
    "a different person."
)

_PRESERVE = (
    "Preserve the person's identity, body shape, pose, and lighting exactly as in the first "
    "image -- change only the clothing. Do not alter the person's proportions or skin tone. Keep "
    "the same full-length framing as the first image, head to feet, with the whole face visible "
    "and uncropped."
)

_BACKGROUND = (
    "The first image has its background removed: keep the person on the same plain white "
    "background, with no scenery, floor, props, or added shadows. Output a single photorealistic "
    "image of the same person, no text, no collage, no side-by-side comparison."
)


def build_prompt(has_jacket: bool, is_dress: bool) -> str:
    """The instruction sent alongside images in this fixed order:
    [person_photo, top_or_dress_cutout, bottom_cutout, jacket_cutout?]. A dress is a top: it
    layers over the bottom, no exclusion logic (A-R5) -- so the bottom is sent and described for
    a dress outfit too. Layer order, body outward: bottom, then top (or dress), then jacket.
    """
    top_word = "dress" if is_dress else "top"
    garment_line = (
        f"The second image is a {top_word} and the third image is a bottom (pants, shorts, or a "
        "skirt)" + (", and the last image is a jacket or coat" if has_jacket else "") + ". "
        "Match each garment's actual color and pattern."
    )
    layer_line = (
        "Layer the garments from the body outward: the bottom first, then the "
        f"{top_word} worn over this bottom"
        + (", then the jacket as the outermost layer over the " + top_word + ", worn naturally open or closed." if has_jacket else ".")
    )
    return (
        "You are compositing a virtual try-on photo from reference images. The first image is "
        "the person to dress. " + garment_line + " " + _REPLACE + " " + layer_line + " " + _FIT
        + " " + _FACE + " " + _PRESERVE + " " + _BACKGROUND
    )
