# Atelier — Resolved Decisions

PM-owned. Read-only to lane subagents. Frozen alongside `contract/FROZEN`.

**How lanes use this file.** When a value or behavior you need is not specified in your
lane context, look here. If it is not here either, **stop and ask the PM.** Do not choose a
default, do not infer one from surrounding code, do not proceed with a placeholder. Append
the question to `contract/OPEN_QUESTIONS.md` and report it in your task response.

---

## Contract amendments required before freeze

Apply these to the contract models, then re-run `python -m contract.check_contract` and
re-freeze. Each is needed by a lane and cannot be worked around.

### A1 — `garment_type` on the item model

`category` decides which swipe list an item appears in and how outfit assembly treats it.
`garment_type` decides which pose region vision segments. Without both, a dress
(`category: tops`) is segmented shoulder-to-hip and comes back cropped at the waist.

Both are **user-supplied at ingest** and required on analyze, save, and the item record.

```python
class Category(str, Enum):
    TOPS = "tops"
    BOTTOMS = "bottoms"
    JACKETS = "jackets"

class GarmentType(str, Enum):
    SHIRT = "shirt"
    DRESS = "dress"
    PANTS = "pants"
    SKIRT = "skirt"
    SHORTS = "shorts"
    JACKET = "jacket"
    COAT = "coat"
```

Valid pairings — enforce in a model validator so an invalid combination cannot be saved:

| category | permitted garment_type |
|---|---|
| `tops` | `shirt`, `dress` |
| `bottoms` | `pants`, `skirt`, `shorts` |
| `jackets` | `jacket`, `coat` |

### A2 — `outfit_id` and `strategy` on the outfit model

`outfit_id` is stable within a response. `strategy` is the generating strategy's name
(e.g. `neutral_anchor`) and is what the explanation is written from. Confirm both exist.

### A3 — An open `attributes` object on the item model

Optional, permissively shaped, empty for every item at launch. Enrichment (V7) populates it
later. Adding it now costs nothing and means the entire stretch goal lands with zero contract
churn and no frontend change.

### A4 — Render job fields

`render_id`, `status` (`pending` | `done` | `failed`), `local_url`, `generated_url`. See
`coordination/BACKEND_API.md` for the polling contract the frontend builds against.

---

## Vision lane

### Color

**V-C1 — All colors are numeric.** Every stored color is a numeric value. Names are derived
by lookup, never stored as the source of truth.

**V-C2 — Extraction algorithm.** K-means, k=5, in CIELAB, over masked (alpha > 0) pixels
only. Clusters sorted by pixel mass descending. Primary color is cluster 1's centroid.

**V-C3 — Secondary color.** Emitted when a later cluster holds ≥20% of masked pixels **and**
is ≥ΔE2000 20 from the primary. At most one secondary. If several qualify, take the largest
by pixel mass.

**V-C4 — Name assignment.** Nearest center by CIEDE2000 from `contract/colors.json`. Beyond
`max_assignment_delta_e` (25), the name is `unmapped`; the numeric value is still stored and
still scored.

**V-C5 — `is_neutral` is numeric, never a name lookup.** Computed from chroma per contract.
If the name table and the chroma computation disagree, **chroma wins.** `colors.json`
supplies `everyday_neutral` only.

**V-C6 — Retailer color agreement.** Resolve the retailer string through
`retail_aliases`, then compare `family` against the extracted primary's family. Bar: ≥16/20.
Strings resolving to `unmapped` are excluded from the denominator, not counted as failures.
This is a mask-quality signal, not a gate — a failure is reported, never blocking.
**Measurement (human decision, 2026-09-26):** fixture labels name the color the owner
registered — on striped or two-tone garments that is the accent, not the larger base. A hit is
the labelled family matching the extracted primary **or** secondary color.

**V-C7 — Denim caveat.** `denim` and `blue` sit close in Lab and will misassign at the
boundary. This is accepted. If agreement failures cluster on denim items, report to the PM
rather than retuning `colors.json` yourself.

### Segmentation

**V-S1 — Skin detection.** Use MediaPipe segmentation categories. **Do not use HSV or RGB
color thresholding for skin** — threshold methods fail on dark skin tones, producing
inflated purity scores on some models and shredded garments on others. Validate across a
deliberately skin-tone-diverse fixture set.

**V-S2 — Independent garment extent.** For the completeness check, derive extent from pose
landmarks plus the non-background region, computed **before** skin exclusion. It must not be
derived from the mask it is checking.

**V-S3 — One pass, three variants.** A single person-segmentation and pose run per image.
The three candidates differ only in post-processing (erosion/dilation radius, skin threshold
strictness). Tripling the segmentation pass will breach the latency budget.

**V-S4 — Record the tuned values.** Once candidate thresholds are tuned against the golden
references, write the final numeric values into `backend/vision/candidate_params.py` with a
comment naming the fixture run they were tuned on. Undocumented thresholds are irreproducible.

**V-S5 — Pose regions are selected by `garment_type`, not `category`.** A dress is filed under
`category: tops` for browsing and outfit assembly, but it needs the full-length region. Using
`category` here would clip every dress into a crop top.

- `garment_type: shirt` / `top` → shoulder-to-hip landmark span
- `garment_type: pants` / `skirt` / `shorts` → hip-to-ankle span
- `garment_type: jacket` / `coat` → shoulder-to-hip plus full arm span
- `garment_type: dress` → continuous shoulder-to-ankle span with **no waist seam**; do not
  union the top and bottom regions, as the join produces a visible discontinuity

`category` (tops | bottoms | jackets) governs which swipe list the item appears in and how
outfit assembly treats it. `garment_type` governs segmentation only. Both are user-supplied at
ingest.

**V-S6 — Multiple people in one image.** Take the largest person by mask area. Log the
occurrence to the rejection log with `event: "multi_person"`.

**V-S7 — Category/image mismatch.** Trust the user's category. If pose regions suggest a
different garment, proceed anyway and log `event: "category_mismatch"` with both values.
Never reject on this basis.

### Artifacts and identity

**V-A1 — Canvas and anchor come from the PM.** Defined in the P0.7 artifact spec.
**Halt rule: do not begin V3 until that spec file exists.** Do not invent a canvas.

**V-A2 — Identity.** Readable slug `<category>_<6 lowercase hex>`, e.g. `top_a3f9c2`,
`dress_7b1e04`. Allocated at **save**, never at analyze. Every reshoot attempt gets a fresh
slug; slugs are never reused.

**V-A3 — Temp handles.** Analyze writes its three cutouts under a temp handle. On save, the
chosen cutout is moved into the item's media path under its slug.

**V-A4 — Temp cleanup.** TTL sweep on server startup: delete any temp handle directory older
than one hour.

### Failure logging

**V-F1 — Location.** `media/_failures/rejections.jsonl`. Single file, all categories.
Append-only, one JSON object per line, opened in append mode. **Never read-modify-write** —
concurrent ingests will clobber each other.

**V-F2 — Written at reject time**, not at finalize. An abandoned session must still leave a
record.

**V-F3 — Entry fields.** `event`, `temp_handle`, `category`, `retailer_color`, `timestamp`,
and the full automated check results for **all three** candidates — not merely which failed.
A rejection where all three passed every check is the most valuable signal in the log.

**V-F4 — Events logged.** `reject_all` (user rejected all three), `exception` (analyze
raised), `multi_person`, `category_mismatch`.

**V-F5 — Backfill.** On eventual save, append the finalized slug to the prior entries for
that session. Appending a linking record is acceptable; rewriting earlier lines is not.

### Endpoints and flow

**V-E1 — Candidates.** Exactly three, always. No two within 3% alpha IoU — if the variants
collapse to near-identical masks, report to the PM rather than shipping three copies.

**V-E2 — Reject all three.** Nothing persists. No cutouts retained. The user reshoots and
ingest restarts from V1 with a fresh temp handle and, eventually, a fresh slug.

**V-E3 — Analyze persists nothing.** A test must assert the items collection is unchanged
after an analyze call.

**V-E4 — Media URLs are relative** (`/media/...`). Never absolute, never host-embedded.

**V-E5 — Input limits.** Max 12 MB. Accept JPEG, PNG, WebP. An input PNG that already
carries alpha has its alpha discarded and is composited onto white before processing.

### Quality bars

**V-Q1 — Purity.** Skin ≤1% of alpha area, and no contiguous skin region >0.3% of alpha
area. All four canvas corners fully transparent.

**V-Q2 — Completeness.** No alpha boundary following a straight line >15% of canvas width.
Mask bbox ≥90% of the V-S2 independent extent. Left/right alpha mass within 25% for tops and
bottoms. No interior holes >2% of alpha area.

**V-Q3 — Structural.** Alpha channel present and not fully opaque. Coverage ratio 8%–70%.
Largest connected component ÷ total alpha ≥0.90.

**V-Q4 — Acceptance.** One-time human pass over the 20-image fixture set selects the best
candidate per image; those become frozen golden references. Thereafter automated:
new output ≥0.85 IoU against the reference.

**V-Q5 — Golden reference regeneration.** Only the PM re-blesses references, and only after
a human pass. Record the date and reason in `contract/GOLDEN_LOG.md`. A lane subagent never
regenerates references to make its own output pass.

**V-Q6 — Latency.** Analyze p50 ≤5s, p95 ≤9s. Save ≤1s. Measured over 20 runs after one
discarded warmup run, so cold MediaPipe init is excluded.

### Enrichment (V7, severable)

**V-X1 — Post-save only.** Never inline in analyze. Structured as a standalone idempotent
`enrich(item) → attributes` callable both after save and as a batch pass over existing items.

**V-X2 — Model.** Gemini, pinned to an explicit version string in `config.py`. Never
`latest`.

**V-X3 — Provenance.** Every attribute carries its source: `retailer`, `user`, `model`, or
`user_correction`. Required from the first attribute written.

**V-X4 — Storage.** Into the contract's open `attributes` object. If the frozen contract
lacks one, this is a PM amendment **before** freeze, not a lane workaround.

**V-X5 — Originals retained.** The original uploaded image is preserved after save, so
future enrichment passes are a backfill rather than a re-ingest.

**V-X6 — Bar.** Sleeve attribute (long / short / sleeveless / straps) correct on ≥15/20.
Deterministic fallback on API failure. Never blocks V5.

### Environment

**V-N1 — MediaPipe requires Python 3.12.** No 3.14 wheels exist. Vision is the lane that
breaks if the local interpreter is wrong. PM verifies in P0.4.

---

## Styling lane

**Standing principle for this lane: ship a working product, tune later.** Where a detail is
undecided, prefer the option that keeps the endpoint returning valid outfits. Record the
choice in `contract/OPEN_QUESTIONS.md` rather than blocking on it.

### Scorer

**S-C1 — The scorer is pure.** No DB, no network, no file I/O inside scoring functions.
Same inputs always produce the same score. This is what makes the 12 expectations meaningful
and what lets this lane finish with the items collection empty.

**S-C2 — Operates on numeric color.** Hue angle is `atan2(b*, a*)`, chroma is
`sqrt(a*² + b*²)`, both from the stored Lab values. Family comes from `contract/colors.json`.
Never score from color names.

**S-C3 — Secondary color scores at reduced weight** relative to primary. The weight lives in
`weights.py`, not inline.

**S-C4 — Missing attributes are absent, never penalized.** Most items will carry no enrichment
attributes for a long time. An item without them must never rank below an otherwise identical
item that has them.

**S-C5 — The 12 expectations are the specification.** If the implementation disagrees, the
implementation is wrong. Never adjust an expectation to match output — report to the PM.

### Tunables

**S-T1 — Every tunable number lives in `backend/styling/weights.py`.** Strategy weights, hue
bands, chroma thresholds, L* spread minimums, diversity caps, secondary-color weight. No
numeric constant governing recommendation behavior appears anywhere else in the lane. This is
what makes later tuning an edit rather than a refactor.

### Outfit shapes

**S-O1 — One outfit shape.** `bottom + (top or dress) + optional jacket`. A dress lives in the
**tops** category and is treated as a top everywhere in this lane.

**S-O2 — A dress does not remove the bottom.** It layers over it. There is no special-case
exclusion logic anywhere in this lane.

**S-O3 — Jackets are a layer, not a slot.** Optional on every outfit.

### Strategies

**S-S1 — Recommendations come from named strategies**, each a generator plus a scorer. Each
outfit carries its strategy label, which is also what the explanation is written from.

**S-S2 — Ship order is a degradation ladder.** Cut from the bottom if time runs short;
rungs 1–2 alone are a working demo.

1. **Neutral anchor** — strict neutral + chromatic. Always eligible; guarantees non-empty results.
2. **Everyday-neutral base** — navy/denim/olive/camel/beige/brown base + chromatic partner.
3. **Analogous** (hue angle ≤40° across pieces) and **complementary** (150°–210°, at least one
   piece low-chroma).
4. **Monochrome + highlight** — one hue family, L* spread ≥20 so the look isn't flat, plus one
   optional accent piece.
5. **Sandwich** — outer and bottom share a family, top contrasts. **Jacket required:** the
   method needs three visible color slots, and top+bottom has two. Goes dormant in a closet
   with no outerwear; that is correct behavior, not a bug.

**S-S3 — A strategy stays silent when its eligibility is unmet.** It does not degrade into a
different strategy or emit low-confidence filler.

### Selection

**S-L1 — Return 5.** Max 2 outfits per strategy. Max 2 outfits sharing any one garment.
Jackets are exempt from the sharing cap — one good jacket would otherwise starve the list.

**S-L2 — Return fewer rather than padding.** A closet yielding 3 valid outfits returns 3.
Never fill slots with combinations the scorer rates poorly.

**S-L3 — Never empty when rung 1 is satisfiable.** If the closet contains a strict neutral and
a chromatic piece in compatible slots, results must be non-empty.

**S-L5 — Recommendations position, they do not filter.** The closet UI is plain browsing: the
user swipes tops and bottoms independently, in a stable default order, with no reordering by
score. "Generate outfit" is a separate action — it calls `/api/outfits` and the frontend moves
the top-ranked outfit's garments to position 0 of their respective lists. The user can swipe
away freely from there.

**S-L6 — No per-slot ranking endpoint.** Ranking a slot against a currently selected garment is
explicitly out of scope. The swipe does not consult the scorer.

**S-L7 — Swipe order must be stable** across calls, so positioning at index 0 is meaningful and
the list does not reshuffle under the user. Default order is item creation, newest first.

**S-L8 — Dresses swipe in the tops list.** Resolved. A dress appears among tops, pairs with a
bottom like any top, and needs no separate slot or mode.

### Explanations

**S-E1 — Gemini explains; it never re-ranks.** Ranking stays deterministic and fast.
Re-ranking is explicitly out of scope.

**S-E2 — Explanations are written from the strategy label and the outfit's colors.**

**S-E3 — Static fallback per strategy**, fired on API error or latency. The fallback path is
exercised by a test, not merely written.

**S-E4 — An explanation never blocks or delays a response.** Outfits are correct and ranked
before any explanation is requested.

**S-E5 — Model pinned** to an explicit version string in `config.py`. Never `latest`.

### Out of scope

**S-X1 — Thumbs/feedback weighting is future work.** Not built now. `outfit_id` and `strategy`
(see contract amendment A2) are the only hooks retained.

**S-X2 — LLM re-ranking: out.** See S-E1.

**S-X3 — Learning from user reference images: out.**

### Independence

**S-I1 — No imports from `backend.vision` or `backend.avatar`.** This lane consumes item
records shaped by the contract, not another lane's code.

**S-I2 — Build and test entirely against fixtures.** The items collection may be empty for
this lane's entire duration. Never wait on the vision lane.

### Dependencies owed to this lane

- **Human:** re-verify all 12 scorer expectations against the current item shape (primary +
  secondary color, everyday-neutral flag) and a calibrated `colors.json`. Until this is done,
  S1's bar is not meaningful.
- **PM:** confirm the contract's outfit model carries `outfit_id` and `strategy` — see
  contract amendment A2 above.

---

## Avatar lane

**Lane status: deferred.** Vision and Styling start first. This section is settled so the lane
can begin without re-litigating decisions.

**Standing principle: the local path must always work.** Every enhancement is severable. A
render that fails must degrade to something visible, never to an error.

### Capture

**A-P1 — Browser camera, no native app.** `getUserMedia` in the existing frontend. Requires
HTTPS (Vercel provides it). iOS Safari grants camera access only on a direct user gesture — a
button tap, never an automatic call on page load.

**A-P2 — Pose outline overlay.** The capture view shows an outline the user positions
themselves inside. Standing, front-facing, arms slightly away from the body.

**A-P3 — Pose validated before acceptance.** MediaPipe Pose landmarks checked against the
outline tolerance. Reject with a specific, actionable reason ("move your arms away from your
body"), never a generic failure. A bad base scan ruins every outfit rendered on it, so
rejecting and re-prompting is correct.

### Body

**A-B1 — The wireframe is the placement rig.** MediaPipe Pose gives 33 landmarks; shoulder
line, torso span, hip line, and leg length are derived from them. This is how garments are
positioned and scaled. It is not optional — placement has no fixed template to fall back on
once the body varies per user.

**A-B2 — Anchors are normalized to landmarks, never absolute pixels.** This propagates to the
P0.7 artifact spec and therefore to the vision lane's V3. Garment cutouts are placed relative
to detected shoulder, hip, and ankle positions.

**A-B3 — The visible avatar is line art drawn from the same landmarks.** Clean strokes, no
photographic body. Deterministic, fast, and unambiguously stylized — which is what makes flat
garment cutouts read as intentional rather than broken.

**A-B4 — Light fill inside the wireframe outline**, in the sampled skin tone. A wireframe is
open; without a fill, background shows through at the neckline and between the legs.

**A-B5 — Skin tone sampled from exposed regions**, falling back to the face region when the
user is scanned in long sleeves and pants. The face is always available.
*Method (2026-09-26):* skin pixels come from the MediaPipe ImageSegmenter's skin categories
(the Windows crash is only in PoseLandmarker's own mask output); the tone is their median in
Lab, ignoring near-black and clipped pixels. Scans are EXIF-corrected and downscaled to a
1600 px long side first; the face is detected in a crop around the head landmarks.

**A-B6 — The real face is composited at the head.** Cropped via MediaPipe face detection,
background removed, scaled to the wireframe's neck anchor.

**A-B7 — No drawn art assets required.** No template body, no component library. The lane has
no dependency on the team's drawing time.

**A-B8 — Fallback ladder.** Segmentation fails → wireframe from landmarks alone. Skin sampling
fails → face-region tone. Landmarks fail → reject the scan and re-prompt (A-P3). There is no
rung below landmarks; a scan without them is not usable.

### Rendering

**A-R1 — Render on click only.** Nothing composites until the user presses "see outfit." No
background pre-rendering, no speculative work. This is what keeps try-on cost and latency
bounded.

**A-R2 — Two-stage response.** On click, return the local composite **immediately** — it is
instant and always available. Then fire the try-on render and swap the image in when it lands.
A button that does nothing for twelve seconds reads as broken regardless of the eventual
quality. If the network fails, the user never learns anything was missing.

**A-R3 — Cache by `(user_id, top_id, bottom_id, jacket_id)`.** Re-viewing a combination costs
nothing.

**A-R4 — Draw order (local composite): bottom → top-or-dress → jacket.** Jackets are the only
piece overlapping another garment and therefore the likeliest source of visible misalignment.

**A-R5 — A dress is a top.** It layers over the bottom. No exclusion logic.

**A-R6 — The local composite is the guaranteed path; generated try-on is an enhancement
layer.** Never build anything that only works when generation is available.

**A-R7 — Gemini image generation is the primary try-on path.** One call takes the person photo
plus garment references and returns the full look. This is preferred over a dedicated VTON
chain because: one call instead of three (a VTON chain is ~10s per garment), it follows an
instruction rather than a region mask so a dress layers over a bottom correctly, it tolerates
stylized input, and it reuses the existing API key and sponsor track with no new vendor,
billing, or license review. Its weakness is garment fidelity — texture, print, and logo detail
drift. Acceptable here; it would not be for a shopping tool.

**A-R8 — Model version pinned** in `config.py`. Never `latest`.

**A-R9 — The generation prompt is a versioned artifact.** It lives in
`backend/avatar/prompt.py` with the pinned model version beside it, plus a five-pair eval set
re-run whenever the prompt changes. For a generative approach, prompt quality determines output
quality more than any other code in this lane. Prompt explicitly for face and body preservation
— identity drift is the characteristic failure of this method.

**A-R10 — Verify generated output before swapping it in.** Sample the rendered garment region
and compare ΔE2000 against the item's stored Lab color from the vision lane. This reuses
machinery that already exists, has real ground truth, and catches the most common failure
(a garment coming back the wrong color). Optionally also compare face landmark geometry between
input and output. On verification failure, keep the local composite.

**A-R11 — VTON is an OPTIONAL third rung, not a checker.** A VTON model composites garments; it
cannot judge another model's output. The ladder is: Gemini → verify → (optional) VTON chain →
local composite. **Only the local composite rung is required.** Ship verify-then-keep-local
first; add the VTON rung only if time clearly allows, since two generation paths is substantial
surface for one demo.

**A-R12 — Fallback rungs run in the background, never in the request.** Worst case is Gemini
plus verification plus a VTON chain — 40s or more. The local composite is already on screen
(A-R2), so a failed ladder simply means no swap ever happens. Nobody waits.

**A-R13 — Stylize after generation, not before.** Both the plain avatar and the dressed avatar
pass through the same local filter (XDoG edge extraction, or bilateral filter plus adaptive
threshold, with skin-tone fill beneath). Plain avatar = `stylize(photo)`; dressed avatar =
`stylize(generated)`. Same subject, same filter, so they read as the same character. Cheap,
local, deterministic, no GPU. Severable — unstyled output is acceptable.

**A-R14 — The wireframe is the loading state.** On click, render the user's wireframe
immediately while generation runs, then swap in the result. More interesting than a spinner and
it is already being built.

**A-R15 — Quota discipline.** Cache every render by garment combination. Back off on 429s
rather than retrying hard. Quota exhaustion degrades to the local composite, never to an error.
Do not load-test against production quota the day before the demo.

**A-R16 — Latency.** Local composite ≤1.5s cold, ≤200ms cached. Generation is best-effort with
no bar; it never blocks a response.

**A-R17 — Media URLs relative** (`/media/...`). `check_media.py` passes before any task is
called done.

**A-R18 — Consent.** Face photos are uploaded to a third-party API. The UI states this before
capture.

### Tasks

| Task | Done when |
|---|---|
| **A1** Capture + pose validation | Outline renders; valid poses accepted, invalid rejected with specific reason |
| **A2** Wireframe rig | 33 landmarks → shoulder/torso/hip/leg geometry on all fixture scans |
| **A3** Avatar assembly | Line art + skin fill + composited face; deterministic across runs |
| **A4** Placement | Garments scale and position to the rig; correct at min and max body proportions |
| **A5** Local compositing | Draw order correct; dress layers over bottom; nothing clipped |
| **A6** Render endpoint | Two-stage response; wireframe loading state; cache hits ≤200ms; media relative |
| **A7** Gemini generation + verification | Prompt versioned with eval set; ΔE verification gates the swap; failure leaves local composite in place |
| **A8** Backup avatar | Pre-scanned avatar + seeded closet reachable in one action on the **deployed** URL; renders pre-cached for the demo combinations |
| **A9** Robustness | Missing cutout, missing face, failed segmentation, quota exhaustion — no unhandled exception |
| **A10** *(optional)* Stylization | Same filter applied to plain and dressed avatars |
| **A11** *(optional)* VTON rung | Background-only; never on the request path |

**Lane done when:** A1–A6, A8, A9 hold, `test_avatar.py` green, zero writes outside scope.
**A7 is severable** (local composite alone is a working demo). **A10 and A11 are optional.**
