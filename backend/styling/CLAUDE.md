# Styling lane — domain notes

Why the lane works the way it does. Rules and scope are in `.claude/agents/styling.md`;
every resolved value is in the Styling section of `contract/DECISIONS.md`.

## The job
Given the closet (items shaped by `contract/schemas.py`), return up to 5 ranked outfits from
`POST /api/outfits/generate`. Each outfit is a bottom + a tops-category item (a shirt or a
dress) + an optional jacket, with an `outfit_id`, a `strategy` label, and an explanation.

## Shape of the code
- `scorer.py` — pure pairwise color-harmony scoring from stored Lab (hue = atan2(b*, a*),
  chroma = sqrt(a*² + b*²)); family from `contract/colors.json`. No DB, network or file I/O.
- `weights.py` — every tunable number. Nothing numeric lives anywhere else.
- `strategies.py` — named generators, in ship order: neutral_anchor, everyday_neutral_base
  (the demo); analogous/complementary, monochrome_highlight, sandwich (upside, cut first).
  A strategy whose eligibility is unmet stays silent.
- `select.py` — max 5, max 2 per strategy, max 2 sharing a garment (jackets exempt); fewer
  rather than padding; never empty when neutral_anchor is satisfiable.
- `explain.py` — Gemini writes the explanation from the strategy label and colors; a static
  per-strategy fallback fires on error or timeout and is covered by a test. Never re-ranks.
- Route in `backend/routes/outfits.py` reads items via `backend.db.get_db()["items"]`.

## Testing
Build and test entirely against `contract/fixtures/items.json` — the items collection may be
empty for this whole lane. The 12 scorer expectations are the specification and live in
`backend/styling/expectations.json`, which the human provides. Until it exists, test the
rules above; when it lands, `test_styling.py` must run every expectation.
