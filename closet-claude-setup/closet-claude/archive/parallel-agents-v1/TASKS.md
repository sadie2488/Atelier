# TASKS.md — planned tasks

Source list of planned work. The architect never hands these out directly: it turns each one into an announcement with `python3 .claude/scripts/announce.py --from-tasks <ID>`, adds context, and dispatches the expert. New work gets lane-prefixed IDs (`TA01`… on laptop A, `TB01`… on laptop B) from `.claude/tasks/_templates/ANNOUNCEMENT.md`.

- Each task belongs to one lane and one expert; the lane is the laptop that announces it.
- "May edit" is an allowlist inside that expert's scope (`.claude/scopes.json`).
- **Check** is the exact command the expert runs and the architect re-runs. `announce.py` fills in `{WT}` (worktree path), `{PY}` (shared venv python), `{PORT}` (a free port), and `{ID}`.
- "Depends on" entries must be merged into `main` (their REPLY.md is in `main`) before the task can be announced. `contract` means `contract/FROZEN` exists in `main`.
- Tasks marked HUMAN are listed for order only; agents never do them.

Old IDs (before tasks were merged): A1+A2+A3 → A1, A4 → A2, A5 → A3, A6 → A4, A7 → A5, A8+A9 → A6, B7a → A7, B0 → B1, B1+B2 → B2, B3 → B3, B4 → B4, B5 → B5, B6+B7b → B6.

---

## Human setup (both laptops)

### H0 · HUMAN: setup
- Follow Stage 1 in `WORKFLOW.md`: shared GitHub repo, `.claude/lane.local`, shared venv, Playwright browsers, hooks approved.
- Lane A human reviews the contract draft (`contract/CONTRACT_NOTES.md`, about 10 minutes), runs `python3 -m contract.check_contract`, then creates `contract/FROZEN`. Push.
- Lane B human: the Next.js rewrite proxies both `/api/*` and `/media/*` to the backend.

---

## Scaffolding

### S1 · Backend scaffold
- **Lane:** A · **Expert:** backend-engineer · **Depends on:** contract
- **May edit:** `backend/app/__init__.py`, `backend/app/routes_scaffold.py`, `backend/tests/test_scaffold.py`, `backend/tests/conftest.py`, `backend/pytest.ini`, `backend/requirements.txt`, `backend/Dockerfile`, `backend/.env.example`
- **Approved dependencies:** fastapi, uvicorn, pydantic, pytest, httpx (pinned)
- **Goal:** a FastAPI app exposing every entry in `contract.schemas.ENDPOINTS`, each returning its `contract/fixtures/api/*.response.json`, and serving `/media/*` from a media folder. `backend/pytest.ini` sets `pythonpath = ..` so `from contract.schemas import ...` works; the Dockerfile copies `contract/` next to `backend/` and bakes model weights into the image.
- **Explicitly allowed:** returning fixtures (this is the scaffold, not a stub of a feature under test).
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/test_scaffold.py -q --tb=short`
- **Done when:** the check passes and every response validates against its Pydantic model.

### S2 · Frontend scaffold
- **Lane:** B · **Expert:** frontend-engineer · **Depends on:** contract
- **May edit:** `frontend/lib/**`, `frontend/app/layout.*`, `frontend/app/page.*`, `frontend/app/fixtures/**`, `frontend/public/**`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/next-env.d.ts`, `frontend/.env.example`
- **Approved dependencies:** next, react, react-dom, typescript, @playwright/test, json-schema-to-typescript (pinned)
- **Goal:** Next.js App Router app with a typed API client whose types are generated from `contract/schema.json` (an npm script, not hand-written) and a fixture mode (`NEXT_PUBLIC_API_MODE=fixtures`), so screens can be built before the backend is live. A `/fixtures` page lists fixture garments.
- **Check:** `bash .claude/scripts/ui_check.sh {ID} {PORT} /fixtures`
- **Done when:** the build passes and the screenshot shows the fixture garments.

---

## Lane A · Scan & avatar

### A1 · Flat-lay pipeline
- **Lane:** A · **Expert:** cv-pipeline-engineer · **Depends on:** S1
- **May edit:** `backend/app/pipeline/__init__.py`, `backend/app/pipeline/preprocess.py`, `backend/app/pipeline/bgremove.py`, `backend/app/pipeline/color.py`, `backend/tests/pipeline/test_preprocess.py`, `backend/tests/pipeline/test_bgremove.py`, `backend/tests/pipeline/test_color.py`, `backend/scripts/golden_flatlay.py`
- **Approved dependencies:** opencv-python-headless, rembg, scikit-learn, scikit-image (pinned)
- **Goal:** image → EXIF-corrected, resized (long side 1024 px), gray-world white-balanced; flat-lay → transparent cutout + bbox (error if the mask covers under 3% or over 95%); cutout → 2–4 colors `{lab, lch, hex, weight}` from opaque pixels only, merged below ΔE2000 8, dropped under 10% weight, with `is_neutral`.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/pipeline -q --tb=short && {PY} scripts/golden_flatlay.py`
- **Done when:** tests pass, dominant color family matches `/golden/labels.csv` on at least 80% of items, and cutouts are saved to `.claude/tasks/{ID}/evidence/` for review.

### A2 · Garment classification
- **Lane:** A · **Expert:** cv-pipeline-engineer · **Depends on:** A1, B1
- **May edit:** `backend/app/pipeline/classify.py`, `backend/tests/pipeline/test_classify.py`
- **Goal:** cutout → category, subcategory, pattern, formality, style_tags through the Gemini wrapper's `classify`. One retry on schema failure, then status `needs_review`.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/pipeline/test_classify.py -q --tb=short`
- **Done when:** tests pass on recorded responses; one live golden-set run (human, with a real key) scores at least 90% on category.

### A3 · Seed and catalog loader
- **Lane:** A · **Expert:** cv-pipeline-engineer · **Depends on:** A2
- **May edit:** `backend/scripts/load_seed.py`, `backend/tests/pipeline/test_load_seed.py`
- **Goal:** batch-ingest a folder through the real pipeline with `ownership` = owned or catalog; idempotent; prints a summary table.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/pipeline/test_load_seed.py -q --tb=short`
- **Done when:** loading the same folder twice leaves exactly one record per image.

### A4 · Clothing segmentation
- **Lane:** A · **Expert:** cv-pipeline-engineer · **Depends on:** A1
- **May edit:** `backend/app/pipeline/segment.py`, `backend/tests/pipeline/test_segment.py`
- **Approved dependencies:** transformers, torch CPU (pinned); model id given in the announcement
- **Goal:** waist-up capture → one region per garment class, skin and hair excluded, small regions dropped; each region as a cutout PNG + bbox + class. Weights loaded once at startup.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/pipeline/test_segment.py -q --tb=short`
- **Done when:** every labeled top in the golden scans is returned as a region; timing per image on CPU is in the REPLY.

### A5 · Avatar head
- **Lane:** A · **Expert:** cv-pipeline-engineer · **Depends on:** B1
- **May edit:** `backend/app/avatar/**`, `backend/tests/avatar/**`
- **Goal:** face capture → drawn head PNG through the wrapper's `generate_head` with the style reference in `/contract/`. On failure or timeout, the photo fallback (face cut out) with `head_source: "photo_fallback"`, logged. The capture is deleted on both paths.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/avatar -q --tb=short`
- **Done when:** both paths produce a head that fits `head_slot`; a test proves the capture file is gone afterwards.

### A6 · Guided scan and garment select
- **Lane:** A · **Expert:** scan-ui-engineer · **Depends on:** S2
- **May edit:** `frontend/components/scan/**`, `frontend/tests/scan/**`
- **Approved dependency:** @mediapipe/tasks-vision (pinned; added to package.json by the lane B human)
- **Goal:** consent screen → face outline with a live quality check → countdown → capture → waist-up outline with a pose check → capture → tap-to-select detected garments with category correction. Quality-check logic is a pure function tested with recorded landmark fixtures.
- **Check:** `cd {WT}/frontend && npx playwright test tests/scan && bash {WT}/.claude/scripts/ui_check.sh {ID} {PORT} /scan`
- **Done when:** tests pass and the consent screen screenshot renders. A human confirms the real webcam flow before merging.

### A7 · Demo reset (backend)
- **Lane:** A · **Expert:** backend-engineer · **Depends on:** S1
- **May edit:** `backend/app/demo/**`, `backend/tests/demo/**`
- **Goal:** `/demo/reset` deletes every guest avatar, guest garment, and their outfits and renders.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/demo -q --tb=short`
- **Done when:** a test seeds guest and non-guest data, calls reset, and only non-guest records remain.

### H1 · HUMAN (lane A): wire A-lane endpoints in `backend/app/routes_a.py`; test a real scan on both of you.

---

## Lane B · Recommend & render

### B1 · Gemini wrapper
- **Lane:** B · **Expert:** gemini-integrator · **Depends on:** S1
- **May edit:** `backend/app/gemini/**`, `backend/tests/gemini/**`
- **Approved dependencies:** the official Gemini Python SDK, psycopg (pinned)
- **Goal:** `classify(cutout)`, `rerank(candidates)`, `generate_head(face, style_ref)`, each with a schema or output check, one retry, a timeout, an on-disk cache keyed by input hash, and a rate limiter. Typed errors, never swallowed. Every call is written to `app_api_calls` via `APP_LOG_DATABASE_URL`; a logging failure prints to stderr and never breaks the call.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/gemini -q --tb=short`
- **Done when:** tests pass on recorded responses, including one proving a logging failure doesn't break a call. The REPLY includes a short interface summary to relay to lane A. A human runs one live smoke test per method.

### B2 · Candidates and scorer
- **Lane:** B · **Expert:** recommender-engineer · **Depends on:** S1
- **May edit:** `backend/app/recommend/__init__.py`, `backend/app/recommend/candidates.py`, `backend/app/recommend/scorer.py`, `backend/tests/recommend/test_candidates.py`, `backend/tests/recommend/test_scorer.py`
- **Spec:** `SCORER.md`, followed exactly, including its test expectations. The architect names it under Context.
- **Goal:** closet + anchor → every valid combination (top + bottom + shoes, or dress + shoes, optional outerwear), owned and catalog both eligible; score and breakdown `{hue, pattern, formality}` with neutrals as wildcards, harmony in LCh, penalties for more than one bold pattern and wide formality spread. Weights in one config block.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/recommend -q --tb=short`
- **Done when:** tests cover no shoes, no bottoms, dress only, outerwear anchor, and hand-picked good/bad pairs rank as expected.

### B3 · Re-rank and reasons
- **Lane:** B · **Expert:** recommender-engineer · **Depends on:** B1, B2
- **May edit:** `backend/app/recommend/rerank.py`, `backend/tests/recommend/test_rerank.py`
- **Goal:** top-N candidates → Gemini ordering + one reason each; IDs validated against the input; on any failure, scorer order with template reasons, logged. Next outfit and swap-one-piece helpers.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/recommend/test_rerank.py -q --tb=short`
- **Done when:** tests prove invalid IDs are rejected and the fallback produces reasons.

### B4 · Compositor
- **Lane:** B · **Expert:** render-engineer · **Depends on:** contract
- **May edit:** `backend/app/render/**`, `backend/tests/render/**`
- **Approved dependency:** Pillow (pinned)
- **Goal:** avatar head + outfit → one PNG: each cutout scaled from its bbox into its anchor slot, layered pants → top → outerwear → arms overlay, head in `head_slot`, shoes in `shoes_area`. Works with the placeholder body until the drawing lands.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/render -q --tb=short`
- **Done when:** every fixture outfit renders; PNGs are saved to `.claude/tasks/{ID}/evidence/`.

### B5 · Closet screen
- **Lane:** B · **Expert:** frontend-engineer · **Depends on:** S2
- **May edit:** `frontend/components/closet/**`, `frontend/app/closet/**`, `frontend/tests/app/closet/**`
- **Goal:** the closet from the team's drawing: cutouts with swatches, owned vs catalog marked, edit sheet for category and colors. Fixture and live mode.
- **Check:** `bash .claude/scripts/ui_check.sh {ID} {PORT} /closet`
- **Done when:** the build passes and the screenshot matches the drawing's layout.

### B6 · Outfit screen, save look, reset
- **Lane:** B · **Expert:** frontend-engineer · **Depends on:** S2
- **May edit:** `frontend/components/outfit/**`, `frontend/app/outfit/**`, `frontend/tests/app/outfit/**`
- **Goal:** Make outfits → dressed avatar image + reason + catalog pieces labeled "you'd need to buy this"; Next outfit; swap one piece; Save look (download the PNG); Reset demo closet (calls `/demo/reset`).
- **Check:** `cd {WT}/frontend && npx playwright test tests/app/outfit && bash {WT}/.claude/scripts/ui_check.sh {ID} {PORT} /outfit`
- **Done when:** the interaction tests pass in fixture mode and the screenshot renders.

### H2 · HUMAN (lane B): wire B-lane endpoints in `backend/app/routes_b.py`; tune scorer weights by eye.

---

## QUEUE · Safe for overnight agents (announced like any task)

### QA1 · Test gaps: pipeline and avatar
- **Lane:** A · **Expert:** cv-pipeline-engineer
- **May edit:** `backend/tests/pipeline/**`, `backend/tests/avatar/**` (new files only)
- **Goal:** tests for untested branches in merged modules. Never modify existing tests.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/pipeline tests/avatar -q --tb=short`

### QA2 · Scan loading and error states
- **Lane:** A · **Expert:** scan-ui-engineer
- **May edit:** `frontend/components/scan/states/**`
- **Goal:** loading, empty, and error states for the scan flow, using existing components only.
- **Check:** `bash .claude/scripts/ui_check.sh {ID} {PORT} /scan`

### QB1 · Gap finder
- **Lane:** B · **Expert:** recommender-engineer
- **May edit:** `backend/app/recommend/gaps.py`, `backend/tests/recommend/test_gaps.py`
- **Goal:** for each category × color family not in the closet, count new valid outfits above threshold it would unlock; return the top 3.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/recommend/test_gaps.py -q --tb=short`

### QB2 · Closet and outfit loading and error states
- **Lane:** B · **Expert:** frontend-engineer
- **May edit:** `frontend/components/closet/states/**`, `frontend/components/outfit/states/**`
- **Goal:** loading, empty, and error states for those screens, using existing components only.
- **Check:** `bash .claude/scripts/ui_check.sh {ID} {PORT} /closet /outfit`

### QB3 · Devpost draft
- **Lane:** B · **Expert:** docs-writer
- **May edit:** `docs/devpost.md`
- **Goal:** draft the write-up from PRD.md and the registry. No claims beyond what's verified.
- **Check:** `test -s {WT}/docs/devpost.md`

### QB4 · Test gaps: recommend
- **Lane:** B · **Expert:** recommender-engineer
- **May edit:** `backend/tests/recommend/**` (new files only)
- **Goal:** as QA1, for the recommend modules.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/recommend -q --tb=short`

### QB5 · Test gaps: render
- **Lane:** B · **Expert:** render-engineer
- **May edit:** `backend/tests/render/**` (new files only)
- **Goal:** as QA1, for the render module.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/render -q --tb=short`

### QB6 · Test gaps: Gemini wrapper
- **Lane:** B · **Expert:** gemini-integrator
- **May edit:** `backend/tests/gemini/**` (new files only)
- **Goal:** as QA1, for the Gemini wrapper.
- **Check:** `cd {WT}/backend && {PY} -m pytest tests/gemini -q --tb=short`
