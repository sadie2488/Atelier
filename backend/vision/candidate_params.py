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
#
# V6.2 (bug (b), re-dispatch): pants/skirt/shorts' pad_x and pad_bottom were tuned far too tight
# for a hip/knee/ankle LANDMARK span, which only traces the model's own legs -- a wide-leg, baggy
# or flared garment's FABRIC extends well past that skeletal span (confirmed against
# fixtures/images: two wide-leg jean fixtures had a landmark span under 90px wide against a
# ~140-250px-wide visible garment, so the isolation region sliced through the middle of the pants
# and cut off almost all of the flare). pad_x is now generous for all three -- both left/right
# edges are the garment's OWN far edge here (there's no neighboring garment on either side), so
# there's no shared-edge reason to keep it tight, unlike pad_top. pad_bottom is a bit more
# generous too, but stays well short of pad_x since it still has to leave room to exclude shoes
# (pants) or bare shin (shorts/skirt, whose pad_bottom is now relative to the shorter hip->knee
# span used for isolation -- see `segmentation._ISOLATION_REGION_LANDMARKS` -- not hip->ankle).
REGION_PAD: dict = {
    "shirt": (0.15, 0.04, 0.12),
    "jacket": (0.15, 0.04, 0.12),
    "coat": (0.15, 0.04, 0.12),
    "dress": (0.08, 0.06, 0.10),
    "pants": (0.04, 0.15, 0.40),
    "skirt": (0.04, 0.35, 0.40),
    "shorts": (0.04, 0.35, 0.40),
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

# V6.1 isolation (re-dispatch: patterned-garment regression): a non-anchor cluster's SAME_FABRIC/
# area-ratio tests above (SAME_FABRIC_MAX_DELTA_E, SECONDARY_MAX_AREA_RATIO) can still wrongly
# drop a multi-color knit pattern -- a Fair Isle yoke's burgundy/pink colorwork is neither close
# enough in Lab to the cream anchor to pass SAME_FABRIC_MAX_DELTA_E, nor a small enough fraction
# of the anchor's area to pass SECONDARY_MAX_AREA_RATIO once its many small diamonds/strips are
# summed up as one k-means cluster. `_isolate_by_color` now also keeps any CONNECTED COMPONENT
# (not the whole cluster -- see below) of a dropped cluster that is spatially INTERLEAVED with
# the anchor: small enough on its own, and mostly ringed by already-kept fabric rather than by
# background/skin/a different garment. A component is judged interleaved, not a competing
# garment, when BOTH hold:
#   - its own pixel count is at most PATTERN_MAX_COMPONENT_FRAC of the anchor cluster's area (a
#     colorwork diamond/strip is a small fragment; a competing garment's visible piece -- a tank
#     under an open jacket, a skirt hem below a cropped top -- is comparable in size to what's
#     left of the garment it's competing with);
#   - dilating it by PATTERN_RING_PX and looking at just the new ring, at least
#     PATTERN_BOUNDARY_CONTACT_MIN of that ring is already-kept fabric, not the region outside
#     `base` or another dropped cluster (a pattern fragment sits almost entirely inside the
#     anchor's own fabric; a competing garment's visible piece borders exposed skin/background
#     along most of its real edge, since that's what makes it visible at all).
# This is evaluated per CONNECTED COMPONENT of the dropped cluster, not the cluster as a whole,
# because one k-means cluster can contain both harmless within-garment specular highlights (kept
# by this rule, which is fine -- they're the SAME garment, just a shinier patch) and one genuine
# competing-garment piece in the same color (dropped by this rule, because that piece alone fails
# the size/boundary test even though smaller flecks of the same cluster pass it).
# Tuned against fixtures/images on 2026-09-26 against two specific cases (see
# backend/vision/scripts/eval_fixtures.py for the full run):
#   - "red Whoa So Soft Shrunken Fairisle Cardigan Sweater #661720.png": the two pattern-color
#     k-means clusters had their largest fragments at 6.5%/9.5% of the anchor (cream) cluster's
#     area, each with >=0.59 boundary contact to the kept cream -- both must be kept.
#   - "black Leather Blazer #1c1c1c.webp": the visible denim mini-skirt's largest fragment was
#     10.4% of the anchor (black leather) area but only 0.33 boundary contact (most of its real
#     edge borders exposed skin, not the jacket) -- must stay dropped. The visible white tank's
#     largest fragment was 30.2% of the anchor area at 0.16 boundary contact -- must stay dropped.
#     A handful of small, high-boundary-contact fragments of the SAME cluster as the skirt turned
#     out to be specular highlights on the leather itself (confirmed by rendering them) -- keeping
#     those is correct, not a regression.
PATTERN_RING_PX = 3
PATTERN_BOUNDARY_CONTACT_MIN = 0.5
PATTERN_MAX_COMPONENT_FRAC = 0.20

# V6.1 isolation (re-dispatch): after assembling the kept mask (anchor + same-fabric + pattern
# fragments above), a knit pattern's fragments can still be separated from the anchor fabric and
# from each other by a hairline of dropped/background pixels at their own edges -- especially
# along the garment's own outer contour (collar, shoulder seam), where the gap isn't a fully
# enclosed "hole" (see `_fill_small_holes`'s own docstring) so it survives that check untouched.
# A small morphological closing bridges these hairline gaps so the knit reads as one piece; it is
# bounded to never grow past `base` itself (the clothes-category evidence), so it cannot pull in
# a whole separate garment even if that garment sits just past the closing radius. Tuned against
# the Fairisle cardigan fixture above (visible shoulder/collar shredding before this closing).
PATTERN_CLOSING_RADIUS_PX = 3

# ARTIFACT_SPEC: crop to alpha bbox plus this padding fraction on every side.
CROP_PAD_FRACTION = 0.02

# V4/V6: pixels eroded off the alpha mask before k-means color sampling only (never applied to
# the shipped cutout's own alpha) -- trims the antialiased background/skin/hair blend ring right
# at the cutout boundary before it can seed its own cluster. Tuned against fixtures/images on
# 2026-09-26 (see backend/vision/scripts/eval_fixtures.py); re-tune once golden references exist.
COLOR_SAMPLE_EROSION_PX = 2

# V2 isolation (tight waist-down crops, re-dispatch): even when the pose-derived region box is
# well-formed (non-degenerate, tall enough per _MIN_BOTTOM_BOX_HEIGHT_FRAC), BlazePose can still
# fit a full 33-point skeleton onto a hip-only or tight waist-down crop by HALLUCINATING a
# plausible-looking leg pose that is spatially wrong -- the box ends up well-formed but placed
# over the wrong part of the frame, or it's correctly placed but far too NARROW for a baggy/
# wide-leg garment whose fabric extends well past the leg landmarks even with REGION_PAD's
# generous pad_x. Ground-truth signal, independent of BlazePose's own (misleadingly high, in
# exactly these cases) visibility/presence scores: the pose-derived box should contain MOST of
# the `clothes`-category pixels visible anywhere in the frame, since these product photos show
# one garment against a plain background. Tuned against fixtures/images on 2026-09-27: the five
# bottoms this was diagnosed against (see backend/vision/segmentation.py's V2 module docstring --
# bottom_62acf6, bottom_6a01d4, bottom_d7459a, bottom_dd2bea, bottom_f91783) had their
# landmark-derived box capture only 2%-40% of the frame's `clothes` pixels; every other bottoms
# fixture (already isolating correctly) captured 100% (its box already spans ~the whole frame,
# either via the existing degenerate/too-short fallbacks above or a generously-padded full-length
# pose). 0.5 sits with wide margin on both sides of that split.
MIN_BOTTOM_REGION_CLOTHES_COVERAGE_FRAC = 0.5

# V2 isolation (re-dispatch): in the pose-free bottoms fallback specifically (`segmentation.
# segment`'s `elif is_bottom` branch), a non-anchor color cluster whose mass sits mostly ABOVE the
# fallback core probe's own top edge (the waistband line) is dropped even if it would otherwise
# pass the SAME_FABRIC/secondary-area-ratio tests in `_isolate_by_color` -- a cropped top garment
# bleeding in from above the waistband is exactly what those two tests can't reliably catch on
# their own (a white tank top and a pale/light-wash bottom can land within SAME_FABRIC_MAX_DELTA_E
# of each other in Lab, since both are simply light and low-chroma). Confirmed against "livin it
# up Stretch Curvy Low-Rise Perfect Shortie #99b3be.png": its white-tank cluster was only
# deltaE=11.1 from the light-denim anchor (under SAME_FABRIC_MAX_DELTA_E=15, so kept by that test
# alone) but had 80% of its own pixels above the waistband line, against 4-6% for the shorts'
# three genuine clusters -- 0.5 sits with wide margin on both sides of that split. Only applied in
# the pose-free fallback (not the landmark-trusted core-probe path used for tops/jackets/dresses,
# where a collar or trim legitimately extends above the probe's own top edge as part of the SAME
# garment).
WAISTBAND_EXCLUDE_MAX_ABOVE_FRAC = 0.5

# V2 isolation (re-dispatch): a candidate mask whose alpha fills more than this fraction of its
# OWN bounding box is a sign the mask is just the region/crop box itself with no garment
# silhouette carved out of it -- e.g. a hip-only crop where the entire visible frame is clothing,
# so `clothes` fills the box wall-to-wall and the "cutout" is really a rectangle, not a garment
# shape (confirmed on "blue daylight Next Level High-Waisted Shortie #849eb1.png": its pre-fix
# balanced mask filled 95.1% of its own bbox). NOT a blanket completeness bar -- real,
# correctly-isolated garments legitimately reach 88-91% bbox fill on some shorts fixtures -- only
# a last-resort trigger, checked AFTER the coverage-ratio fix above already ran, to retry once
# more with the pose-free whole-frame fallback (see `segmentation.segment`).
RECTANGULAR_BBOX_FILL_MAX = 0.90

# V3 edge quality (bottoms re-dispatch, human request): "the bottoms look better. Try and keep
# edges straight, as they tend to be straight or slightly curved (like the bottom of shorts)."
# Tunables for backend/vision/edge_regularize.py's waistband/hem regularization (pants/skirt/
# shorts only) -- see that module's docstring for the algorithm. Tuned by eye against the 9 real
# bottoms in the closet DB (pants: bottom_6b839f, bottom_e7883c, bottom_62acf6, bottom_6a01d4;
# shorts: bottom_f91783, bottom_418fa7, bottom_36a1e0, bottom_d7459a, bottom_dd2bea) via
# backend/vision/scripts/reprocess_item.py, 2026-09-27.

# Minimum number of boundary (x, y) points required to attempt a robust fit at all; below this,
# the edge is left untouched rather than fit to a handful of points (e.g. a hem barely in frame).
EDGE_MIN_FIT_POINTS = 8

# Iterative-reweighting rounds for the robust (outlier-rejecting) polynomial fit.
EDGE_FIT_MAX_ITER = 4

# Floor for the outlier-rejection threshold (median-absolute-deviation-based) so a near-perfect
# boundary (MAD ~= 0) doesn't reject nearly every point over sub-pixel noise.
EDGE_OUTLIER_FLOOR_PX = 2.0

# A straight-line fit whose RMSE against the boundary points is at or below this is kept straight
# (no quadratic escalation) -- most waistbands and jean hems are already this straight once mask
# noise is robust-fit-averaged out; escalating them to a curve would just be overfitting noise.
EDGE_LINE_RMSE_OK_PX = 2.5

# Cap on a quadratic fit's own "sag" (its max deviation from the straight line implied by its
# endpoints, over the observed span) once escalated past EDGE_LINE_RMSE_OK_PX -- keeps the
# allowed curve "gentle" (a shorts hem's real curve) rather than a wild parabola chasing a couple
# of noisy points at one end.
EDGE_MAX_CURVATURE_PX = 8.0

# Give-up gate: if even a (curvature-capped) quadratic fit still misses the boundary by more than
# this RMSE (measured against every boundary point, not just the fit's own inliers), the boundary
# is left unregularized rather than forced -- see edge_regularize._fit_edge_curve's docstring.
# Confirmed against "dark indigo wash Super High-Waisted Baggy Wide-Leg Jean #e2e7ea.webp"
# (bottom_e7883c): its mask had a pre-existing thin bridge to a stray blob elsewhere in frame, so
# its top-boundary points spanned most of the canvas height (residual >>100px) -- forcing a fit
# through that deleted ~65% of the correctly-segmented garment. A clean waistband/hem's robust-fit
# RMSE is under a few pixels even with real fraying, so this sits with wide margin above that.
EDGE_GIVE_UP_RMSE_PX = 20.0

# Guards on the pants/shorts leg split (edge_regularize._split_leg_masks): the candidate crotch
# row must be at or below this fraction of the mask's own height (a real crotch is well below the
# waistband, never at the very top -- rules out a stray fragment touching the top of the mask,
# e.g. a hanger clip, from masquerading as an early "split"), and each of the two resulting leg
# components must be at least this fraction of the mask's total area (rules out a small stray
# fragment being accepted as a "leg" anywhere in the mask, not just near the top). Confirmed
# against "livin it up Stretch Curvy Low-Rise Perfect Shortie #99b3be.png" (bottom_dd2bea): an
# unguarded split found "2 components" at row 0 (a 758px hanger-clip fragment above the waistband
# vs. the 51909px garment, 1.4% vs. 98.6% of the mask) and fit a hem to the fragment, deleting
# ~12% of the correctly-segmented shorts when that bogus fit was applied.
EDGE_LEG_SPLIT_MIN_Y_FRAC = 0.15
EDGE_LEG_SPLIT_MIN_AREA_FRAC = 0.15

# Tolerance band (pixels, perpendicular... approximated as vertical, which is accurate for these
# near-horizontal boundaries) around the fitted curve: mask pixels beyond it are trimmed (spikes),
# gaps within it are filled (small notches/holes from mask noise). Generous enough that a
# modestly frayed/distressed hem stays slightly irregular rather than perfectly ruled, per the
# human's ask, while still killing the big spikes/notches that read as "ragged."
EDGE_TOLERANCE_PX = 4

# Light morphological open+close radius applied to the side seams only (never a line/curve fit --
# a flared/baggy leg's silhouette is a real shape, not noise). Small on purpose: this is meant to
# denoise jagged single-pixel contour steps, not reshape the garment.
EDGE_SIDE_SMOOTH_PX = 1

# Guard on the side-seam smoothing above: max allowed drop in largest-connected-component
# fraction (see edge_regularize._largest_cc_fraction) before the smoothing pass is rejected in
# favor of the un-smoothed mask. Catches a high-waisted/baggy garment whose waist-to-leg bridge
# is only 1-2px wide in the segmenter's own (blocky) mask -- opening at EDGE_SIDE_SMOOTH_PX would
# sever it, turning one connected garment into two-plus components and failing
# checks.structural_largest_cc_ratio outright. Confirmed against "dark indigo wash Super
# High-Waisted Baggy Wide-Leg Jean #e2e7ea.webp" (bottom_e7883c): pre-fix, opening split it into
# 3 components (largest 60% of total, vs. 90%+ before regularization).
EDGE_CONNECTIVITY_DROP_TOL = 0.05

# Hard safety net: the regularized mask is clipped to a dilation of the ORIGINAL (pre-
# regularization) mask by this many pixels, intersected with the clothes category -- it can never
# grow onto skin/background by more than this, and never past what the segmenter itself called
# "clothes" to begin with (V-S1 stays intact: skin exclusion is still MediaPipe-category-only).
EDGE_SAFETY_GROW_PX = 3

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

