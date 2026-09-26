# Avatar lane — domain notes

Why the lane works the way it does. Rules and scope are in `.claude/agents/avatar.md`;
every resolved value is in the Avatar section of `contract/DECISIONS.md`. The render polling
contract the frontend builds against is in `coordination/BACKEND_API.md`.

## The job
A standing, front-facing photo becomes a line-art avatar drawn from MediaPipe Pose landmarks,
with the real face composited at the head. Outfits are composited onto it locally and
returned at once; Gemini try-on is a background enhancement that may never arrive.

## The two-stage render
`POST /api/render` returns `{render_id, status, local_url}` immediately — the local composite
is always present and always correct. Generation runs in the background; `GET
/api/render/{render_id}` reports `pending` → `done` (with `generated_url`) or `failed`.
The render_id is the cache key for `(user, top_id, bottom_id, jacket_id)` and is stored in the
`renders` collection so it survives a restart. Failure is silent: the local composite stays.

## Layering and media rules
- Draw order: bottom → top-or-dress → jacket. A dress layers over the bottom; no exclusion logic.
- Garments are placed with the landmark-normalized anchors in `contract/ARTIFACT_SPEC.md`,
  never absolute pixels — every body is a different size.
- All returned media URLs are relative (`/media/...`); run `python tools/check_media.py`.
- Previews go to `media/_preview/`.

## Ship order
A1 capture + pose validation → A2 rig → A3 assembly → A4 placement → A5 local composite →
A6 endpoint → A8 backup avatar → A9 robustness. A7 (Gemini generation + ΔE verification) is
severable; A10 stylization and A11 VTON are optional. MediaPipe needs Python 3.12
(`.venv/Scripts/python.exe`).
