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

# Either piece is a strict neutral (chroma < NEUTRAL_CHROMA_MAX, contract V-C5): neutrals
# pair with everything, so this is a high, flat score regardless of the partner's hue.
NEUTRAL_PAIR_SCORE = 0.90

# Same color family (contract/colors.json), different lightness: a monochrome-leaning pair.
# Score rises toward MONOCHROME_BASE + MONOCHROME_L_BONUS as the L* spread grows, capped at
# MONOCHROME_L_SPREAD_TARGET (S-S2 rung 4 uses the same "L* spread >= 20" idea).
MONOCHROME_BASE = 0.75
MONOCHROME_L_BONUS = 0.20
MONOCHROME_L_SPREAD_TARGET = 20.0

# Analogous: hue angle <= 40 degrees apart (S-S2 rung 3). Score falls off mildly with angle.
HUE_ANALOGOUS_MAX_DEG = 40.0
ANALOGOUS_BASE_SCORE = 0.80
ANALOGOUS_HUE_PENALTY = 0.30

# Complementary: hue angle 150-210 degrees apart, at least one piece low-chroma (S-S2 rung 3).
HUE_COMPLEMENTARY_MIN_DEG = 150.0
HUE_COMPLEMENTARY_MAX_DEG = 210.0
COMPLEMENTARY_LOW_CHROMA_MAX = 20.0
COMPLEMENTARY_SCORE = 0.85
COMPLEMENTARY_HIGH_CHROMA_PENALTY = 0.6  # multiplier when neither piece is low-chroma

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

# ---- explanations (S-E4): the whole batch of Gemini explanations for one
# POST /api/outfits/generate response must return within this fixed wall-clock budget,
# regardless of how many outfits are being explained or how slow Gemini is. Any explanation
# not finished by the deadline falls back to its static per-strategy text instead of blocking
# the response.
EXPLAIN_BUDGET_SECONDS = 2.5
