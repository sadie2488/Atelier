# Frontend → Backend

**Written by: the frontend agent/session only.** The backend PM reads this every dispatch
cycle and responds by editing `coordination/BACKEND_API.md` — **not** by editing this file.
Two writers on one file is how you get merge conflicts between two laptops.

**Cadence:** append an entry the moment you are blocked or notice a mismatch, then push. Do
not batch requests; a blocked frontend and a backend that does not know is the most expensive
state in this project.

---

## How to use this

Append a new row. Newest at the top. Leave `Status` and `Resolution` blank — the PM fills
those in when it responds, and points you at the `BACKEND_API.md` change.

**Types:**

- `BLOCKED` — you cannot proceed. The PM treats these first.
- `MISMATCH` — the API behaves differently than `BACKEND_API.md` says. Include what you sent,
  what you expected, what you got.
- `REQUEST` — you need a field, an endpoint, or a behavior that does not exist.
- `QUESTION` — a behavior is unspecified and you do not want to guess.
- `FYI` — a frontend decision the backend should know about.

**When you are blocked, keep building against a mock** shaped like `BACKEND_API.md` and flag
it here. Do not wait idle, and do not silently invent a different shape — an undeclared mock
that diverges from the real API is worse than being blocked, because nobody finds out until
integration.

---

## Open

| # | Type | Raised | Detail | Status | Resolution |
|---|---|---|---|---|---|
| 8 | FYI | 2026-09-26 | **Handoff for redelegation: frontend status.** The human ran the ported UI against the real backend and reports it runs fine; the frontend is ready for review on branch `frontend/port-lovable-ui` (not merged to `main`). **Frontend done:** all five screens (`/`, `/closet`, `/scan` with consent, 5 s countdown and backup-avatar trigger, `/add-item`, `/stylist` with the two-stage render and silent swap), typed client generated from `contract/schema.json`, whole-body 1:2 avatar layout, degraded/empty/error states. **Frontend remaining (unstarted, needs a call):** (a) auto-capture on the scan screen when the user is correctly positioned: needs approval for the `@mediapipe/tasks-vision` dependency and a decision to bundle the model in `frontend/public/` (about 30-45 min); (b) Playwright tests for the flows (needs approval for `@playwright/test`); (c) set `BACKEND_URL` in Vercel and deploy, then check `/api/health` through the Vercel URL; (d) `NEXT_PUBLIC_BACKUP_AVATAR_ID` once the backup avatar exists (#1); (e) merge `main` into the branch and rebuild before merging. **Needs backend or PM:** #1 backup avatar id, #2 color extraction on the green polo fixture (may be covered by OPEN_QUESTIONS #2), #5 updated `MONGODB_URI` everywhere, #7 real full-body avatar (decision A-B3 reversal). **Not verified by the frontend agent:** add-item `save`, and the generated-image swap timing on the deployed URL. | | |
| 7 | REQUEST | 2026-09-26 | **Avatar should be the user's real body, not the drawn mannequin.** Product ask from the human: the avatar shown in the closet, the stylist and the scan reveal should be the real image of the user's whole body (head to feet), cut out of their scan photo, instead of the line-art figure with a composited face (DECISIONS A-B3). **Why it matters:** the current avatar is a tube-limbed mannequin with no feet or hands and a lot of empty margin (seen in a live scan); it does not read as "me", and outfits composited on it look flat. **What we suggest (backend decides feasibility):** (1) at `POST /api/avatar/scan`, segment the person from the background (the pose landmarks are already computed, and clothing segmentation already exists in the ingest lane) and return the cutout as a transparent PNG, head to feet, on the 600x1200 template canvas; keep the pose landmarks as the source for garment anchors so `/api/render` placement is unchanged; (2) keep the current wireframe as `wireframe_url` (it is the render loading state); (3) a cutout of the person still wearing their own clothes is a problem for try-on, so either ask the user to scan in a fitted base layer, inpaint/erase their clothing, or keep the mannequin body below the neck and only swap in the real head as today (fallback). **Frontend impact:** none if `avatar_url` stays a full-figure transparent PNG on 1:2; the frontend already fits it by height with no cropping. **Contract:** no schema change needed if the fields stay the same, but this reverses decision A-B3, so it needs a PM/DECISIONS call (also logged in `contract/OPEN_QUESTIONS.md` #3). | | |
| 6 | FYI | 2026-09-26 | **Frontend port is done but only partly verified against the real backend.** The Lovable design is ported to Next.js (`/`, `/closet`, `/scan`, `/add-item`, `/stylist`); build and lint pass. Verified on the frontend laptop with the real backend and Atlas: `/api/health`, `/api/items` (19 items), `/api/outfits/generate`, `/media/*`, `POST /api/items/analyze` (multipart, ~10 s, 3 candidates) and `/api/items/reject`, all through the Next `/api` rewrite. **Not verified:** `/api/avatar/scan`, `/api/render` and its polling swap (no avatar exists in the DB yet, and the fixture id `avatar_427165` returns `not_found`), `/api/items/save`, and the UI in a real browser. The first real scan on this laptop will exercise them. | | |
| 5 | FYI | 2026-09-26 | **MongoDB access.** The Atlas user's password was changed on this laptop after the old one was pasted into a chat transcript. Anything else using that database user (the PM's backend, deployed App Platform env vars, the other laptop's `backend/.env`) needs the new `MONGODB_URI`. The frontend laptop's backend also needed `pip install -r backend/requirements.txt` (the venv had no pip and no numpy) after pulling. **PM: please confirm the deployed backend and your own `.env` have the updated URI.** | | |
| 4 | FYI | 2026-09-26 | **Renders fire on selection.** The stylist calls `POST /api/render` about 0.5 s after the tops/bottoms/jacket selection settles (including on plain swipes), because the frontend may not composite garments itself. Each new combination can start a Gemini generation; repeats hit the cache. If that cost is a problem, say so and the frontend will limit rendering to the "generate outfit" button. | | |
| 3 | FYI | 2026-09-26 | **Removed/decided in the UI:** the Lovable "color palette" button has no API behind it and was dropped. Bottoms include `pants` (BACKEND_API valid pairs), and there is no shoes category. "none of these" on the cutout picker calls `POST /api/items/reject`. `frontend/.gitignore` matches `.env*`, so `frontend/.env.example` (BACKEND_URL, NEXT_PUBLIC_BACKUP_AVATAR_ID) is ignored by git; add an exception if it should be committed. | | |
| 2 | MISMATCH | 2026-09-26 | **Color extraction looks wrong on a fixture.** Sent `fixtures/images/sharp green Whoa So Soft Fitted Sweater Polo #048c57.png` to `POST /api/items/analyze` (`category=tops`, `garment_type=shirt`). Expected a green primary color (about `#048c57`); got `primary_color.hex` `#d2cdb7`, name "cream", `is_neutral: true` for all three candidates (`#d2cdb7`, `#d3ceb8`, `#dddac7`). The cutout may include the light background, or sampling is off. The detail panel shows this swatch next to the retailer color, so a wrong swatch is visible to judges. | | |
| 1 | QUESTION | 2026-09-26 | **Backup avatar id.** The frontend has a one-action trigger: a "use backup avatar" button on `/scan`, and `/scan?backup=<avatar_id>` (or `?backup=1`) which calls `GET /api/avatar/{id}` and stores it as the current avatar. The id comes from `NEXT_PUBLIC_BACKUP_AVATAR_ID` (see `frontend/.env.example`); the button is hidden while it is unset. **Backend PM: please prompt the human to do the real pre-scan (A8), then tell us the `avatar_id` (or expose it another way, e.g. an endpoint) so it can be set in Vercel.** | | |

## Resolved

| # | Type | Detail | Resolution |
|---|---|---|---|
| — | — | *(none yet)* | — |

---

## Scope boundary

The two halves are split cleanly. Raise anything that crosses this line **here, before
building it** — do not implement across the boundary and do not assume the other side has it
covered.

**Frontend owns:** camera capture and the pose outline overlay, client-side downscaling, swipe
lists and their rendering, the generate button, positioning garments at index 0, the metadata
detail panel, polling and the image swap, all loading and degraded states, the backup-avatar
shortcut, the consent line.

**Backend owns:** every endpoint, segmentation and cutouts, color extraction, scoring and
outfit selection, avatar assembly, local compositing, generation and its verification, caching,
all media files.

**Grey areas — raise as `QUESTION`, do not decide unilaterally:**

- Which side enforces an image size or dimension limit
- Whether a value is computed server-side or derived in the client
- Anything that would mean the same logic existing on both sides

If you find yourself writing color logic, scoring logic, or garment placement logic in the
frontend, stop and raise it. That work belongs to a backend lane and duplicating it will
diverge.
