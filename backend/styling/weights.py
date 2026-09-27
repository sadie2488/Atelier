"""Every tunable number for the styling lane (S-T1). Strategy weights, hue bands, chroma
thresholds, L* spread minimums, diversity caps, secondary-color weight -- all here, nothing
numeric governing recommendation behavior lives anywhere else in this lane.

Tuning after the hackathon means editing values in this file, never refactoring code.
"""
from contract.enums import NEUTRAL_CHROMA_MAX, OUTFITS_MAX, OUTFITS_MAX_PER_STRATEGY, OUTFITS_MAX_SHARING_GARMENT

# ---- diversity caps (contract-enforced invariants; mirrored here so this lane has one
# place to read them from, per S-T1 -- the contract in contract/enums.py remains the
# frozen source of truth and must not drift from these).
OUTFITS_MAX = OUTFITS_MAX
OUTFITS_MAX_PER_STRATEGY = OUTFITS_MAX_PER_STRATEGY
OUTFITS_MAX_SHARING_GARMENT = OUTFITS_MAX_SHARING_GARMENT

# ---- pairwise color-harmony scoring (scorer.py), all scores in [0, 1]

# Either piece is a strict neutral (chroma < NEUTRAL_CHROMA_MAX, contract V-C5) paired with a
# true chromatic partner (not itself an everyday-neutral base): neutrals pair with everything,
# so this is a high, flat score regardless of the partner's hue (E1/E2/E3).
NEUTRAL_PAIR_SCORE = 0.90

# A strict neutral paired with an everyday-neutral BASE color (navy/denim/olive/camel/beige/
# brown/black-ish muted tones) instead of a true chromatic: both pieces read as "neutral", so
# this is safe but only as interesting as its lightness contrast -- human ratings show flat,
# similar-L* pairs (cream+beige, brown+black) as middling (~0.5, E9/E11) while big-L*-spread
# pairs (navy+white, denim+white) read as high as a neutral+chromatic pair (E1/E3). Score
# ramps from NEUTRAL_LOW_CONTRAST_SCORE up to NEUTRAL_PAIR_SCORE as |L*a - L*b| grows from
# NEUTRAL_LOW_CONTRAST_L_MIN to NEUTRAL_LOW_CONTRAST_L_MAX.
NEUTRAL_LOW_CONTRAST_SCORE = 0.50
NEUTRAL_LOW_CONTRAST_L_MIN = 30.0
NEUTRAL_LOW_CONTRAST_L_MAX = 45.0

# Same color family (contract/colors.json), different lightness: a monochrome-leaning pair.
# Score rises toward MONOCHROME_BASE + MONOCHROME_L_BONUS as the L* spread grows, capped at
# MONOCHROME_L_SPREAD_TARGET. Human ratings on tonal same-family pairs (light_blue+navy,
# pink+red, E8/E12) put these solidly in the middle -- pleasant but flat, well below a
# genuine harmony match -- so the base and cap are lower than earlier tonal-pair guesses.
MONOCHROME_BASE = 0.40
MONOCHROME_L_BONUS = 0.30
MONOCHROME_L_SPREAD_TARGET = 60.0

# S-S2 rung 4 (monochrome_highlight): eligibility gate, not a scoring term. A same-family
# top+bottom pair only qualifies for this strategy label once their L* values are far enough
# apart that the look reads as deliberately tonal rather than flat/same-shade. Distinct from
# MONOCHROME_L_SPREAD_TARGET above, which shapes the *score* of an already-same-family pair
# regardless of strategy label.
MONOCHROME_HIGHLIGHT_MIN_L_SPREAD = 20.0

# Analogous: hue angle <= 40 degrees apart (S-S2 rung 3). Score falls off mildly with angle.
HUE_ANALOGOUS_MAX_DEG = 40.0
ANALOGOUS_BASE_SCORE = 0.80
ANALOGOUS_HUE_PENALTY = 0.30

# Complementary: hue angle 137-210 degrees apart, at least one piece low-chroma (S-S2 rung 3).
# The lower bound was widened from 150 to 137 (numerically, from the fixture colors' actual
# LCH hue angles, never from names -- S-C2): human ratings show hue-diff a strong predictor
# of a bright complementary pair's likability once past ~137 degrees apart -- blue+orange at
# ~140 degrees works (E7), while purple+yellow at ~135 and red+green at ~109 (further from
# complementary) read as costume-y (E6/E10) and stay in the lower default-scored band below.
HUE_COMPLEMENTARY_MIN_DEG = 137.0
HUE_COMPLEMENTARY_MAX_DEG = 210.0
COMPLEMENTARY_LOW_CHROMA_MAX = 20.0
COMPLEMENTARY_SCORE = 0.85
# Multiplier when neither piece is low-chroma (both pieces bright/saturated). Raised from 0.6
# so a bright-but-genuinely-complementary pair (E4 camel+navy, E7 blue+orange) still lands
# solidly above the "no relationship recognized" default, rather than being scored as poorly
# as an unrelated hue pair.
COMPLEMENTARY_HIGH_CHROMA_PENALTY = 0.88

# Neither neutral, neither analogous/complementary, but one piece is an everyday-neutral
# base color (navy/denim/olive/camel/beige/brown, contract/colors.json): still a reasonably
# safe pairing (S-S2 rung 2), just not a strong color-theory match.
EVERYDAY_NEUTRAL_PAIR_SCORE = 0.70

# No harmony relationship recognized by this lane's rungs.
DEFAULT_PAIR_SCORE = 0.35

# S-C3: a secondary color contributes but at reduced weight relative to primary (weight 1.0).
SECONDARY_COLOR_WEIGHT = 0.5

# Combining top-bottom (the core pairing) with an optional jacket layer (S-O3): the jacket's
# pairings with top and bottom each count for less than the core top-bottom pairing.
PRIMARY_PAIR_WEIGHT = 1.0
JACKET_PAIR_WEIGHT = 0.5

# A jacket variant is only offered if its average compatibility with top and bottom clears
# this bar; otherwise that jacket is silently skipped for that combination (not an error).
JACKET_MIN_COMPATIBILITY = 0.4

# Re-exported for readability where scorer.py needs the shared neutral-chroma threshold.
NEUTRAL_CHROMA_MAX = NEUTRAL_CHROMA_MAX

# ---- variety in selection (S4, human request: "generate outfits should generate different
# ones each time"). The scorer stays pure and deterministic (S-C1) -- these tunables only
# affect which of the *eligible, rule-satisfying* candidates get picked in select.py, never
# their scores.

# Quality floor for the candidate pool eligible for random selection: a candidate qualifies if
# its score clears this absolute bar, OR (union, not intersection -- this is what keeps a weak
# closet non-empty per S-L3) it is within VARIETY_POOL_MARGIN of the best score seen. Everything
# below both bars is excluded from variety entirely, even under a low limit.
VARIETY_MIN_SCORE = 0.6
VARIETY_POOL_MARGIN = 0.15

# Weighted-random-without-replacement exponent: sampling weight = max(score, epsilon) ** this.
# Higher = more tightly weighted toward the top of the pool (less variety); lower = closer to
# uniform random among the pool (more variety, including weaker-but-still-eligible pairs).
VARIETY_SCORE_EXPONENT = 3.0

# Multiplier applied to a candidate's sampling weight when it appeared in the immediately
# previous response and there weren't enough fresh alternatives to exclude repeats outright
# (see select.py's exclude-vs-downweight rule). Small but nonzero: a repeat is unlikely, not
# impossible, when the pool is otherwise thin.
VARIETY_REPEAT_PENALTY = 0.15

# ---- explanations (S-E4): the whole batch of Gemini explanations for one
# POST /api/outfits/generate response must return within this fixed wall-clock budget,
# regardless of how many outfits are being explained or how slow Gemini is. Any explanation
# not finished by the deadline falls back to its static per-strategy text instead of blocking
# the response.
EXPLAIN_BUDGET_SECONDS = 2.5

# A sandwich explanation only claims the jacket and bottom "share a color" when their primary
# colors are this close (CIEDE2000); otherwise it says they share a family. Wording only --
# never affects scores or strategy selection.
EXPLAIN_SHARED_COLOR_MAX_DELTA_E = 10.0

# ---- insights (backend/styling/insights.py, GET /api/insights/palette): closet-wide
# summary heuristics that lean on the pair scorer, so their tunables live here too (S-T1).

# Threshold above which a synthetic top-family/bottom pairing counts as "pairs well" for the
# "Adding a <family> top would pair with N of your bottoms" observation.
INSIGHTS_PAIR_GOOD_THRESHOLD = 0.6

# ---- colour-dressing guide (backend/styling/pairing_guide.py; "A Pair & A Spare" chart).
# Additive adjustment to a pair's score (top-bottom at full weight, jacket pairs averaged into
# the jacket term) by what the guide says about the pair. Never touches score_color_pair, so
# the 12 expectations are unaffected; it only nudges outfit scores / ranking.
GUIDE_COMPLEMENTARY_BONUS = 0.04
GUIDE_TONAL_BONUS = 0.03
GUIDE_NEUTRAL_BONUS = 0.0
GUIDE_UNLISTED_PENALTY = -0.04

# Denim special case: a blue bottom (pants/shorts/skirt) reads as light-wash denim (guide "light
# blue") above this L*, dark/indigo denim (guide "navy") at or below it. "Blue" = hue in the
# band below with at least this chroma (below it the bottom is grey/black by nearest swatch).
DENIM_LIGHT_L_MIN = 55.0
DENIM_HUE_MIN_DEG = 200.0
DENIM_HUE_MAX_DEG = 300.0
DENIM_MIN_CHROMA = 4.0

# Seasonal palette read (insights): mean L*, mean chroma and warm share of the closet's
# non-neutral items. A hue counts as warm when it lies outside [SEASON_COOL_HUE_MIN,
# SEASON_COOL_HUE_MAX) (reds/oranges/yellows/browns); inside is cool (greens to purples).
SEASON_MIN_ITEMS = 2
SEASON_COOL_HUE_MIN = 105.0
SEASON_COOL_HUE_MAX = 330.0
SEASON_LIGHT_L_MIN = 62.0       # mean L* above -> light
SEASON_DEEP_L_MAX = 42.0        # mean L* below -> deep
SEASON_BRIGHT_C_MIN = 45.0      # mean chroma above -> bright
SEASON_SOFT_C_MAX = 28.0        # mean chroma below -> soft/muted
SEASON_WARM_SHARE_MIN = 0.6     # warm share at/above -> warm
SEASON_COOL_SHARE_MAX = 0.4     # warm share at/below -> cool
# Normalisers used to decide which axis dominates (distance past the mid thresholds).
SEASON_L_SCALE = 20.0
SEASON_C_SCALE = 20.0
SEASON_TEMP_SCALE = 1.0
