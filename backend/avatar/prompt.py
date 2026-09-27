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

PROMPT_VERSION = "v1"
MODEL = GEMINI_IMAGE_MODEL  # pinned; never "latest" (A-R8)

_PRESERVE = (
    "Preserve the person's face, identity, body shape, pose, and the photo's background and "
    "lighting exactly as in the first image -- change only the clothing. Do not alter the "
    "person's proportions, skin tone, or facial features. Output a single photorealistic image "
    "of the same person, no text, no collage, no side-by-side comparison."
)


def build_prompt(has_jacket: bool, is_dress: bool) -> str:
    """The instruction sent alongside images in this fixed order:
    [person_photo, top_or_dress_cutout, bottom_cutout (omitted for a dress), jacket_cutout?].
    A dress is a top: it layers over the bottom, no exclusion logic (A-R5).
    """
    if is_dress:
        garment_line = (
            "The second image is a dress. Replace the person's current outfit with this dress, "
            "worn naturally over their body, matching its actual color and pattern."
        )
    else:
        garment_line = (
            "The second image is a top and the third image is a bottom (pants, shorts, or a "
            "skirt). Replace the person's current outfit with this top worn naturally over this "
            "bottom, matching each garment's actual color and pattern."
        )
    jacket_line = (
        " The last image is a jacket or coat; layer it over the top, worn naturally as an open "
        "or closed outer layer."
        if has_jacket else ""
    )
    return (
        "You are compositing a virtual try-on photo from reference images. The first image is "
        "the person to dress. " + garment_line + jacket_line + " " + _PRESERVE
    )
