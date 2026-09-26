# Artifact spec (P0.7) — garment cutouts and placement anchors

PM-owned, frozen with the contract. Vision produces artifacts to this spec (V3); avatar
consumes them (A4 placement). Neither lane changes it; report problems to the PM.

## Cutout image
- PNG, RGBA, 8-bit. Background fully transparent (alpha 0); all four corners alpha 0.
- Cropped to the alpha bounding box plus 2% padding on every side, then scaled so the long
  side is at most 1024 px. No fixed canvas size: bodies differ, so placement never relies on
  pixel positions.
- Stored at `media/items/<slug>.png` (URL `/media/items/<slug>.png`); temp candidates at
  `media/tmp/<temp_handle>_<index>.png`.

## Anchors (landmark-normalized)
Each cutout carries the MediaPipe Pose landmarks of the **model it was cut from**, expressed in
the cutout's own coordinates, normalized: `x = px / width`, `y = py / height`, so (0,0) is the
top-left corner and (1,1) the bottom-right. Values may fall slightly outside [0,1] when a
landmark lies beyond the crop (e.g. shoulders on a sleeveless top).

Names follow MediaPipe (person's own left/right, so `left_shoulder` is on the image's right
for a front-facing model):

| garment_type | required anchors |
|---|---|
| shirt | left_shoulder, right_shoulder, left_hip, right_hip |
| jacket, coat | left_shoulder, right_shoulder, left_hip, right_hip, left_wrist, right_wrist |
| dress | left_shoulder, right_shoulder, left_hip, right_hip, left_ankle, right_ankle |
| pants, shorts, skirt | left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle |

Anchors are a **database-only field**: stored on the item document as
`anchors: {"<name>": [x, y], ...}` (also kept with the temp handle between analyze and save).
They are not part of the API response models.

## Placement (avatar A4)
- Primary anchor pair: shoulders for shirt, jacket, coat and dress; hips for pants, shorts and
  skirt.
- Fit a similarity transform (uniform scale, rotation, translation) that maps the cutout's
  primary pair onto the avatar's same two landmarks. Use the secondary anchors (hips, ankles)
  only to sanity-check the vertical extent; never stretch non-uniformly.
- Draw order: bottom → top-or-dress → jacket.
- An item missing a required anchor falls back to its alpha bounding box aligned to the
  avatar's landmark span for that region; log it, never fail the render.
