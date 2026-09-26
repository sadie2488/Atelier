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
# intersecting with the clothes-category mask, per V-S5.
REGION_PAD_FRACTION = 0.12

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

