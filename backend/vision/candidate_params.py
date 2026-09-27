"""V-S4: tuned candidate post-processing values.

Tuned by eye against fixtures/images (18 retail photos on models) on 2026-09-26, before the
human golden-reference pass existed (V-Q4 golden references are pending; see the vision lane's
report to the PM). Re-tune here once golden references land, and update this comment with the
new fixture run.

The three candidates (V-S3) come from ONE person-segmentation + pose pass. They differ only in
post-processing: how hard we erode/dilate the raw (clothes-category ∩ pose-region ∩ largest-person)
mask, and whether small enclosed holes get filled.
"""

# Erosion/dilation radius in pixels, applied to the boolean mask on the *preprocessed*
# (long-side-1024) image before cropping. Positive = dilate, negative = erode.
CANDIDATE_MORPH_RADIUS_PX = {
    "tight": -3,      # pull mask in from the clothes/skin boundary
    "balanced": 0,     # raw category mask, holes filled only
    "generous": 3,      # push mask out slightly past the boundary
}

# Padding fraction (of landmark span) added around the pose-derived region box before
# intersecting with the clothes-category mask, per V-S5. Kept as the symmetric default for the
# V-S7 canonical top/bottom mismatch-signal boxes (segmentation.segment); the per-candidate
# region box uses the asymmetric REGION_PAD table below instead.
REGION_PAD_FRACTION = 0.12

# V-S5 tightening (re-dispatch fix): asymmetric padding as (pad_top, pad_bottom, pad_x), each a
# fraction of the landmark span, so the region box stays generous on the garment's OWN far edge
# (room for a collar above the shoulders, a cuff below the ankle) but tight on the edge shared
# with a NEIGHBORING garment (hip line, for a top vs. a bottom) -- that shared edge is exactly
# where fixtures/images shows a skirt hem or shirt hem bleeding into the wrong cutout (see
# backend/vision/segmentation.py's `_isolate_by_color` docstring for the other half of that fix).
# Tuned by eye against fixtures/images on 2026-09-26; re-tune once golden references exist.
REGION_PAD: dict = {
    "shirt": (0.15, 0.04, 0.12),
    "jacket": (0.15, 0.04, 0.12),
    "coat": (0.15, 0.04, 0.12),
    "dress": (0.08, 0.06, 0.10),
    "pants": (0.04, 0.10, 0.12),
    "skirt": (0.04, 0.10, 0.12),
    "shorts": (0.04, 0.10, 0.12),
}

# V6 isolation (re-dispatch fix): within the pose region, a "core probe" band -- (frac_start,
# frac_end) of the vertical span between the garment's near and far landmark groups -- used to
# pick which color-coherent segment of the `clothes` category is the requested garment (see
# `_isolate_by_color`). Deliberately WIDE (most of the garment's own extent, excluding only a
# thin sliver at each end nearest a neighboring garment/hair) rather than a narrow "center"
# band: a narrow band tuned to "torso center" dropped a patterned garment's own trim/yoke color
# whenever the pattern sat outside that band (a fairisle cardigan's colorwork yoke sits in the
# top third, not the center) -- a wide band still lets the true target garment win by area (a
# worn-open jacket's own fabric covers far more of the wide band than the inner layer it
# exposes) while still excluding the extremities where a different garment actually intrudes.
CORE_PROBE_BAND: dict = {
    "shirt": (0.10, 0.90),
    "jacket": (0.05, 0.80),
    "coat": (0.05, 0.80),
    "dress": (0.08, 0.85),
    "pants": (0.08, 0.85),
    "skirt": (0.08, 0.85),
    "shorts": (0.08, 0.85),
}

# V6: minimum fraction of the core-probe pixels a color cluster must cover to be judged part of
# the requested garment (see `_isolate_by_color`).
CORE_PROBE_MIN_COVERAGE = 0.15

# V6: a non-anchor color cluster is kept alongside the best-covering ("anchor") one only if its
# own total area is at most this fraction of the anchor's -- a trim/pattern color is a minority
# of its garment's fabric; a competing garment (inner layer under an open jacket) usually is not.
# Only applies to a cluster that is NOT already judged the same fabric (see
# SAME_FABRIC_MAX_DELTA_E below).
SECONDARY_MAX_AREA_RATIO = 0.35

# V6: a non-anchor color cluster within this CIEDE2000 distance of the anchor's own centroid is
# judged the SAME garment fabric under different lighting/shading (a fold, a seam, a light
# source from one side) rather than a different segment -- always kept, regardless of area or
# core-probe coverage. A shading gradient can easily split one garment's fabric into two k-means
# clusters that are each close to half its area, which the area-ratio rule alone would wrongly
# read as "a competing garment." Below `contract.enums.SECONDARY_MIN_DELTA_E` (20, V-C3's own
# bar for "clearly a different color") so it only catches genuine same-fabric shading, not a
# garment's own contrasting trim.
SAME_FABRIC_MAX_DELTA_E = 15

# V6: number of Lab color clusters used to split the region's `clothes` mask into candidate
# garment segments, and the pixel sample cap for fitting them (mirrors color.py's own sampling
# so this stays fast -- see `_isolate_by_color`).
ISOLATION_KMEANS_K = 4
ISOLATION_SAMPLE_PIXELS = 20000

# V6: below this many `clothes` pixels, skip color-segment isolation entirely -- too few pixels
# for k-means clusters to mean anything, and the mask is already tiny.
ISOLATION_MIN_PIXELS = 400

# ARTIFACT_SPEC: crop to alpha bbox plus this padding fraction on every side.
CROP_PAD_FRACTION = 0.02

# V4/V6: pixels eroded off the alpha mask before k-means color sampling only (never applied to
# the shipped cutout's own alpha) -- trims the antialiased background/skin/hair blend ring right
# at the cutout boundary before it can seed its own cluster. Tuned against fixtures/images on
# 2026-09-26 (see backend/vision/scripts/eval_fixtures.py); re-tune once golden references exist.
COLOR_SAMPLE_EROSION_PX = 2

# Minimum soft-segmentation confidence to count a pixel as belonging to the chosen person
# (V-S6: largest person by mask area). Unused since pose-landmarker segmentation masks are not
# requested (see mp_models.pose_landmarker's docstring); kept for when that mediapipe bug is fixed.
PERSON_MASK_THRESHOLD = 0.5

# PoseLandmarker min_pose_detection_confidence / min_pose_presence_confidence. The default
# (0.5) misses the ~50% of fixtures/images that are waist-down or knee-down crops (pants,
# shorts, skirts): no head/torso in frame, so BlazePose's own confidence stays under 0.5 even
# though the legs it does see are clean. Tuned down against fixtures/images on 2026-09-26;
# spot-checked against fixtures/flatten (no person) at this value with only one false positive
# out of 5 sampled flat-lays -- acceptable for now, revisit once golden references exist.
POSE_MIN_CONFIDENCE = 0.1

