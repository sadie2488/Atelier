# SCORER.md — outfit scoring rules (spec for task B2)

HUMAN-OWNED. The recommender implements these rules exactly; every number here lives in one config block in `backend/app/recommend/scorer.py`. The test expectations at the bottom were checked against a reference implementation of these exact rules on the contract fixtures.

`rule_score = 0.6 × hue + 0.2 × pattern + 0.2 × formality`, each component 0..1, rounded to 3 decimals.

## 1. Color roles

Each garment's role comes from its **dominant color** (`colors[0].lch` = L, C, h):

| Role | Rule | Examples in the fixtures |
| --- | --- | --- |
| **achromatic** | `is_neutral` is true (C < 12) | white tee, black jeans, grey hoodie, cream trousers |
| **everyday neutral** | not achromatic, C < 40, and one of: navy/denim (200 ≤ h ≤ 300, L < 60); beige/tan/camel/brown (50 ≤ h ≤ 95); olive (95 < h ≤ 135, L < 55) | blue jeans, denim jacket, beige chinos, brown boots, camel coat, olive overshirt, cargo pants |
| **accent** | everything else | red flannel, mustard sweater, pink knit, burgundy sneakers, green floral skirt |

## 2. Hue score (weight 0.6)

Only **accents** are compared; achromatic and everyday neutrals go with everything.

- No accents: **0.85** if the outfit has at least one everyday neutral, otherwise **0.80** (all black/white/grey is safe but plain).
- One accent: **0.90**.
- Two or more accents: the **lowest** pair score among all accent pairs, minus **0.15 for each accent beyond two**, clamped to 0..1.

Pair score from the hue difference d (degrees, 0..180, the short way round the wheel):

| d | Relationship | Pair score |
| --- | --- | --- |
| 0–30 | analogous / tonal | 1.00 |
| 31–60 | near-analogous | 0.60 |
| 61–104 | clash zone | 0.35 |
| 105–135 | triadic | 0.85 |
| 136–149 | near-complement | 0.50 |
| 150–180 | complementary | 0.95 |

## 3. Pattern score (weight 0.2)

Count garments whose `pattern` isn't `solid`: 0 or 1 → **1.0**; 2 or more → **0.3**.

## 4. Formality score (weight 0.2)

Spread = max formality − min formality in the outfit: 0 → **1.0**, 1 → **0.9**, 2 → **0.6**, 3 → **0.25**, 4 → **0.0**.

## 5. Ordering and ties

Sort by `rule_score` descending, then fewer catalog items (prefer what the user owns), then fewer items, then the sorted item ids. Ranks start at 1. Output is deterministic for the same closet and anchor.

## 6. Template reasons (fallback when the Gemini re-rank fails)

Pick the first line that applies and fill in garment `subcategory` names; at most 140 characters.

1. Two or more patterns: "Busy: the {a} and {b} patterns compete; kept as an option."
2. Formality spread ≥ 2: "Mixes dressy and casual: the {most formal} with the {least formal}."
3. Accents analogous (hue 1.0): "Tonal look: the {a} and {b} share a color family."
4. Accents complementary (hue ≥ 0.95): "Complementary colors: the {a} and {b} balance each other."
5. One accent: "The {accent} leads; the rest stays neutral."
6. Otherwise: "Neutral outfit that works with anything."

Append " You'd need to buy the {catalog item}." when `needs_purchase` isn't empty and the reason still fits in 140 characters.

## 7. Test expectations (verified)

Fixture garment `n` has id `"1" + 19 zeros + n as 4 hex digits` (e.g. 2 → `100000000000000000000002`). Numbers: 1 white tee, 2 red flannel, 3 breton, 4 mustard sweater, 5 grey hoodie, 6 black jeans, 7 blue jeans, 8 beige chinos, 9 green floral skirt, 10 black slip dress, 11 olive overshirt, 13 white sneakers, 14 brown boots, 16 olive cargo (catalog), 17 pink knit (catalog), 18 cream trousers (catalog), 19 burgundy sneakers (catalog).

**Must rank A above B** (reference scores ±0.01):

| Test | A | score | B | score |
| --- | --- | --- | --- | --- |
| Pattern clash | 2 + 6 + 13 | 0.92 | 2 + 9 + 13 | 0.69 |
| Pattern clash 2 | 3 + 7 + 13 | 0.89 | 3 + 9 + 13 | 0.72 |
| Accent clash | 4 + 6 + 13 | 0.86 | 4 + 6 + 19 | 0.74 |
| Hue clash | 4 + 7 + 14 | 0.92 | 4 + 9 + 14 | 0.61 |
| Complement beats clash | 17 + 9 + 14 | 0.97 | 4 + 9 + 14 | 0.61 |
| Formality spread | 10 + 14 | 0.89 | 10 + 13 | 0.73 |
| Formality spread 2 | 1 + 6 + 13 | 0.86 | 1 + 18 + 13 | 0.73 |
| Neutral base beats clash | 5 + 6 + 13 | 0.86 | 4 + 9 + 19 | 0.50 |

**Absolute bounds:**

| Outfit | Expected |
| --- | --- |
| 5 + 6 + 13 (all achromatic) | ≥ 0.80 |
| 4 + 8 + 14 (mustard, beige, brown: warm tonal) | ≥ 0.90 |
| 2 + 16 + 19 (red, olive, burgundy: tonal) | ≥ 0.95, and it contains 2 catalog items |
| 3 + 9 + 13 (two patterns) | ≤ 0.75 |

**Candidate generation** (TASKS.md B2): anchor 2 (flannel) never produces an outfit containing another top or the dress; anchor 10 (dress) never produces an outfit with a top or bottom; every outfit has exactly one pair of shoes.
