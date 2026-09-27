# Backend → Frontend

**Written by: the backend PM agent only.** The frontend reads this and never edits it. To
request a change, write in `coordination/FRONTEND_REQUESTS.md`.

**Authority:** where this document and the frozen contract in `contract/` disagree, **the
frozen contract wins.** This is a readable summary plus behavioral detail the contract does
not encode. Report any disagreement you find.

**Cadence:** the PM updates this whenever an endpoint, shape, or behavior changes, and pushes
immediately. The frontend pulls before starting any task. A stale read here costs rework on
both sides.

---

## PM responses to FRONTEND_REQUESTS (2026-09-26)

Answers to #1–#7 on branch `frontend/port-lovable-ui`. The PM fills in the Status and
Resolution columns in `FRONTEND_REQUESTS.md` after the merge, so don't edit those rows.

**Action needed before merge (push to `frontend/port-lovable-ui`, then tell the PM):**

- **#4: render on explicit action only.** Don't call `POST /api/render` on swipe or selection
  (DECISIONS A-R1: "render on click only; no speculative work"). Every new combination starts a
  paid ~10 s Gemini generation. Trigger it only from an explicit "See it on me" button and after
  "Generate outfit" positions the lists. Keep the two-stage display and the polling as they are.
- **#3:** add `!.env.example` to `frontend/.gitignore` so the example env file is committed.
- **#1: backup avatar.** `NEXT_PUBLIC_BACKUP_AVATAR_ID=avatar_f709dc` (alternative:
  `avatar_56501c`). Both are real scans. Put it in `frontend/.env.example` and in Vercel.

**Answers, no action needed:**

- **#2 (green polo → cream):** known limitation, not a bug. The polo is mostly cream with thin
  green stripes. The primary color is the largest area, and the stripes cover under 20% of the
  fabric, so they don't count as a secondary color either. Display the color as returned.
- **#5:** done. The PM's `backend/.env` and DigitalOcean have the new `MONGODB_URI`.
- **#6:** scan and render can be tested now. `avatar_f709dc` exists with cached, completed
  try-ons for these combinations (instant `done` on the first `POST /api/render`):
  `dress_6b8577 + bottom_f91783`, the same plus `jacket_18d0da`, and
  `top_9a92f8 + bottom_e7883c`.
- **#7 (real-body avatar): approved** by the human (DECISIONS A-B3 updated). `avatar_url`
  becomes the user's real body cut out of the scan photo, head to feet, on a transparent 1:2
  canvas. `wireframe_url` stays the line-art loading state. There is **no schema change**; keep
  fitting the avatar image by height. It lands on `main` shortly; existing avatar ids stay the
  same.

**Deployed backend:** DigitalOcean is still being switched from the Python buildpack to the
Dockerfile. Until `https://atelier-9t24w.ondigitalocean.app/api/live` returns
`{"status":"ok"}`, run the backend locally (see below).

## Connecting the frontend

**Status (2026-09-26):** every endpoint below is live on `main`.

1. **Run the backend** (repo root, `backend/.env` with `MONGODB_URI` and `GEMINI_API_KEY`).
   It needs **Python 3.12** — MediaPipe has no 3.13/3.14 build. First time only, build the venv
   from the requirements (a venv made for the old hello-world backend lacks numpy, MediaPipe,
   etc.):
   ```
   py -3.12 -m venv .venv            # or: uv venv .venv --python 3.12   (macOS/Linux: python3.12 -m venv .venv)
   .venv/Scripts/python.exe -m pip install -r backend/requirements.txt   # macOS/Linux: .venv/bin/python
   ```
   Then run it:
   ```
   .venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000
   ```
   Check `http://localhost:8000/api/health` → `{"status":"ok","db":"ok"}`.
2. **Run the frontend** (`frontend/`): `npm run dev`. `next.config.ts` already rewrites `/api/*`
   and `/media/*` to `BACKEND_URL` (default `http://localhost:8000`). **Always call relative
   paths** (`fetch("/api/items")`, `<img src={item.cutout_url}>`) — never the backend host — so
   the same code works locally and deployed.
3. **Types:** generate TypeScript from `contract/schema.json`, e.g.
   `npx json-schema-to-typescript ../contract/schema.json -o lib/api-types.ts`. Regenerate when
   this changelog says the contract changed.
4. **Before the backend is reachable** (or for UI work without a backend), use the examples in
   `contract/fixtures/api/<name>.response.json` — one per endpoint.
5. **Deployed:** set `BACKEND_URL` in Vercel to the deployed backend's base URL.

**Behaviors to wire first** (details in the sections below): analyze → pick one of 3 → save;
the closet lists (stable order); "generate outfit" moves the top outfit's garments to index 0;
scan with the pose outline and show the rejection message; render → show `local_url` at once →
poll `GET /api/render/{id}` (1s for 15s, then 3s, give up at 45s) → swap in `generated_url`
silently. Tell the user before capture that the photo is sent to Google's Gemini API (A-R18).

## Conventions

- All API routes are under `/api`. Media is served from `/media` at the top level.
- **Uploads are `multipart/form-data`. Everything else is JSON.**
- **All media URLs returned are relative** (`/media/...`), never absolute. The Vercel rewrite
  resolves them. An absolute URL would work locally and break in production.
- No file size cap is enforced server-side. **Downscale captures client-side to ~1080px on the
  long edge** — not as a restriction, as latency. Most of a phone photo's resolution is unused
  by segmentation and generation, and upload time is the user-visible cost.
- Errors return a contract-shaped error body, never a bare string or stack trace:
  `{"error": {"code": "<ErrorCode>", "message": "<human-readable>"}}`. Codes: `invalid_request`,
  `not_found`, `pose_rejected` (message is the actionable reason), `no_person_detected`,
  `unsupported_image`, `analyze_failed`, `handle_expired`, `gemini_unavailable`,
  `not_implemented` (501 while a lane hasn't built the route yet), `internal_error` (500, unexpected failure).
- **Types and examples:** generate TypeScript from `contract/schema.json`. Every endpoint has a
  request/response example in `contract/fixtures/api/` — build against those until the real
  route lands.
- **ID formats:** items `top_a3f9c2` / `dress_…` / `bottom_…` / `jacket_…` (prefix follows
  `garment_type`); `tmp_<12 hex>` temp handles; `avatar_<6 hex>`; `outfit_<6 hex>`;
  `render_<12 hex>`.

---

## Health

**`GET /api/health`** → `{"status":"ok","db":"ok"}`

Useful to keep open in a tab during the demo — it distinguishes a backend failure from a
venue network failure instantly.

---

## Ingest (two steps, always)

Nothing persists until step two. This is a contract requirement, not an implementation detail.

### `POST /api/items/analyze`

`multipart/form-data`: the image, plus user-supplied `category` (`tops` | `bottoms` |
`jackets`), user-supplied `garment_type` (`shirt` | `dress` | `pants` | `skirt` | `shorts` |
`jacket` | `coat`), retailer `color` string, retailer `item_name`.

**Both category fields are required.** `category` decides which swipe list the item lands
in; `garment_type` decides how the backend segments it. A dress is `category: tops` with
`garment_type: dress` — sending only the category would have the backend crop it at the hip.
Valid pairs: tops → shirt, dress · bottoms → pants, skirt, shorts · jackets → jacket, coat.

Returns a `temp_handle` and **exactly three candidate cutouts** — tight, balanced, generous —
each with a relative cutout URL and the color fields derived from it. Nothing is in the
database yet.

Latency: p50 ≤5s, p95 ≤9s. The UI should show progress, not a frozen button.

> **Dresses:** a dress is filed under `tops`. It layers over a bottom and does not replace it.
> There is no separate dress category, slot, or mode anywhere in the system.

### `POST /api/items/save`

JSON: `temp_handle` plus the chosen candidate index. Persists the item and its media, and
allocates its permanent id — a readable slug like `top_a3f9c2`. Latency ≤1s.

### `POST /api/items/reject`

JSON: `temp_handle`. The user rejected all three. Nothing persists, no cutouts are kept, and
the backend logs the failure for later analysis. **The user reshoots and ingest restarts from
the beginning** with a fresh handle.

---

## Closet

### `GET /api/items`

Optional `category` filter. Returns items in a **stable order — creation time, newest first.**

Stability matters: "generate outfit" works by moving a garment to position 0 of its list, so
the list must not reshuffle underneath the user between calls.

### `GET /api/items/{slug}`

Full detail for the metadata panel shown when a garment is clicked. Includes the extracted
primary color, secondary color when present, the neutral flags, the retailer's original color
string and item name, and later any enrichment attributes.

> This panel is the natural home for showing the **extracted color swatch beside the
> retailer's name**. The color extraction, the Lab-space analysis, and the segmentation are the
> substantial engineering in this project, and a judge sees none of it in a rendered image.
> This is where it becomes visible.

---

## Outfits

### `POST /api/outfits/generate`

Returns **up to 5** ranked outfits. Each carries an `outfit_id`, a `strategy` label
(e.g. `neutral_anchor`), the garment ids composing it, and an explanation string.

**Behavior the frontend must handle:**

- **Fewer than 5 is normal.** A small closet returns what exists; the backend never pads with
  poor combinations. Render what arrives.
- **The response is a positioning instruction, not a view.** Take the top-ranked outfit and
  move its garments to position 0 of the tops and bottoms lists. The user swipes away freely
  from there. There is no separate outfit-results screen.
- **The swipe never consults the scorer.** Browsing is plain browsing; no reordering by score.
- Every outfit is `bottom + (top or dress) + optional jacket`.
- The explanation may be a generic per-strategy fallback when the language API is unavailable.
  It is always present and always renderable.

---

## Avatar

### `POST /api/avatar/scan`

`multipart/form-data`: the captured photo.

The capture UI must show a **pose outline** the user positions themselves inside — standing,
front-facing, arms slightly away from the body. The backend validates pose landmarks against
that outline.

On success: an `avatar_id`, a wireframe URL, and an avatar URL.
On rejection: **a specific, actionable reason** ("move your arms away from your body"), never a
generic failure. Show the reason and let them retry. A bad base scan degrades every outfit
rendered on it, so rejecting is correct behavior.

### `GET /api/avatar/{avatar_id}`

---

## Rendering — the two-stage swap

**This is the most important interaction to get right, and the only place the two halves
genuinely interlock.**

Two images exist at two different times. The local composite is ready in under a second. The
generated version takes five to fifteen. The first appears immediately; the second replaces it
silently when it arrives.

### `POST /api/render`

JSON: `avatar_id`, `top_id`, `bottom_id`, optional `jacket_id`.

Returns immediately:

```json
{ "render_id": "...", "local_url": "/media/...", "status": "pending" }
```

**Display `local_url` at once.** It is always present and always correct.

If this combination was rendered before, status comes back `done` on the very first call with
`generated_url` already populated — no polling, no generation, no cost. The render id is the
cache key.

### `GET /api/render/{render_id}`

Poll until `status` changes:

- `pending` → keep showing what you have
- `done` → swap `generated_url` in
- `failed` → stop polling, **keep the local composite showing**

**Polling cadence: every 1s for the first 15 seconds, then every 3s. Give up at 45s** and keep
the local composite.

**The swap must be silent.** If generation fails, times out, the quota is exhausted, or the
network drops, the user keeps a correct rendered outfit and never learns anything was missing.
This is what makes a live demo survivable — so **no error toast on render failure**, ever.

**The wireframe is the loading state.** Show the user's wireframe while status is `pending`
rather than a spinner. It is more interesting than a spinner and it is already being built.

Abandonment is harmless. If the user swipes away mid-generation the job still completes and
populates the cache, so returning to that combination is instant.

---

## Behaviors the frontend must implement

These are not optional polish. The live demo depends on them.

1. **Every failure has a visible degraded state, not an error.** No hanging spinners, no blank
   states, no stack traces. Render failure keeps the local composite. Explanation failure shows
   the fallback text.
2. **Stable list order.** Do not re-sort client-side.
3. **Pose outline overlay** during capture, and display of the backend's specific rejection
   reason.
4. **One-action route to the pre-scanned backup avatar** (URL parameter or shortcut) for demo
   fallback.
5. **Progress during analyze.** Five seconds with a dead button reads as broken.

---

## Changelog

Append here on every change so the frontend can diff quickly.

| Date | Change |
|---|---|
| — | Initial version. Polling chosen for the render swap; multipart for uploads; dresses filed under tops. |
| — | Added `garment_type` to analyze — required alongside `category`. |
| 2026-09-26 | Contract 2.0.0 frozen: this document's endpoints are now the contract. Added error codes, ID formats, and pointers to `contract/schema.json` and `contract/fixtures/api/`. Analyze form fields: `category`, `garment_type`, optional `color`, optional `item_name`. `POST /api/outfits/generate` takes `{"limit": 1..5}` (default 5; `{}` is valid). All routes return 501 `not_implemented` until each lane lands. |
| 2026-09-26 | Added error code `internal_error` (500). Items, outfits, avatar scan and render endpoints are live on the backend; render currently returns `status: failed` (local composite only) until Gemini try-on lands. |
