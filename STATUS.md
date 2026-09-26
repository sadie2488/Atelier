# STATUS.md — live coordination between Lane A and Lane B

A status board, not a log. Both agents read this before starting a task and
write to it when starting and finishing one, so scope conflicts show up
immediately instead of surfacing as a merge conflict or a broken build later.

## In progress

| Lane | Task | Files (scope) | Started |
| --- | --- | --- | --- |
<!-- Add a row here right after you start a task. Remove it (move to
     Recently finished below) as soon as you're done — a stale row here
     reads as "still being edited" to the other lane. -->

## Recently finished

| Lane | Task | Files touched | Check result | Notes for the other lane |
| --- | --- | --- | --- | --- |
| A | A1 | backend/app/pipeline/{__init__,preprocess,bgremove,color}.py, backend/tests/pipeline/test_flatlay.py, backend/scripts/golden_flatlay.py, requirements.txt | `pytest tests/pipeline` 13 passed; golden 13/16 = 81% on `fixtures/flatten/` | **Two-tone garments:** `colors[0]` is the largest-area color (often a neutral cream base) per contract, so `is_neutral` can be true for e.g. a green-striped sweater; the pattern color is in `colors[1:]`. Scorer may want to look past `colors[0]`. Golden counts a hit if the labelled family is any extracted color (human decision). Added onnxruntime (rembg needs it) + A1 deps to requirements. rembg downloads u2net (~176 MB) on first use. |
| A | S1 | backend/app/{__init__,main,routes_a,routes_b,routes_scaffold}.py, backend/tests/{conftest,test_scaffold}.py, backend/pytest.ini, requirements.txt, Dockerfile, .env.example | `pytest tests/test_scaffold.py` 13 passed | All routes under `/api` prefix. Replace fixture routes in `routes_b.py`: build your own `APIRouter`, keep `LANE_B_PATHS` (routes_a excludes those paths). `routes_scaffold.fixture_router(endpoints_for({...}))` serves any remaining fixtures. Media dir = `backend/media` (override `MEDIA_DIR`). Docker: build from repo root, `docker build -f backend/Dockerfile .`. Added `pytest` to requirements. |
<!-- Move your row here from "In progress" when you finish. Keep the
     "Notes" column for things the other lane actually needs: a function
     signature they'll call, a schema field you added, a fixture you
     changed. Leave it blank if there's nothing to flag. -->

## Rules

- **Before starting:** check the **In progress** table. If any row's files
  overlap with the files your task lists, stop and tell your human before
  touching anything — don't assume it's safe just because your lane "owns"
  that folder on paper.
- **A row older than a couple of hours with no matching commit on `main`**
  is probably stale (laptop closed, session cleared). Don't treat it as a
  hard lock — flag it to your human instead of either barging in or
  blocking indefinitely.
- This board is for scope/overlap visibility, not a replacement for
  `git pull` — always pull before starting a task regardless of what this
  file says.
