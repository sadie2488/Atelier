# Atelier — Backend PM Agent Task List

The PM agent is the **main Claude Code session**. It owns the shared layer, dispatches the
three lane subagents in `.claude/agents/`, and is the only actor that runs git.

---

## PRIORITY: a working product

**A deployed, working, end-to-end demo beats a half-built impressive one. Always.**

This governs every decision the PM makes. When a lane is behind, cut scope rather than
extending the timeline. When a feature is risky, ship the fallback first and layer the
feature on top. When two options exist and one is simpler, take the simpler one and revisit
only if time remains.

Features are added **after** frontend and backend are deployed and working together — never
before. The build order is: working chain → working demo → features. Anything that inverts
that order is wrong, however appealing.

The PM is expected to **adapt**. The phases below are a plan, not a schedule. If a lane
finishes early, pull optional work forward. If a lane is stuck, cut its optional tasks and
redirect. Do not follow this document off a cliff.

---

## Standing rules

1. **The PM never writes lane code.** Only PM-owned files (below). Lane work is dispatched.
2. **The PM runs all git.** Subagents may not run any git command. One working tree, one
   committer. Subagents share the tree, so disjoint file ownership is what prevents collisions.
3. **Set `ATELIER_LANE` when dispatching.** The scope guard fails open without it, making all
   lane rules advisory. Verify enforcement before the first real dispatch: have a lane attempt
   to write `backend/main.py` and confirm it is blocked.
4. **Push gate to `main`** — all four, no exceptions, because `main` auto-deploys:
   - `python -m contract.check_contract` exits 0
   - `pytest backend/tests` exits 0
   - server starts locally and `/api/health` returns `{"status":"ok","db":"ok"}`
   - no route returns 501 that this commit was meant to implement
   - `python tools/check_docs.py` exits 0 — the docs must not contradict each other
5. **Drain `contract/OPEN_QUESTIONS.md` every dispatch cycle.** Lanes append blocked questions
   there. An undrained queue means a stalled lane.
6. **Cross-reference the two coordination docs every dispatch cycle**, before dispatching:
   - `coordination/BACKEND_API.md` — **the PM is its only writer.** Update it the moment an
     endpoint, shape, or behavior changes, and push immediately. The frontend builds against
     it; a stale version costs rework on both sides.
   - `coordination/FRONTEND_REQUESTS.md` — **read-only to the PM.** The frontend appends
     `BLOCKED`, `MISMATCH`, `REQUEST`, `QUESTION`, and `FYI` entries. Answer by editing
     `BACKEND_API.md` and filling in the Status and Resolution columns; never rewrite the
     frontend's entries. Handle `BLOCKED` first — a blocked frontend that the backend does not
     know about is the most expensive state in this project.

   `git pull` before reading either. They live in the repo and only propagate on push.
7. **Flag scope overlap to the user; do not resolve it silently.** If a frontend request would
   duplicate backend logic, or a lane task would implement something the frontend already owns,
   **stop and tell the user** which two pieces of work collide and which side you think should
   own it. Duplicated logic diverges, and the divergence surfaces at integration.

   **Prevent it by delegating cleanly:** one owner per capability, stated in the scope boundary
   at the end of `FRONTEND_REQUESTS.md`. Color logic, scoring, and garment placement are
   backend, always. Capture, list rendering, polling, and all UI state are frontend, always. If
   a task does not obviously belong to one side, that is the signal to raise it rather than to
   pick.
8. **Model policy:** PM on Opus for Phase 0 and integration planning; subagents on Sonnet.
9. **`/clear` between dispatches.**

## PM-owned files

```
contract/                      frozen: contract, DECISIONS.md, colors.json
backend/main.py                router registration
backend/db.py, config.py       shared layer
requirements.txt               all deps, pre-installed
.claude/agents/*.md            subagent definitions
.claude/hooks/scope_guard.py   scope enforcement
backend/tests/conftest.py      shared fixtures
```

Scope-guard exceptions required: lanes may append to `contract/OPEN_QUESTIONS.md`; vision may
write `media/_failures/` and `backend/vision/candidate_params.py`.

## Lane ownership

| Lane | Owns | Endpoints |
|---|---|---|
| `vision` | `backend/vision/**`, `backend/routes/items.py` | `/api/items/*` |
| `styling` | `backend/styling/**`, `backend/routes/outfits.py` | `/api/outfits/*` |
| `avatar` | `backend/avatar/**`, `backend/routes/avatar.py` | `/api/avatar/*`, `/media/` writes |

Each lane also owns `backend/tests/test_<lane>.py`.

---

## THE MINIMUM DEMO

Everything above this line is optional. Protect this and nothing else.

> A few garments are already ingested. The user opens the app, swipes tops and bottoms,
> taps **generate outfit**, and sees a recommended combination rendered on their avatar.
> One garment is ingested live to prove the pipeline works.

Backend parts required:
- Ingest → cutout → color extraction → saved item (V1–V5)
- Neutral-anchor pairing only (S1, S2, strategy rung 1)
- Ranked outfit endpoint returning garment ids (S4, S6)
- Local composite render on click (A1–A6)
- Deployed and working end to end

**That is the product.** Strategies 2–5, Gemini generation, verification, stylization,
enrichment, and VTON are all upside.

---

## PRE-COMMITTED CUT LIST

Decided now, while calm. The PM applies these without re-litigating. Sunk cost is the enemy
in the last third; this list is the defense.

| Checkpoint | If this is not true | Cut |
|---|---|---|
| **Hour 6** | Walking skeleton not deployed and working | Stop all lane work; everyone on the skeleton |
| **Hour 12** | Gemini generation not producing usable output on a real fixture | Cut A7 entirely; local composite is the render |
| **Hour 12** | Vision segmentation not passing purity + completeness | Drop to background-removal-only; keep color extraction |
| **Hour 18** | Strategy rungs 1–2 not working | Cut rungs 3–5 permanently |
| **Hour 20** | Not integrated end to end | Cut every optional task in every lane; integration only |
| **Hour 24** | — | Feature freeze. Only bug fixes, deploy checks, and demo rehearsal |
| **Any time** | A7 verification is flaky | Cut verification; keep local composite as the swap gate |
| **Any time** | Considering the VTON rung (A11) | Default is **do not build it** |

---

## Phase 0 — PM setup (blocking)

Everything that could collide is written once, here.

- **P0.1** Contract frozen; `check_contract` exits 0. Confirm it carries `outfit_id`,
  `strategy`, and an open `attributes` object. Missing → amend now, before freeze.
- **P0.2** Shared layer: `config.py`, `db.py`.
- **P0.3** Lane skeletons with contract-shaped 501 stubs; all routers registered under `/api`
  (`/media` stays top level). **After this, `main.py` is never edited again** — this is what
  keeps three concurrent agents from colliding.
- **P0.4** Pre-install all deps in one write. **Verify MediaPipe on `py -3.12`** — no 3.14
  wheels exist, and vision is the lane that breaks.
- **P0.5** Write `.claude/agents/*.md` and lane `CLAUDE.md` files. Install the scope guard.
  **Test that it blocks.**
- **P0.6** `conftest.py` exposing fixtures; create empty `OPEN_QUESTIONS.md` and `GOLDEN_LOG.md`.
- **P0.7** **Artifact spec.** Canvas, alpha, and **landmark-normalized anchors** (not pixels —
  the body scales per user). Vision's V3 halts without this.
- **P0.8** Calibrate `contract/colors.json` Lab centers against the fixture set. The written
  values are starting points, not measurements. Watch beige/tan/camel and denim/navy/blue.
- **P0.9** **Publish `coordination/BACKEND_API.md`** and create an empty
  `coordination/FRONTEND_REQUESTS.md`. Both settled decisions are already recorded there:
  **polling** for the two-stage render swap (`POST /api/render` → poll
  `GET /api/render/{id}`; the render id doubles as the cache key, stored in Mongo so it
  survives a restart), and **multipart** for uploads with no server-side cap but client-side
  downscaling to ~1080px. Confirm the frontend has pulled and read it before dispatch.

> **Exit:** server starts; `/api/health` ok; all routes return 501; scope guard demonstrably
> blocks an out-of-scope write; committed, pushed, both deploys green.

---

## Phase 0.5 — Walking skeleton (PM, before any lane dispatch)

**Do not skip this.** Three lanes building in parallel against fixtures and first meeting in
Phase 2 is how you discover at hour 30 that the pieces do not fit.

Build the thinnest possible end-to-end path: one hardcoded garment, one hardcoded outfit, one
local composite render, visible in the deployed frontend. Ugly is fine. Hardcoded is fine.

> **Exit:** a human can open the deployed URL and see a garment rendered on an avatar. The
> lanes now fill in a skeleton that already works instead of building toward an unproven join.

---

## Phase 1 — Parallel lane dispatch

Dispatch all three. Shared working tree, disjoint files, so they run concurrently. **No lane
depends on another's output** — each builds against the frozen contract and fixtures.

Task lists and exit criteria: `contract/DECISIONS.md`.

- **vision** — V1 intake → V2 isolation (3 candidates) → V3 normalization → V4 color →
  V5 endpoints → V6 robustness. *V7 enrichment is severable.*
- **styling** — S1 pair scorer → S2 outfit shapes → S3 strategies (**rungs 1–2 first; 3–5 are
  the cut line**) → S4 selection → S6 endpoint. *S5 explanations severable; fallback is not.*
- **avatar** — A1 capture → A2 rig → A3 assembly → A4 placement → A5 local composite →
  A6 endpoint → A8 backup avatar → A9 robustness. *A7 generation severable; A10, A11 optional.*

**PM during Phase 1:** poll lanes, drain `OPEN_QUESTIONS.md`, install requested deps, commit
each lane as it clears exit criteria, apply the cut list at each checkpoint.

**Spike, run this first, before Phase 1 is far along:** one user photo, one retail garment, one
Gemini generation call. Thirty minutes. The entire avatar render approach rests on output
quality nobody has seen yet. If identity drift is severe or garments come back unrecognizable,
cut A7 at hour 12 as planned — but know it early.

---

## Phase 2 — Integration

- **I1** Real end to end on the **deployed** URL: ingest → item in Mongo → outfits → render.
- **I2** Fix mismatches by **re-dispatching the owning lane**, never by patching lane code.
- **I3** Latency pass. Confirm fallbacks fire cleanly when APIs are slow.
- **I4** Frontend join: confirm live responses match what the frontend built against.

---

## Phase 3 — Live demo readiness

The demo is **live**. There is no canned alternative — so the live path must be robust.

- **D1** Rehearse the exact demo path **twice on the deployed URL**, clean browser, not
  localhost. Most failures live in the gap between local and deployed.
- **D2** Tether a phone. Test the full flow on cellular. Keep the hotspot on during judging.
- **D3** Warm everything a minute before presenting — one full cycle. Cold MediaPipe init,
  cold container, and cold model load all hit whatever runs first.
- **D4** Pre-ingest a closet. Demo opens populated; ingest **one** item live to prove the
  pipeline. Same story, a fraction of the exposure.
- **D5** Confirm every failure has a visible degraded state, not an error. No hanging spinners,
  no blank states, no stack traces. A judge who never learns something failed saw a working demo.
- **D6** Verify the backup avatar (A8) works on deployed, on cellular, with real keys, and is
  reachable in one action. **It is a backup, not the plan** — rehearse live capture.
- **D7** Keep a browser tab on the deployed health endpoint. Tells you instantly whether a
  failure is yours or the venue's.
- **D8** Decide the recovery move in advance: refresh, skip, or narrate.
- **D9** Draft sponsor submissions at ~hour 20, while the build is fresh. Four tracks, four
  forms. Ensure someone can speak to the MongoDB and DigitalOcean usage specifically.
- **D10** Surface the invisible work. Score breakdown on an outfit card, extracted color swatch
  beside the retailer's name. The scorer, Lab extraction, and segmentation are the substantial
  engineering and a judge sees none of it in a rendered image. Near-zero cost, high payoff.

---

## Phase 4 — Features, only after deployed and working

Pull forward only once Phases 2 and 3 hold, in this order:

1. Strategy rungs 3–5 (analogous, complementary, monochrome, sandwich)
2. Gemini explanations (S5)
3. Gemini generation + ΔE verification (A7)
4. Stylization filter (A10)
5. Enrichment / sleeve attributes (V7)
6. VTON rung (A11) — **default is not to build this**

---

## Human prerequisites — start these immediately

These block lane verification and none are agent work. **Begin tonight.**

- 20-image retail fixture set. Template and instructions are already at
  `fixtures/MANIFEST.csv` and `fixtures/images/README.md` — drop images in and fill the
  columns. Split by `garment_type`: 6 shirt / 5 dress / 5 bottoms / 4 outerwear. Note a
  dress is `category: tops`, `garment_type: dress`. Retail images must be **neutral pose**:
  front-facing, arms down. Vary skin tone deliberately across the set.
- One-time golden-reference pass: pick the best candidate per fixture; those become frozen
  references at ≥0.85 IoU.
- Re-verify the 12 scorer expectations against the current item shape and calibrated
  `colors.json`.
- Pre-scanned avatar for A8, tested on deployed.
- Plan sleep. Staggered naps beat both people degrading at once — and the last four hours,
  when you integrate and demo, are the ones where sharpness matters.

---

## Initial dispatch template

The PM hands each lane its context explicitly. Do not assume a subagent inherits it.

```
Set ATELIER_LANE=<lane> in the environment before dispatching.
Without it the scope guard fails open and every lane rule becomes advisory.

Lane: <vision|styling|avatar>
Task: <first task id, e.g. V1>

Your context, in this order:
  1. .claude/agents/<lane>.md      your rules, scope, and tools
  2. backend/<lane>/CLAUDE.md      why the lane works the way it does
  3. contract/DECISIONS.md         every resolved value (your section only)
  4. ARCHITECTURE.md               how your lane fits the whole
  (avatar only) coordination/BACKEND_API.md — the render polling contract

Do not read the other lanes' context. You do not need it and it costs you nothing but
tokens and confusion.

Priority: a working product. Simpler beats better. Severable tasks are severable.

Exit criteria: <from DECISIONS.md>
When a needed value is not in your context or DECISIONS.md, STOP. Append to
contract/OPEN_QUESTIONS.md and report it. Never guess.
```

## Re-dispatch template

```
Lane: <vision|styling|avatar>
Task: <task id>
Failing: <exact test name or endpoint + observed vs contract-expected>
Scope: you may edit only <lane paths>. Do not run git. Do not edit requirements.txt.
Exit: <the specific criterion to satisfy>
```
