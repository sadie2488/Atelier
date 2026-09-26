# TASKS.md — work list for two people, two agents

Each person works down their lane's list **in order** with their Claude Code agent (`/task <ID>`). Tasks marked ⇄ depend on the other lane: check that the dependency is merged into `main` and pull before starting.

Each task lists its **files** (stay inside them), **depends on**, **goal**, and **check** (the command that must pass before committing). Backend checks run from `backend/` with the venv active; frontend checks run from `frontend/`.

---

## Setup (both, before any task)

### H0 · Setup (humans)
- Follow **Setup** in `WORKFLOW.md`: accounts, repo, venv, frontend app, hello-world deploy.
- Lane A reviews `contract/CONTRACT_NOTES.md`, runs `python3 -m contract.check_contract`, then commits `contract/FROZEN` and pushes.
- Lane B: the Next.js rewrite proxies both `/api/*` and `/media/*` to the backend.

---

## Lane A · Scan & avatar (person with more CV experience)

Order: **S1 → A1 → A2 ⇄ → A3 → A4 → A5 ⇄ → A6 ⇄ → A7**

### S1 · Backend scaffold (do this first; lane B's B1 waits on it)
- **Files:** `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/routes_a.py`, `backend/app/routes_b.py` (stub only), `backend/app/routes_scaffold.py`, `backend/tests/test_scaffold.py`, `backend/tests/conftest.py`, `backend/pytest.ini`, `backend/requirements.txt`, `backend/Dockerfile`, `backend/.env.example`
- **Depends on:** contract frozen
- **Goal:** FastAPI app serving every entry in `contract.schemas.ENDPOINTS` from `contract/fixtures/api/*.response.json`, plus `/media/*` static files. `main.py` includes `routes_a.py` and `routes_b.py`, so each lane later replaces fixture routes in its own file. `pytest.ini` sets `pythonpath = ..`; the Dockerfile copies `contract/` next to `backend/`.
- **Check:** `pytest tests/test_scaffold.py -q --tb=short` (every response validates against its model)

### A1 · Flat-lay pipeline
- **Files:** `backend/app/pipeline/` (`preprocess.py`, `bgremove.py`, `color.py`), `backend/tests/pipeline/`, `backend/scripts/golden_flatlay.py`
- **Depends on:** S1
- **Dependencies to install:** opencv-python-headless, rembg, scikit-learn, scikit-image
- **Goal:** image → EXIF-corrected, long side 1024 px, gray-world white balance; flat-lay → transparent cutout + bbox (error if the mask covers under 3% or over 95%); cutout → 1–4 colors `{lab, lch, hex, weight}` from opaque pixels only, merged below ΔE2000 8, dropped under 10%, with `is_neutral`. Thresholds come from `contract/enums.py`.
- **Check:** `pytest tests/pipeline -q --tb=short && python scripts/golden_flatlay.py` (dominant color family right on ≥ 80% of the seed photos)
- **Human:** photograph the ~15 seed items flat-lay on one plain sheet in consistent light while the agent works.

### A2 · Garment classification ⇄ needs B1
- **Files:** `backend/app/pipeline/classify.py`, `backend/tests/pipeline/test_classify.py`
- **Goal:** cutout → category, subcategory, pattern, formality, style_tags via the Gemini wrapper's `classify`. One retry on schema failure, then status `needs_review`.
- **Check:** `pytest tests/pipeline/test_classify.py -q --tb=short` (recorded responses); then one live run on the seed photos scores ≥ 90% on category.

### A3 · Seed and catalog loader
- **Files:** `backend/scripts/load_seed.py`, `backend/tests/pipeline/test_load_seed.py`
- **Goal:** batch-ingest a folder through the real pipeline with `ownership` owned or catalog; idempotent; prints a summary table. Load the seed closet and the sample catalog.
- **Check:** `pytest tests/pipeline/test_load_seed.py -q --tb=short` (loading twice leaves one record per image)

### A4 · Clothing segmentation and ingest endpoints
- **Files:** `backend/app/pipeline/segment.py`, `backend/app/routes_a.py`, `backend/tests/pipeline/test_segment.py`
- **Dependencies to install:** transformers, torch (CPU)
- **Goal:** waist-up capture → one region per garment class (skin and hair excluded, small regions dropped) → candidates. Real `POST /ingest` and `POST /ingest/{photo_id}/select` in `routes_a.py`, matching the contract. Weights load once at startup. Originals deleted after ingest.
- **Check:** `pytest tests/pipeline/test_segment.py -q --tb=short`; every labeled top in scans of both of you comes back as a candidate.

### A5 · Avatar head ⇄ needs B1
- **Files:** `backend/app/avatar/`, `backend/app/routes_a.py`, `backend/tests/avatar/`
- **Goal:** `POST /avatar`: face capture → drawn head through the wrapper's `generate_head` with the team's style reference; on failure or timeout, the photo fallback (face cut out), `head_source: "photo_fallback"`, logged. The capture is deleted either way.
- **Check:** `pytest tests/avatar -q --tb=short` (both paths fit `head_slot`; the capture file is gone)

### A6 · Guided scan and garment select UI ⇄ needs S2
- **Files:** `frontend/components/scan/`, `frontend/tests/scan/`
- **Dependencies:** @mediapipe/tasks-vision (lane B adds it to `package.json`)
- **Goal:** consent screen → face outline with live quality check → countdown → capture (fire `/avatar` without waiting) → waist-up outline with pose check → capture → tap-to-select detected garments with category correction. Quality-check logic is a pure function tested with recorded landmarks.
- **Check:** `npx playwright test tests/scan && npm run build`; then the human runs the real webcam flow.

### A7 · Demo reset
- **Files:** `backend/app/demo/`, `backend/app/routes_a.py`, `backend/tests/demo/`
- **Goal:** `POST /demo/reset` deletes every guest avatar, guest garment, and their outfits and renders.
- **Check:** `pytest tests/demo -q --tb=short` (only non-guest records remain)

---

## Lane B · Recommend & render

Order: **S2 → B1 ⇄ → B4 → B2 → B3 → B5 → B6**

### S2 · Frontend scaffold (do this first; lane A's A6 waits on it)
- **Files:** `frontend/` app scaffold: `app/layout.*`, `app/page.*`, `app/fixtures/`, `lib/`, `public/`, `package.json`, `package-lock.json`, `tsconfig.json`, `.env.example`
- **Depends on:** contract frozen
- **Dependencies:** next, react, react-dom, typescript, @playwright/test, json-schema-to-typescript, @mediapipe/tasks-vision (for lane A)
- **Goal:** typed API client whose types are generated from `contract/schema.json` (an npm script), and a fixture mode (`NEXT_PUBLIC_API_MODE=fixtures`) that serves `contract/fixtures/api/*.response.json`. A `/fixtures` page lists the fixture garments.
- **Check:** `npm run build`; the human opens `/fixtures` in fixture mode.

### B1 · Gemini wrapper ⇄ needs S1 (lane A's A2 and A5 wait on it)
- **Files:** `backend/app/gemini/`, `backend/tests/gemini/`
- **Dependencies to install:** google-genai
- **Goal:** `classify(cutout)`, `rerank(candidates)`, `generate_head(face, style_ref)`, each with a schema or output check, one retry, a timeout, an on-disk cache keyed by input hash, and a simple rate limiter. Typed errors, never swallowed.
- **Check:** `pytest tests/gemini -q --tb=short` (recorded responses); the human runs one live call per method. Post the function signatures for lane A.

### B4 · Compositor
- **Files:** `backend/app/render/`, `backend/app/routes_b.py`, `backend/tests/render/`
- **Dependencies to install:** Pillow
- **Goal:** `POST /render`: avatar head + outfit → one PNG. Each cutout scaled from its bbox into its anchor slot in `contract/template_body.json`, layered bottom → dress → top → outerwear → arms, head in `head_slot`, shoes in `shoes_area`. Works with the placeholder body until the drawing lands.
- **Check:** `pytest tests/render -q --tb=short`; the human looks at the rendered fixture outfits.

### B2 · Candidates and scorer
- **Files:** `backend/app/recommend/` (`candidates.py`, `scorer.py`), `backend/tests/recommend/`
- **Spec:** `SCORER.md`, exactly, including its test expectations.
- **Goal:** closet + anchor → every valid combination (top + bottom + shoes, or dress + shoes, optional outerwear; owned and catalog both eligible) → scored and ordered per `SCORER.md`.
- **Check:** `pytest tests/recommend -q --tb=short` (all `SCORER.md` expectations pass)

### B3 · Re-rank, reasons, next and swap
- **Files:** `backend/app/recommend/rerank.py`, `backend/app/routes_b.py`, `backend/tests/recommend/test_rerank.py`
- **Goal:** real `POST /recommend` and `POST /recommend/swap`: top candidates → Gemini ordering + one reason each; IDs validated; on any failure, scorer order with `SCORER.md` template reasons, logged. `offset`/`limit` give Next outfit. Results cached.
- **Check:** `pytest tests/recommend -q --tb=short` (invalid IDs rejected; fallback produces reasons)

### B5 · Closet screen
- **Files:** `frontend/components/closet/`, `frontend/app/closet/`, `frontend/tests/app/closet/`
- **Goal:** the closet from the team's drawing: cutouts with swatches, owned vs catalog marked, edit sheet for category and colors. Works in fixture and live mode.
- **Check:** `npm run build`; the human compares `/closet` with the drawing.

### B6 · Outfit screen, save look, reset button
- **Files:** `frontend/components/outfit/`, `frontend/app/outfit/`, `frontend/tests/app/outfit/`
- **Goal:** Make outfits → dressed avatar + reason + catalog pieces labeled "you'd need to buy this"; Next outfit; swap one piece; Save look (download the PNG); Reset demo closet.
- **Check:** `npx playwright test tests/app/outfit && npm run build`; the human clicks through in fixture mode.

---

## Spare-time tasks (only when your lane is ahead)

- **Lane A:** tests for untested branches in merged pipeline and avatar code; loading and error states for the scan flow.
- **Lane B:** gap finder (`backend/app/recommend/gaps.py`: the missing category × color family that unlocks the most outfits above threshold); loading and error states for closet and outfit; Devpost draft in `docs/devpost.md`.
- **Stretch** (after Rung 2, see PRD Section 3): lane A live AR; lane B generative try-on render.
